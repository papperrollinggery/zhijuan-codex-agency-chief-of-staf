#!/usr/bin/env python3
"""Verify a Codex Desktop task receipt from persisted state and installed bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from install_skill import INSTALL_NAMES, installed_manifest, runtime_manifest
from inspect_codex_models import canonical_state_connection
from protocol_contract import (
    REVIEW_FIELDS,
    WORKER_HEADER,
    parse_reviewer_terminal,
    parse_worker_packet,
)
from run_profile_compat import (
    command_reads_artifact,
    hardened_git_observation,
    output_proves_exit_zero,
    verify_read_only_sandbox,
)


THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
REVIEWER_FINAL_FIELDS = tuple(f"{field}:" for field in REVIEW_FIELDS[:-1]) + (
    "REVIEW_VERDICT: PASS",
)


def read_regular_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    candidate = path.expanduser().absolute()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a non-symlink regular file: {candidate}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"{label} must be a single regular file: {candidate}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
        current = candidate.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise ValueError(f"{label} changed while it was read: {candidate}")
    finally:
        os.close(descriptor)
    return data, {
        "path": str(candidate),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def require_unchanged_snapshot(path: Path, label: str, expected: dict[str, Any]) -> None:
    _data, observed = read_regular_bytes(path, label)
    if observed != expected:
        raise ValueError(f"{label} changed during receipt verification: {path}")


def write_new_private_file(path: Path, payload: bytes) -> Path:
    """Create one receipt without following or truncating an existing entry."""
    candidate = path.expanduser().absolute()
    if candidate.name in {"", ".", ".."}:
        raise ValueError("receipt output must name a file")
    parent = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        directory = os.open(parent, directory_flags)
    except OSError as exc:
        raise ValueError(
            f"receipt output parent must be a non-symlink directory: {parent}"
        ) from exc
    descriptor: int | None = None
    created = False
    try:
        directory_info = os.fstat(directory)
        if not stat.S_ISDIR(directory_info.st_mode):
            raise ValueError(f"receipt output parent is not a directory: {parent}")
        parent_info = os.stat(parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or (parent_info.st_dev, parent_info.st_ino)
            != (directory_info.st_dev, directory_info.st_ino)
        ):
            raise ValueError(
                f"receipt output parent path changed before write: {parent}"
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(
                candidate.name,
                flags,
                0o600,
                dir_fd=directory,
            )
        except FileExistsError as exc:
            raise ValueError(
                f"receipt output already exists; refusing overwrite: {candidate}"
            ) from exc
        created = True
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(
                f"receipt output must be a new single regular file: {candidate}"
            )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("receipt output write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        current = os.stat(candidate.name, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise ValueError(f"receipt output changed while it was written: {candidate}")
        parent_after = os.stat(parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_after.st_mode)
            or (parent_after.st_dev, parent_after.st_ino)
            != (directory_info.st_dev, directory_info.st_ino)
        ):
            raise ValueError(
                f"receipt output parent path changed while writing: {parent}"
            )
        os.fsync(directory)
        return candidate
    except BaseException:
        if created:
            try:
                os.unlink(candidate.name, dir_fd=directory)
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def string_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(string_content(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(string_content(item) for item in value.values())
    return ""


def thread_row(database: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    database.row_factory = sqlite3.Row
    row = database.execute(
        """
        SELECT id, rollout_path, source, model_provider, model, reasoning_effort,
               cwd, archived, first_user_message, sandbox_policy, agent_role,
               created_at_ms, updated_at_ms
        FROM threads WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"thread is missing from state database: {thread_id}")
    return dict(row)


def verify_native_reviewer_identity(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("agent_role") != "reviewer":
        raise ValueError("native reviewer thread agent_role is not reviewer")
    sandbox = verify_read_only_sandbox(str(row.get("sandbox_policy", "")))
    message = str(row.get("first_user_message", ""))
    start = message.find(WORKER_HEADER)
    if start < 0:
        raise ValueError("native reviewer first message has no complete worker packet")
    try:
        packet = parse_worker_packet(message[start:])
    except ValueError as exc:
        raise ValueError(f"native reviewer worker packet is invalid: {exc}") from exc
    return {
        "agent_role": "reviewer",
        "sandbox_type": str(sandbox["type"]),
        "worker_packet_fields": len(packet),
    }


def rollout_records(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, snapshot = read_regular_bytes(path, "rollout")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"rollout is not UTF-8: {path}") from exc
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rollout JSON at line {number}: {path}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records, snapshot


def reviewer_binding(
    database: sqlite3.Connection,
    *,
    parent_id: str,
    reviewer_id: str,
    records: list[dict[str, Any]],
    parent_final: str,
) -> dict[str, str]:
    edges = database.execute(
        "SELECT status FROM thread_spawn_edges WHERE parent_thread_id = ? AND child_thread_id = ?",
        (parent_id, reviewer_id),
    ).fetchall()
    if len(edges) != 1:
        raise ValueError("reviewer has no native spawn edge uniquely bound from parent")
    edge_status = edges[0][0]
    if not isinstance(edge_status, str) or not edge_status:
        raise ValueError("reviewer native spawn edge has no status")
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
        "spawn_edge_status": edge_status,
    }


