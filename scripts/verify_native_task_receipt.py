#!/usr/bin/env python3
"""Verify a Codex Desktop task receipt from persisted state and installed bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from install_skill import INSTALL_NAMES, installed_manifest, runtime_manifest


THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
REVIEWER_FINAL_FIELDS = (
    "REVIEW_TARGET:",
    "REVIEW_READBACK:",
    "REVIEW_FINDINGS:",
    "REVIEW_RESIDUAL_RISK:",
    "REVIEW_VERDICT: PASS",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def thread_row(database: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    database.row_factory = sqlite3.Row
    row = database.execute(
        """
        SELECT id, rollout_path, source, model_provider, model, reasoning_effort,
               cwd, archived, first_user_message, created_at_ms, updated_at_ms
        FROM threads WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"thread is missing from state database: {thread_id}")
    return dict(row)


def rollout_records(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"rollout is not a regular file: {path}")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rollout JSON at line {number}: {path}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records


def reviewer_binding(
    database: sqlite3.Connection,
    *,
    parent_id: str,
    reviewer_id: str,
    records: list[dict[str, Any]],
    parent_final: str,
) -> dict[str, str]:
    edge = database.execute(
        "SELECT status FROM thread_spawn_edges WHERE parent_thread_id = ? AND child_thread_id = ?",
        (parent_id, reviewer_id),
    ).fetchone()
    if edge is None:
        raise ValueError("reviewer has no native spawn edge from parent")
    metas = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == reviewer_id
    ]
    if len(metas) != 1 or metas[0].get("parent_thread_id") != parent_id:
        raise ValueError("reviewer rollout is not bound to parent thread")
    agent_path = metas[0].get("agent_path")
    if not isinstance(agent_path, str) or not agent_path or agent_path not in parent_final:
        raise ValueError("parent final does not expose the reviewer agent identifier")
    return {
        "parent_thread_id": parent_id,
        "reviewer_thread_id": reviewer_id,
        "reviewer_agent_path": agent_path,
        "spawn_edge_status": str(edge[0]),
    }


def verify_reviewer_read(
    records: list[dict[str, Any]], markers: list[str], artifact: str
) -> dict[str, Any]:
    completion_indexes = [
        index
        for index, record in enumerate(records)
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completion_indexes) != 1:
        raise ValueError("reviewer tool-read ordering cannot be established")
    calls = {
        payload.get("call_id"): str(payload.get("input", ""))
        for index, record in enumerate(records)
        if record.get("type") == "response_item"
        and index < completion_indexes[0]
        and isinstance((payload := record.get("payload")), dict)
        and payload.get("type") == "custom_tool_call"
        and payload.get("name") == "exec"
        and payload.get("status") == "completed"
        and isinstance(payload.get("call_id"), str)
    }
    outputs = {
        payload.get("call_id"): json.dumps(payload.get("output"), ensure_ascii=False)
        for index, record in enumerate(records)
        if record.get("type") == "response_item"
        and index < completion_indexes[0]
        and isinstance((payload := record.get("payload")), dict)
        and payload.get("type") == "custom_tool_call_output"
        and payload.get("call_id") in calls
    }
    if not outputs:
        raise ValueError("reviewer has no completed exec call with bound output")
    combined = "\n".join([*calls.values(), *outputs.values()])
    if artifact not in combined:
        raise ValueError("reviewer tool evidence is not bound to the target artifact")
    for marker in markers:
        if marker not in combined:
            raise ValueError(f"reviewer tool read is missing marker {marker!r}")
    return {"paired_exec_outputs": len(outputs), "artifact": artifact, "markers": markers}


def completed_message(records: list[dict[str, Any]]) -> str:
    messages = [
        record["payload"].get("last_agent_message")
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(messages) != 1 or not isinstance(messages[0], str):
        raise ValueError("task completion message is not unique")
    return messages[0]


def verify_reviewer_schema(final_message: str) -> None:
    fields: dict[str, str] = {}
    for line in final_message.splitlines():
        for field in REVIEWER_FINAL_FIELDS[:-1]:
            if line.startswith(field):
                fields[field] = line[len(field) :].strip()
        if line.startswith("REVIEW_VERDICT:"):
            fields["REVIEW_VERDICT:"] = line.removeprefix("REVIEW_VERDICT:").strip()
    required = [*REVIEWER_FINAL_FIELDS[:-1], "REVIEW_VERDICT:"]
    if any(not fields.get(field) for field in required):
        raise ValueError("reviewer final does not contain the required line schema")
    if not fields["REVIEW_VERDICT:"].startswith("PASS"):
        raise ValueError("reviewer verdict is not PASS")


def verify_thread(
    row: dict[str, Any],
    *,
    expected_model: str,
    expected_effort: str,
    require_archived: bool,
    final_markers: list[str],
) -> dict[str, Any]:
    thread_id = str(row["id"])
    if not THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError(f"invalid thread id: {thread_id}")
    if row["model_provider"] != "openai":
        raise ValueError(f"thread provider is not OpenAI: {thread_id}")
    if row["model"] != expected_model or row["reasoning_effort"] != expected_effort:
        raise ValueError(
            f"thread model identity mismatch: {thread_id}: "
            f"{row['model']}/{row['reasoning_effort']}"
        )
    if require_archived and row["archived"] != 1:
        raise ValueError(f"thread cleanup is incomplete: {thread_id}")

    rollout = Path(str(row["rollout_path"]))
    records = rollout_records(rollout)
    session_meta = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == thread_id
    ]
    if len(session_meta) != 1 or session_meta[0].get("model_provider") != "openai":
        raise ValueError(f"rollout session identity is not uniquely bound: {thread_id}")

    contexts = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("model") == expected_model
        and record["payload"].get("effort") == expected_effort
    ]
    if not contexts:
        raise ValueError(f"rollout does not bind model and effort: {thread_id}")

    completions = [
        record["payload"]
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completions) != 1:
        raise ValueError(f"thread needs exactly one task_complete event: {thread_id}")
    final_message = completions[0].get("last_agent_message")
    if not isinstance(final_message, str) or not final_message.strip():
        raise ValueError(f"thread task_complete has no final message: {thread_id}")
    for marker in final_markers:
        if marker not in final_message:
            raise ValueError(f"thread final is missing marker {marker!r}: {thread_id}")

    return {
        "thread_id": thread_id,
        "provider": row["model_provider"],
        "model": row["model"],
        "reasoning_effort": row["reasoning_effort"],
        "archived": bool(row["archived"]),
        "cwd": row["cwd"],
        "source": row["source"],
        "rollout_sha256": sha256(rollout),
        "task_complete_turn_id": completions[0].get("turn_id"),
        "final_sha256": hashlib.sha256(final_message.encode("utf-8")).hexdigest(),
    }


