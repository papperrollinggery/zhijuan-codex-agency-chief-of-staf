#!/usr/bin/env python3
"""Verify a heterogeneous native child route from persisted Codex state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Any

sys.dont_write_bytecode = True

from inspect_codex_models import (
    canonical_state_connection,
    canonical_state_database,
    state_database_connection,
)


THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MAX_ROLLOUT_BYTES = 64 * 1024 * 1024


def fail(message: str) -> None:
    raise ValueError(message)


def read_regular_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    expanded = path.expanduser().absolute()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(expanded, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a non-symlink regular file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"{label} must be a single regular file: {path}")
        if info.st_size > MAX_ROLLOUT_BYTES:
            fail(f"{label} exceeds the 64 MiB verification limit: {path}")
        chunks: list[bytes] = []
        remaining = MAX_ROLLOUT_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_ROLLOUT_BYTES:
            fail(f"{label} exceeds the 64 MiB verification limit: {path}")
        current = expanded.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            fail(f"{label} changed while it was read: {path}")
    finally:
        os.close(descriptor)
    return data, {
        "path": str(expanded),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": len(data),
        "mtime_ns": info.st_mtime_ns,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def require_unchanged_snapshot(
    path: Path, label: str, expected: dict[str, Any]
) -> None:
    _data, observed = read_regular_bytes(path, label)
    if observed != expected:
        fail(f"{label} changed during receipt verification: {path}")


def state_database_file(path: Path, codex_home: Path | None) -> tuple[Path, bool]:
    expanded = path.expanduser()
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        fail(f"state database must resolve to a regular file: {path}")
    if codex_home is None:
        return resolved, False
    return canonical_state_database(expanded, codex_home), True


def state_window_identity(
    database_path: Path, state_identity: dict[str, Any]
) -> dict[str, object]:
    sidecars: dict[str, tuple[int, int] | None] = {}
    for suffix in ("-wal", "-shm"):
        candidate = Path(str(database_path) + suffix)
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            sidecars[suffix] = None
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail(f"state database {suffix[1:]} must be a non-symlink regular file")
        sidecars[suffix] = (info.st_dev, info.st_ino)
    return {
        "database": (state_identity.get("device"), state_identity.get("inode")),
        "sidecars": sidecars,
    }


def thread_row(database: sqlite3.Connection, thread_id: str) -> dict[str, Any]:
    if not THREAD_ID_RE.fullmatch(thread_id):
        fail(f"invalid thread id: {thread_id}")
    database.row_factory = sqlite3.Row
    row = database.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        fail(f"thread is missing from state database: {thread_id}")
    value = dict(row)
    required = {
        "id",
        "rollout_path",
        "model_provider",
        "model",
        "reasoning_effort",
        "archived",
        "agent_role",
    }
    missing = sorted(required - set(value))
    if missing:
        fail("thread state lacks required columns: " + ", ".join(missing))
    return value


def rollout_records(data: bytes, label: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8 JSONL") from exc
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rollout JSON at line {number}: {label}") from exc
        if isinstance(value, dict):
            records.append(value)
    return records


def verify_child_rollout(
    records: list[dict[str, Any]],
    *,
    parent_id: str,
    child_id: str,
    provider: str,
    model: str,
    effort: str,
) -> dict[str, object]:
    metas = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == child_id
    ]
    if len(metas) != 1:
        fail("child rollout does not contain exactly one matching session_meta")
    meta = metas[0]
    if meta.get("parent_thread_id") != parent_id:
        fail("child rollout parent_thread_id does not match the spawn edge")
    if meta.get("model_provider") != provider:
        fail("child rollout provider does not match persisted child state")
    completions = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completions) != 1 or not isinstance(
        completions[0].get("last_agent_message"), str
    ) or not completions[0]["last_agent_message"].strip():
        fail("child rollout must contain exactly one non-empty task_complete")
    completion_turn_id = completions[0].get("turn_id")
    if not isinstance(completion_turn_id, str) or not completion_turn_id:
        fail("child task_complete has no turn_id")
    contexts = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("turn_id") == completion_turn_id
    ]
    if len(contexts) != 1:
        fail("child completion turn does not have exactly one turn context")
    if contexts[0].get("model") != model or contexts[0].get("effort") != effort:
        fail(
            "child completion turn does not bind the expected model and reasoning effort"
        )
    return {
        "session_meta_bound": True,
        "turn_context_bound": True,
        "task_complete_turn_id": completion_turn_id,
        "final_sha256": hashlib.sha256(
            completions[0]["last_agent_message"].encode("utf-8")
        ).hexdigest(),
    }


def parse_json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, str):
        fail(f"{label} must be a JSON object string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        fail(f"{label} must decode to an object")
    return parsed


def verify_parent_spawn_call(
    records: list[dict[str, Any]],
    *,
    parent_id: str,
    child_id: str,
    provider: str,
    model: str,
    effort: str,
    route_kind: str,
    expected_agent_role: str | None,
) -> dict[str, object]:
    metas = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == parent_id
    ]
    if len(metas) != 1:
        fail("parent rollout does not contain exactly one matching session_meta")
    if metas[0].get("model_provider") != provider:
        fail("parent rollout provider does not match persisted parent state")

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in records:
        payload = record.get("payload")
        if (
            record.get("type") != "response_item"
            or not isinstance(payload, dict)
            or payload.get("type") != "function_call"
            or payload.get("namespace") != "agents"
            or payload.get("name") != "spawn_agent"
        ):
            continue
        arguments = parse_json_object(payload.get("arguments"), "spawn arguments")
        if arguments.get("fork_turns") != "none":
            continue
        if route_kind == "direct":
            if (
                arguments.get("model") != model
                or arguments.get("reasoning_effort") != effort
                or "agent_type" in arguments
            ):
                continue
        elif route_kind == "custom-agent":
            if arguments.get("agent_type") != expected_agent_role:
                continue
            for key, expected in (("model", model), ("reasoning_effort", effort)):
                if key in arguments and arguments[key] != expected:
                    break
            else:
                matches.append((payload, arguments))
            continue
        matches.append((payload, arguments))
    if len(matches) != 1:
        fail("parent rollout does not contain exactly one matching native spawn call")

    call, arguments = matches[0]
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        fail("native spawn call has no call_id")
    outputs = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "response_item"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "function_call_output"
        and record["payload"].get("call_id") == call_id
    ]
    if len(outputs) != 1:
        fail("native spawn call does not have exactly one matching output")
    output = parse_json_object(outputs[0].get("output"), "spawn output")
    task_name = output.get("task_name")
    if not isinstance(task_name, str) or not task_name:
        fail("native spawn output has no task_name")
    requested_task_name = arguments.get("task_name")
    if not isinstance(requested_task_name, str) or not requested_task_name:
        fail("native spawn arguments have no task_name")
    if task_name.rsplit("/", 1)[-1] != requested_task_name:
        fail("native spawn output task_name does not match the request")
    activities = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "sub_agent_activity"
        and record["payload"].get("event_id") == call_id
        and record["payload"].get("kind") == "started"
    ]
    if len(activities) != 1:
        fail("native spawn call does not have exactly one matching started activity")
    activity = activities[0]
    if activity.get("agent_thread_id") != child_id:
        fail("native spawn activity does not bind the expected child thread")
    if activity.get("agent_path") != task_name:
        fail("native spawn activity path does not match the call output")
    return {
        "session_meta_bound": True,
        "call_id": call_id,
        "task_name": task_name,
        "fork_turns": "none",
        "model": model if route_kind == "direct" else arguments.get("model"),
        "reasoning_effort": (
            effort if route_kind == "direct" else arguments.get("reasoning_effort")
        ),
        "agent_type": arguments.get("agent_type"),
        "call_output_bound": True,
        "activity_child_bound": True,
    }


def route_state_binding(
    parent: dict[str, Any],
    child: dict[str, Any],
    edges: list[tuple[Any, ...]],
) -> dict[str, object]:
    return {
        "parent": {
            key: parent.get(key)
            for key in ("id", "model_provider", "model", "reasoning_effort")
        },
        "child": {
            key: child.get(key)
            for key in (
                "id",
                "rollout_path",
                "model_provider",
                "model",
                "reasoning_effort",
                "archived",
                "agent_role",
            )
        },
        "edges": [tuple(edge) for edge in edges],
    }


def verify_receipt(
    *,
    state_db: Path,
    parent_id: str,
    child_id: str,
    expected_provider: str,
    expected_model: str,
    expected_effort: str,
    route_kind: str,
    expected_agent_role: str | None,
    expected_edge_status: str | None,
    require_archived: bool,
    require_native_spawn_call: bool = False,
    codex_home: Path | None = None,
) -> dict[str, object]:
    if expected_provider != "openai":
        fail("role route receipts only support the Codex OpenAI provider")
    if expected_model.lower().startswith("claude-"):
        fail("external Claude models are disabled in core role route receipts")
    database_path, canonical_state_store_bound = state_database_file(
        state_db, codex_home
    )
    if parent_id == child_id:
        fail("parent and child thread IDs must differ")
    for label, value in (
        ("expected provider", expected_provider),
        ("expected model", expected_model),
        ("expected effort", expected_effort),
    ):
        if not isinstance(value, str) or not value:
            fail(f"{label} must be non-empty")
    def connection_context():
        return (
            canonical_state_connection(state_db, codex_home)
            if codex_home is not None
            else state_database_connection(state_db)
        )

    with connection_context() as (database, state_identity):
        parent = thread_row(database, parent_id)
        child = thread_row(database, child_id)
        edges = database.execute(
            "SELECT status FROM thread_spawn_edges "
            "WHERE parent_thread_id = ? AND child_thread_id = ?",
            (parent_id, child_id),
        ).fetchall()
        if len(edges) != 1:
            fail("child has no unique native spawn edge from the parent")
        edge_status = edges[0][0]
        if not isinstance(edge_status, str) or not edge_status:
            fail("native spawn edge has no status")
        if expected_edge_status is not None and edge_status != expected_edge_status:
            fail(f"native spawn edge status mismatch: {edge_status!r}")

        expected = (expected_provider, expected_model, expected_effort)
        observed = (
            child.get("model_provider"),
            child.get("model"),
            child.get("reasoning_effort"),
        )
        if observed != expected:
            fail(f"child route identity mismatch: {observed!r}")
        parent_route = (
            parent.get("model_provider"),
            parent.get("model"),
            parent.get("reasoning_effort"),
        )
        if any(not isinstance(value, str) or not value for value in parent_route):
            fail("parent route identity is incomplete")
        if parent_route[0] != "openai":
            fail("role route receipt parent must use the Codex OpenAI provider")
        if parent_route == observed:
            fail("child route is inherited, not heterogeneous")
        if require_archived and child.get("archived") != 1:
            fail("child thread cleanup is incomplete")

        agent_role = child.get("agent_role")
        if route_kind == "direct":
            if expected_agent_role is not None:
                fail("direct routes do not accept --expected-agent-role")
            if agent_role not in {None, ""}:
                fail("direct route unexpectedly persisted a custom agent role")
        elif route_kind == "custom-agent":
            if not expected_agent_role:
                fail("custom-agent routes require --expected-agent-role")
            if agent_role != expected_agent_role:
                fail("child custom-agent role does not match")
        else:
            fail(f"unsupported route kind: {route_kind}")

        rollout_path = Path(str(child["rollout_path"])).expanduser()
        rollout_bytes, rollout_snapshot = read_regular_bytes(
            rollout_path, "child rollout"
        )
        records = rollout_records(rollout_bytes, str(rollout_path))
        rollout_binding = verify_child_rollout(
            records,
            parent_id=parent_id,
            child_id=child_id,
            provider=expected_provider,
            model=expected_model,
            effort=expected_effort,
        )
        parent_rollout_bytes: bytes | None = None
        parent_rollout_snapshot: dict[str, Any] | None = None
        parent_rollout_path: Path | None = None
        native_spawn_binding: dict[str, object] | None = None
        if require_native_spawn_call:
            parent_rollout_path = Path(str(parent["rollout_path"])).expanduser()
            if parent_rollout_path == rollout_path:
                fail("parent and child rollout paths must differ")
            parent_rollout_bytes, parent_rollout_snapshot = read_regular_bytes(
                parent_rollout_path, "parent rollout"
            )
            native_spawn_binding = verify_parent_spawn_call(
                rollout_records(parent_rollout_bytes, str(parent_rollout_path)),
                parent_id=parent_id,
                child_id=child_id,
                provider=str(parent_route[0]),
                model=expected_model,
                effort=expected_effort,
                route_kind=route_kind,
                expected_agent_role=expected_agent_role,
            )
        state_binding = route_state_binding(parent, child, edges)
        first_state_window = state_window_identity(database_path, state_identity)

    require_unchanged_snapshot(rollout_path, "child rollout", rollout_snapshot)
    if parent_rollout_path is not None and parent_rollout_snapshot is not None:
        require_unchanged_snapshot(
            parent_rollout_path, "parent rollout", parent_rollout_snapshot
        )
    with connection_context() as (database, state_identity_after):
        parent_after = thread_row(database, parent_id)
        child_after = thread_row(database, child_id)
        edges_after = database.execute(
            "SELECT status FROM thread_spawn_edges "
            "WHERE parent_thread_id = ? AND child_thread_id = ?",
            (parent_id, child_id),
        ).fetchall()
        if route_state_binding(parent_after, child_after, edges_after) != state_binding:
            fail("role route state changed during receipt verification")
        second_state_window = state_window_identity(
            database_path, state_identity_after
        )
        if second_state_window != first_state_window:
            fail("role route state store identity changed during receipt verification")
    require_unchanged_snapshot(rollout_path, "child rollout", rollout_snapshot)
    if parent_rollout_path is not None and parent_rollout_snapshot is not None:
        require_unchanged_snapshot(
            parent_rollout_path, "parent rollout", parent_rollout_snapshot
        )
    return {
        "receipt_type": "ROLE_ROUTE_RECEIPT",
        "status": "locally-consistent",
        "canonical_state_store_bound": canonical_state_store_bound,
        "state_identity_guarded": bool(state_identity.get("identity_guarded")),
        "state_wal_aware": bool(state_identity.get("wal_aware")),
        "current_task_binding_verified": False,
        "route_kind": route_kind,
        "heterogeneous": True,
        "parent": {
            "id": parent_id,
            "provider": parent_route[0],
            "model": parent_route[1],
            "reasoning_effort": parent_route[2],
        },
        "child": {
            "id": child_id,
            "provider": observed[0],
            "model": observed[1],
            "reasoning_effort": observed[2],
            "agent_role": agent_role or None,
            "archived": child.get("archived") == 1,
            "rollout_sha256": hashlib.sha256(rollout_bytes).hexdigest(),
        },
        "spawn_edge": {"status": edge_status},
        "rollout_binding": rollout_binding,
        "native_spawn_call_arguments_verified": native_spawn_binding is not None,
        "native_spawn_binding": native_spawn_binding,
        "parent_rollout_sha256": (
            hashlib.sha256(parent_rollout_bytes).hexdigest()
            if parent_rollout_bytes is not None
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--parent-id", required=True)
    parser.add_argument("--child-id", required=True)
    parser.add_argument("--expected-provider", required=True)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--expected-effort", required=True)
    parser.add_argument("--route-kind", choices=("direct", "custom-agent"), required=True)
    parser.add_argument("--expected-agent-role")
    parser.add_argument("--expected-edge-status")
    parser.add_argument("--require-archived", action="store_true")
    parser.add_argument(
        "--require-native-spawn-call",
        action="store_true",
        help=(
            "Bind the parent rollout's unique native agents.spawn_agent call and "
            "matching output to the expected route."
        ),
    )
    args = parser.parse_args()
    receipt = verify_receipt(
        state_db=args.state_db,
        parent_id=args.parent_id,
        child_id=args.child_id,
        expected_provider=args.expected_provider,
        expected_model=args.expected_model,
        expected_effort=args.expected_effort,
        route_kind=args.route_kind,
        expected_agent_role=args.expected_agent_role,
        expected_edge_status=args.expected_edge_status,
        require_archived=args.require_archived,
        require_native_spawn_call=args.require_native_spawn_call,
        codex_home=args.codex_home,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"Role route receipt invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