def verify_reviewer_read(
    records: list[dict[str, Any]],
    markers: list[str],
    artifact: str,
    reviewer_cwd: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_path = Path(artifact).expanduser().absolute()
    artifact_bytes, artifact_snapshot = read_regular_bytes(
        artifact_path, "reviewer artifact"
    )
    try:
        artifact_text = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("reviewer artifact must be UTF-8") from exc
    artifact_text_json = json.dumps(artifact_text, ensure_ascii=False)[1:-1]
    if any(marker not in artifact_text for marker in markers):
        raise ValueError("reviewer read marker is not present in the artifact bytes")
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
    outputs: dict[str, tuple[str, object]] = {}
    for index, record in enumerate(records):
        if record.get("type") != "response_item" or index >= completion_indexes[0]:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "custom_tool_call_output":
            continue
        call_id = payload.get("call_id")
        if not isinstance(call_id, str) or call_id not in calls:
            continue
        raw_output = payload.get("output")
        outputs[call_id] = (string_content(raw_output), raw_output)
    if not outputs:
        raise ValueError("reviewer has no completed exec call with bound output")
    bound_calls = []
    for call_id, (output, raw_output) in outputs.items():
        call_input = calls[call_id]
        if (
            command_reads_artifact(call_input, artifact_path, reviewer_cwd)
            and output_proves_exit_zero(raw_output)
            and (artifact_text in output or artifact_text_json in output)
            and all(marker in output for marker in markers)
        ):
            bound_calls.append(call_id)
    if not bound_calls:
        raise ValueError("no single reviewer exec/output pair proves the artifact read")
    return (
        {
            "paired_exec_outputs": len(outputs),
            "bound_read_calls": len(bound_calls),
            "artifact": str(artifact_path),
            "artifact_sha256": artifact_snapshot["sha256"],
            "markers": markers,
        },
        artifact_snapshot,
    )


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


def verify_reviewer_schema(
    final_message: str,
    *,
    artifact: Path,
    reviewer_cwd: Path,
    markers: list[str],
) -> None:
    try:
        values = parse_reviewer_terminal(final_message)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if values["REVIEW_VERDICT"] != "PASS":
        raise ValueError("reviewer verdict is not exactly PASS")
    try:
        expected_target = artifact.resolve().relative_to(reviewer_cwd.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("reviewer artifact must stay inside reviewer cwd") from exc
    if values["REVIEW_TARGET"] != expected_target:
        raise ValueError("reviewer final target does not match reviewer artifact")
    if any(marker not in values["REVIEW_READBACK"] for marker in markers):
        raise ValueError("reviewer final readback does not contain every artifact marker")


def verify_thread(
    row: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    rollout_snapshot: dict[str, Any],
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

    session_meta = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == thread_id
    ]
    if len(session_meta) != 1 or session_meta[0].get("model_provider") != "openai":
        raise ValueError(f"rollout session identity is not uniquely bound: {thread_id}")

    completions = [
        record["payload"]
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completions) != 1:
        raise ValueError(f"thread needs exactly one task_complete event: {thread_id}")
    completion_turn_id = completions[0].get("turn_id")
    if not isinstance(completion_turn_id, str) or not completion_turn_id:
        raise ValueError(f"thread task_complete has no turn id: {thread_id}")
    contexts = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("turn_id") == completion_turn_id
    ]
    if len(contexts) != 1:
        raise ValueError(
            f"completion turn does not have exactly one model context: {thread_id}"
        )
    if (
        contexts[0].get("model") != expected_model
        or contexts[0].get("effort") != expected_effort
    ):
        raise ValueError(
            f"completion turn model identity mismatch: {thread_id}: "
            f"{contexts[0].get('model')}/{contexts[0].get('effort')}"
        )
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
        "rollout_sha256": rollout_snapshot["sha256"],
        "task_complete_turn_id": completion_turn_id,
        "final_sha256": hashlib.sha256(final_message.encode("utf-8")).hexdigest(),
    }


