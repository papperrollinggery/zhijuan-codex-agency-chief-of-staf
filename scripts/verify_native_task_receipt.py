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
    parser.add_argument("--reviewer-id")
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--parent-final-marker", action="append", default=[])
    parser.add_argument("--reviewer-final-marker", action="append", default=[])
    parser.add_argument("--require-archived", action="store_true")
    parser.add_argument("--require-clean-source", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if "luna" in args.model.lower():
        raise SystemExit("Luna is not allowed for this release receipt")
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

        reviewer = None
        if args.reviewer_id:
            reviewer_row = thread_row(database, args.reviewer_id)
            reviewer = verify_thread(
                reviewer_row,
                expected_model=args.model,
                expected_effort=args.reasoning_effort,
                require_archived=args.require_archived,
                final_markers=args.reviewer_final_marker,
            )
            first_message = str(reviewer_row["first_user_message"])
            if args.parent_id not in first_message or "AGENCY_WORKER: true" not in first_message:
                raise ValueError("reviewer task is not bound to the parent worker packet")
    finally:
        database.close()

    receipt = {
        "receipt_type": "NATIVE_TASK_SMOKE_RECEIPT",
        "status": "verified",
        "source": source_state,
        "installed_bundle_manifests": installed,
        "parent": parent,
        "reviewer": reviewer,
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