def git_state(source: Path) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return {
        "head": head,
        "clean": not bool(status),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--parent-id", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--parent-final-marker", action="append", default=[])
    parser.add_argument("--reviewer-final-marker", action="append", default=[])
    parser.add_argument("--reviewer-read-marker", action="append", default=[])
    parser.add_argument("--reviewer-artifact", required=True)
    parser.add_argument("--require-archived", action="store_true")
    parser.add_argument("--require-clean-source", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if "luna" in args.model.lower():
        raise SystemExit("Luna is not allowed for this release receipt")
    if not args.parent_final_marker:
        raise SystemExit("at least one --parent-final-marker is required")
    if not args.reviewer_final_marker:
        raise SystemExit("at least one --reviewer-final-marker is required")
    if not args.reviewer_read_marker:
        raise SystemExit("at least one --reviewer-read-marker is required")
    supplied_markers = (
        args.parent_final_marker
        + args.reviewer_final_marker
        + args.reviewer_read_marker
    )
    if any(len(marker.strip()) < 16 for marker in supplied_markers):
        raise SystemExit("receipt markers must be exact facts of at least 16 characters")
    if not args.require_archived or not args.require_clean_source:
        raise SystemExit("native task receipt requires archived tasks and a clean source")
    source = args.source_root.resolve()
    installed_root = args.installed_root.resolve()
    state_db = args.state_db.resolve()
    if state_db.is_symlink() or not state_db.is_file():
        raise SystemExit(f"state database is not a regular file: {state_db}")

    source_state = git_state(source)
    if args.require_clean_source and not source_state["clean"]:
        raise SystemExit("source worktree is not clean")

    installed: dict[str, dict[str, str]] = {}
    for skill_name in INSTALL_NAMES:
        target = installed_root / skill_name
        observed = installed_manifest(target)
        expected = runtime_manifest(source, skill_name)
        if observed != expected:
            raise SystemExit(f"installed bundle does not match source: {skill_name}")
        installed[skill_name] = observed

    database = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    try:
        parent_row = thread_row(database, args.parent_id)
        parent = verify_thread(
            parent_row,
            expected_model=args.model,
            expected_effort=args.reasoning_effort,
            require_archived=args.require_archived,
            final_markers=args.parent_final_marker,
        )
        if "$agency-chief-of-staff" not in str(parent_row["first_user_message"]):
            raise ValueError("parent task did not explicitly invoke canonical skill")
        parent_records = rollout_records(Path(str(parent_row["rollout_path"])))
        parent_final = completed_message(parent_records)

        reviewer_row = thread_row(database, args.reviewer_id)
        reviewer = verify_thread(
            reviewer_row,
            expected_model=args.model,
            expected_effort=args.reasoning_effort,
            require_archived=args.require_archived,
            final_markers=args.reviewer_final_marker + list(REVIEWER_FINAL_FIELDS),
        )
        reviewer_records = rollout_records(Path(str(reviewer_row["rollout_path"])))
        verify_reviewer_schema(completed_message(reviewer_records))
        binding = reviewer_binding(
            database,
            parent_id=args.parent_id,
            reviewer_id=args.reviewer_id,
            records=reviewer_records,
            parent_final=parent_final,
        )
        reviewer_read = verify_reviewer_read(
            reviewer_records, args.reviewer_read_marker, args.reviewer_artifact
        )
    finally:
        database.close()

    receipt = {
        "receipt_type": "NATIVE_TASK_SMOKE_RECEIPT",
        "status": "verified",
        "source": source_state,
        "installed_bundle_manifests": installed,
        "parent": parent,
        "reviewer": reviewer,
        "reviewer_binding": binding,
        "reviewer_tool_read": reviewer_read,
        "cold_context_isolation": "unverified",
        "agents_md_routing_dependency": False,
    }
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"native task receipt invalid: {exc}") from exc