def git_state(source: Path) -> dict[str, Any]:
    observation = hardened_git_observation(source)
    status = bytes(observation["status_bytes"])
    return {
        "head": observation["head"],
        "clean": not bool(status),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "filter_paths_checked": observation["filter_paths_checked"],
        "fsmonitor_disabled": observation["fsmonitor_disabled"],
        "lazy_fetch_disabled": observation["lazy_fetch_disabled"],
        "submodules_ignored": observation["submodules_ignored"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
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

    if args.model.lower().startswith("claude-"):
        raise SystemExit("external Claude models are disabled in the core Codex receipt")
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
    source_arg = args.source_root.expanduser().absolute()
    installed_arg = args.installed_root.expanduser().absolute()
    if source_arg.is_symlink() or installed_arg.is_symlink():
        raise SystemExit("source and installed roots must not be symlinks")
    source = source_arg.resolve(strict=True)
    installed_root = installed_arg.resolve(strict=True)
    codex_home = args.codex_home.expanduser().absolute()
    state_db = args.state_db.expanduser()

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

    with canonical_state_connection(
        state_db, codex_home
    ) as (database, state_identity):
        parent_row = thread_row(database, args.parent_id)
        parent_rollout = Path(str(parent_row["rollout_path"]))
        parent_records, parent_rollout_snapshot = rollout_records(parent_rollout)
        parent = verify_thread(
            parent_row,
            records=parent_records,
            rollout_snapshot=parent_rollout_snapshot,
            expected_model=args.model,
            expected_effort=args.reasoning_effort,
            require_archived=args.require_archived,
            final_markers=args.parent_final_marker,
        )
        if "$agency-chief-of-staff" not in str(parent_row["first_user_message"]):
            raise ValueError("parent task did not explicitly invoke canonical skill")
        parent_final = completed_message(parent_records)

        reviewer_row = thread_row(database, args.reviewer_id)
        reviewer_identity = verify_native_reviewer_identity(reviewer_row)
        reviewer_rollout = Path(str(reviewer_row["rollout_path"]))
        reviewer_records, reviewer_rollout_snapshot = rollout_records(
            reviewer_rollout
        )
        reviewer = verify_thread(
            reviewer_row,
            records=reviewer_records,
            rollout_snapshot=reviewer_rollout_snapshot,
            expected_model=args.model,
            expected_effort=args.reasoning_effort,
            require_archived=args.require_archived,
            final_markers=args.reviewer_final_marker + list(REVIEWER_FINAL_FIELDS),
        )
        reviewer_artifact = Path(args.reviewer_artifact).expanduser().absolute()
        verify_reviewer_schema(
            completed_message(reviewer_records),
            artifact=reviewer_artifact,
            reviewer_cwd=Path(str(reviewer_row["cwd"])),
            markers=args.reviewer_read_marker,
        )
        binding = reviewer_binding(
            database,
            parent_id=args.parent_id,
            reviewer_id=args.reviewer_id,
            records=reviewer_records,
            parent_final=parent_final,
        )
        reviewer_read, reviewer_artifact_snapshot = verify_reviewer_read(
            reviewer_records,
            args.reviewer_read_marker,
            args.reviewer_artifact,
            Path(str(reviewer_row["cwd"])),
        )

    require_unchanged_snapshot(
        parent_rollout, "parent rollout", parent_rollout_snapshot
    )
    require_unchanged_snapshot(
        reviewer_rollout, "reviewer rollout", reviewer_rollout_snapshot
    )
    require_unchanged_snapshot(
        reviewer_artifact, "reviewer artifact", reviewer_artifact_snapshot
    )
    source_state_after = git_state(source)
    if source_state_after != source_state:
        raise ValueError("source Git state changed during receipt verification")
    for skill_name, before_manifest in installed.items():
        observed_after = installed_manifest(installed_root / skill_name)
        expected_after = runtime_manifest(source, skill_name)
        if observed_after != before_manifest or expected_after != before_manifest:
            raise ValueError(
                f"source or installed bundle changed during verification: {skill_name}"
            )

    receipt = {
        "receipt_type": "NATIVE_TASK_SMOKE_RECEIPT",
        "status": "verified",
        "canonical_state_store_bound": True,
        "state_identity_guarded": bool(state_identity.get("identity_guarded")),
        "state_wal_aware": bool(state_identity.get("wal_aware")),
        "state_readonly_transaction": bool(
            state_identity.get("readonly_transaction")
        ),
        "current_source_observation": source_state,
        "installed_bundle_manifests": installed,
        "parent": parent,
        "reviewer": reviewer,
        "reviewer_binding": binding,
        "reviewer_identity": reviewer_identity,
        "reviewer_tool_read": reviewer_read,
        "cold_context_isolation": "unverified",
        "historical_writes_verified": False,
        "agents_md_state": "unverified",
    }
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        write_new_private_file(args.out, payload.encode("utf-8"))
    print(payload, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"native task receipt invalid: {exc}") from exc
