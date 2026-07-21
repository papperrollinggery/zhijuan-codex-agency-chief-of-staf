#!/usr/bin/env python3
"""Bind a prepared Execution Session to one mechanically observed Codex task."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agency_task import (
    active_task_dir,
    atomic_write_json,
    atomic_write_text,
    load_json,
    read_regular_text,
    safe_project_root,
    task_index_lock,
    transition_task,
    utc_now,
    validate_task_plan,
)
from inspect_codex_models import (
    CodexAppServer,
    canonical_state_connection,
    collect_model_items,
    resolve_executable,
)
from prepare_execution_launch import _writes_required, execution_packet
from protocol_contract import (
    InvalidAgencyPacket,
    classify_transport_source_prompt,
    match_execution_session_transport,
)
from resolve_execution_model import _effort_fields
from update_task_progress import update_progress


THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MECHANICAL_ATTESTATION = "app-server-canonical-state-mechanically-bound"
READY_SESSION_STATUSES = frozenset({"native_launch_ready", "manual_launch_ready"})
TRANSPORT_READBACK_FIELDS = (
    "prompt_transport",
    "source_thread_id",
    "source_thread_readback",
    "source_user_root_readback",
)


def _snapshot(path: Path) -> tuple[bool, str]:
    if path.is_symlink():
        raise ValueError(f"managed execution-session output must not be a symlink: {path}")
    return (True, read_regular_text(path)) if path.exists() else (False, "")


def _restore(path: Path, snapshot: tuple[bool, str]) -> None:
    existed, text = snapshot
    if existed:
        atomic_write_text(path, text)
    elif path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"cannot remove unsafe execution-session output: {path}")
        path.unlink()


def _rollback(snapshots: dict[Path, tuple[bool, str]], exc: Exception) -> None:
    failures: list[str] = []
    for path, snapshot in reversed(list(snapshots.items())):
        try:
            _restore(path, snapshot)
        except (OSError, ValueError) as rollback_exc:
            failures.append(f"{path}: {rollback_exc}")
    if failures:
        raise RuntimeError(
            "execution-session binding failed and rollback was incomplete: "
            + "; ".join(failures)
        ) from exc


def _iso_milliseconds(value: object) -> int:
    if not isinstance(value, str) or not value:
        raise ValueError("prepared execution session has no created_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("prepared execution session created_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("prepared execution session created_at needs a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _git_identity(path: Path) -> tuple[Path, Path]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ValueError(f"cannot inspect execution worktree: {path}: {exc}") from exc
    lines = [line for line in result.stdout.splitlines() if line]
    if result.returncode != 0 or len(lines) != 2:
        detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise ValueError(f"cannot prove execution worktree identity: {detail}")
    top = Path(lines[0]).resolve(strict=True)
    common = Path(lines[1]).resolve(strict=True)
    return top, common


def _prove_execution_cwd(project: Path, plan: dict[str, Any], raw_cwd: object) -> dict[str, Any]:
    if not isinstance(raw_cwd, str) or not Path(raw_cwd).is_absolute():
        raise ValueError("native task cwd is not absolute")
    cwd = Path(raw_cwd).resolve(strict=True)
    if not cwd.is_dir() or cwd.is_symlink():
        raise ValueError("native task cwd must be a real directory")
    if not _writes_required(plan):
        if cwd != project:
            raise ValueError("read-only native task cwd does not match the project")
        return {
            "cwd": str(cwd),
            "isolated_worktree": False,
            "worktree_path": None,
        }

    project_top, project_common = _git_identity(project)
    worktree_top, worktree_common = _git_identity(cwd)
    if project_top != project or worktree_top != cwd:
        raise ValueError("execution cwd is not the root of its Git worktree")
    if worktree_top == project_top or worktree_common != project_common:
        raise ValueError("write task is not in an isolated worktree of the project")
    return {
        "cwd": str(cwd),
        "isolated_worktree": True,
        "worktree_path": str(cwd),
    }


def _rollout_identity(path: object, thread_id: str, model: str, effort: str) -> dict[str, Any]:
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError("native task rollout path is unavailable")
    text = read_regular_text(Path(path))
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid native rollout JSON on line {number}") from exc
        if isinstance(value, dict):
            records.append(value)
    metas = [
        record["payload"]
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == thread_id
    ]
    if len(metas) != 1 or metas[0].get("model_provider") != "openai":
        raise ValueError("native rollout is not uniquely bound to the OpenAI task")
    contexts = [
        record["payload"]
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
    ]
    if not contexts or any(
        context.get("model") != model or context.get("effort") != effort
        for context in contexts
    ):
        raise ValueError("native rollout does not prove the requested model and effort")
    return {
        "rollout_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "model_turns_observed": len(contexts),
    }


def _mechanical_readback(
    project: Path,
    plan: dict[str, Any],
    session: dict[str, Any],
    native_task_id: str,
    *,
    codex_bin: str,
    codex_home: Path | None,
    state_db: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not THREAD_ID_RE.fullmatch(native_task_id):
        raise ValueError("native task id is not a Codex UUID")
    executable = resolve_executable(codex_bin)
    with CodexAppServer(
        executable,
        cwd=project,
        codex_home=codex_home.expanduser() if codex_home else None,
        timeout_seconds=timeout_seconds,
    ) as app:
        host = app.request(
            "thread/read", {"threadId": native_task_id, "includeTurns": False}
        ).get("thread")
        if not isinstance(host, dict) or host.get("id") != native_task_id:
            raise ValueError("App Server did not read back the requested native task")
        if "parentThreadId" not in host or host.get("parentThreadId") is not None:
            raise ValueError("native execution root is a subagent, not a user-owned task")
        expected_packet = execution_packet(project, plan["task_id"])
        host_prompt = match_execution_session_transport(host.get("preview"), expected_packet)
        if host_prompt is None:
            raise ValueError("App Server task preview does not match the execution packet")
        source_thread_id = host_prompt.get("source_thread_id")
        if source_thread_id == native_task_id:
            raise ValueError("native execution transport source is self-referential")
        if source_thread_id is not None:
            source_host = app.request(
                "thread/read", {"threadId": source_thread_id, "includeTurns": False}
            ).get("thread")
            if not isinstance(source_host, dict) or source_host.get("id") != source_thread_id:
                raise ValueError("App Server did not read back the transport source task")
            if (
                "parentThreadId" not in source_host
                or source_host.get("parentThreadId") is not None
            ):
                raise ValueError("transport source task is not a user-owned root")
        items = collect_model_items(app)
        database_path = state_db or (app.codex_home / "state_5.sqlite")
        with canonical_state_connection(database_path, app.codex_home) as (
            database,
            state_identity,
        ):
            database.row_factory = sqlite3.Row
            row = database.execute(
                """
                SELECT id, rollout_path, source, model_provider, model,
                       reasoning_effort, cwd, archived, first_user_message,
                       agent_role, created_at_ms
                FROM threads WHERE id = ?
                """,
                (native_task_id,),
            ).fetchone()
            if row is None:
                raise ValueError("native task is absent from canonical Codex state")
            observed = dict(row)
            if source_thread_id is not None:
                source_row = database.execute(
                    "SELECT id, thread_source, agent_role, first_user_message "
                    "FROM threads WHERE id = ?",
                    (source_thread_id,),
                ).fetchone()
                if source_row is None:
                    raise ValueError("transport source task is absent from canonical Codex state")
                if source_row[1] != "user" or source_row[2] not in {None, ""}:
                    raise ValueError("transport source task is not a canonical user root")
                if not isinstance(source_row[3], str) or not source_row[3]:
                    raise ValueError("transport source task has no canonical first prompt")
                try:
                    source_packet_kind, _ = classify_transport_source_prompt(
                        source_row[3]
                    )
                except InvalidAgencyPacket as exc:
                    raise ValueError(
                        "transport source task contains an invalid reserved packet"
                    ) from exc
                if source_packet_kind != "ordinary":
                    raise ValueError("transport source task is a reserved protocol session")

    expected_model = session.get("resolved_model_id")
    expected_effort = session.get("reasoning_request")
    if observed.get("model_provider") != "openai":
        raise ValueError("native task provider is not OpenAI")
    if observed.get("model") != expected_model or observed.get("reasoning_effort") != expected_effort:
        raise ValueError("native task model or reasoning readback does not match the request")
    if observed.get("archived") != 0:
        raise ValueError("native task is already archived")
    if observed.get("agent_role") not in {None, ""}:
        raise ValueError("native execution root has a subagent role")
    state_prompt = match_execution_session_transport(
        observed.get("first_user_message"), expected_packet
    )
    if state_prompt is None:
        raise ValueError("canonical task prompt does not match the execution packet")
    if state_prompt != host_prompt:
        raise ValueError("App Server and canonical state disagree on prompt transport")
    created_at_ms = observed.get("created_at_ms")
    if not isinstance(created_at_ms, int) or created_at_ms < _iso_milliseconds(
        session.get("created_at")
    ) - 5_000:
        raise ValueError("native task predates the prepared execution session")
    catalog_matches = [item for item in items if item.get("model") == expected_model]
    if len(catalog_matches) != 1:
        raise ValueError("native task model is not uniquely visible in the live catalog")
    catalog_model = catalog_matches[0]
    if catalog_model.get("hidden") is True or catalog_model.get(
        "available", catalog_model.get("isAvailable", True)
    ) is not True:
        raise ValueError("native task model is unavailable in the live catalog")
    advertised_provider = catalog_model.get(
        "modelProvider", catalog_model.get("provider")
    )
    if advertised_provider is not None and advertised_provider != "openai":
        raise ValueError("live model provider does not match canonical task state")
    if expected_effort not in _effort_fields(catalog_model):
        raise ValueError("native task effort is not supported by the live model")
    cwd_proof = _prove_execution_cwd(project, plan, observed.get("cwd"))
    rollout = _rollout_identity(
        observed.get("rollout_path"), native_task_id, str(expected_model), str(expected_effort)
    )
    state_source = observed.get("source")
    if not isinstance(state_source, str) or not state_source.strip():
        state_source = "unknown"
    return {
        "native_task_id": native_task_id,
        "provider": "openai",
        "actual_model_id": expected_model,
        "actual_reasoning_effort": expected_effort,
        **cwd_proof,
        "status": "active-unarchived",
        "host_thread_readback": True,
        "prompt_bound": True,
        **host_prompt,
        "source_thread_readback": source_thread_id is not None,
        "source_user_root_readback": source_thread_id is not None,
        "catalog_bound": True,
        "state_store_identity": state_identity,
        "state_source": state_source,
        "prompt_sha256": hashlib.sha256(expected_packet.encode("utf-8")).hexdigest(),
        **rollout,
        "observed_at": utc_now(),
    }


def validate_bound_execution_session(
    session: dict[str, Any], plan: dict[str, Any], project: Path
) -> dict[str, Any]:
    root = safe_project_root(project)
    task_id = plan["task_id"]
    base = f".agency/tasks/active/{task_id}"
    expected_fields = {
        "task_id": task_id,
        "orchestration_depth": 0,
        "project_root": str(root),
        "task_plan": f"{base}/task-plan.json",
        "team_plan": f"{base}/TEAM_PLAN.json",
        "progress_file": f"{base}/PROGRESS.md",
        "display_model_request": "GPT-5.6 Sol",
        "reasoning_request": "ultra",
        "model_resolution_status": "resolved",
        "session_status": "executing",
        "native_readback_attestation": MECHANICAL_ATTESTATION,
    }
    mismatches = {
        field: {"expected": expected, "actual": session.get(field)}
        for field, expected in expected_fields.items()
        if session.get(field) != expected
    }
    if plan.get("status") != "executing":
        mismatches["task_plan.status"] = {
            "expected": "executing",
            "actual": plan.get("status"),
        }
    model_request = plan.get("execution_model_request", {})
    if session.get("resolved_model_id") != model_request.get("resolved_model_id"):
        mismatches["resolved_model_id"] = {
            "expected": model_request.get("resolved_model_id"),
            "actual": session.get("resolved_model_id"),
        }
    readback = session.get("native_readback")
    if not isinstance(readback, dict):
        raise ValueError("executing session has no mechanical native readback")
    nested_expected = {
        "native_task_id": session.get("native_task_id"),
        "provider": "openai",
        "actual_model_id": session.get("resolved_model_id"),
        "actual_reasoning_effort": session.get("reasoning_request"),
        "status": "active-unarchived",
        "host_thread_readback": True,
        "prompt_bound": True,
        "catalog_bound": True,
        "prompt_sha256": hashlib.sha256(
            execution_packet(root, task_id).encode("utf-8")
        ).hexdigest(),
    }
    for field, expected in nested_expected.items():
        if readback.get(field) != expected:
            mismatches[f"native_readback.{field}"] = {
                "expected": expected,
                "actual": readback.get(field),
            }
    if not isinstance(session.get("native_task_id"), str) or not THREAD_ID_RE.fullmatch(
        str(session.get("native_task_id"))
    ):
        mismatches["native_task_id"] = {"expected": "Codex UUID", "actual": session.get("native_task_id")}
    present_transport_fields = {
        field for field in TRANSPORT_READBACK_FIELDS if field in readback
    }
    legacy_raw_readback = not present_transport_fields
    if present_transport_fields and present_transport_fields != set(
        TRANSPORT_READBACK_FIELDS
    ):
        mismatches["native_readback.transport_fields"] = {
            "expected": "all transport fields or legacy raw omission",
            "actual": sorted(present_transport_fields),
        }
    prompt_transport = readback.get(
        "prompt_transport", "raw" if legacy_raw_readback else None
    )
    source_thread_id = readback.get("source_thread_id")
    source_thread_readback = readback.get(
        "source_thread_readback", False if legacy_raw_readback else None
    )
    source_user_root_readback = readback.get(
        "source_user_root_readback", False if legacy_raw_readback else None
    )
    if prompt_transport == "raw":
        if (
            source_thread_id is not None
            or source_thread_readback is not False
            or source_user_root_readback is not False
        ):
            mismatches["native_readback.source_thread_id"] = {
                "expected": {
                    "source_thread_id": None,
                    "source_thread_readback": False,
                    "source_user_root_readback": False,
                },
                "actual": {
                    "source_thread_id": source_thread_id,
                    "source_thread_readback": source_thread_readback,
                    "source_user_root_readback": source_user_root_readback,
                },
            }
    elif prompt_transport == "codex_delegation":
        if (
            not isinstance(source_thread_id, str)
            or not THREAD_ID_RE.fullmatch(source_thread_id)
            or source_thread_id == session.get("native_task_id")
            or source_thread_readback is not True
            or source_user_root_readback is not True
        ):
            mismatches["native_readback.source_thread_id"] = {
                "expected": "distinct, mechanically read Codex source UUID",
                "actual": {
                    "source_thread_id": source_thread_id,
                    "source_thread_readback": source_thread_readback,
                    "source_user_root_readback": source_user_root_readback,
                },
            }
    else:
        mismatches["native_readback.prompt_transport"] = {
            "expected": "raw or codex_delegation",
            "actual": prompt_transport,
        }
    if _writes_required(plan):
        if readback.get("isolated_worktree") is not True or readback.get(
            "worktree_path"
        ) != readback.get("cwd"):
            mismatches["native_readback.worktree"] = {
                "expected": "isolated cwd/worktree",
                "actual": readback.get("worktree_path"),
            }
    elif (
        readback.get("cwd") != str(root)
        or readback.get("isolated_worktree") is not False
        or readback.get("worktree_path") is not None
    ):
        mismatches["native_readback.cwd"] = {
            "expected": str(root),
            "actual": readback.get("cwd"),
        }
    state_identity = readback.get("state_store_identity")
    if (
        not isinstance(state_identity, dict)
        or set(state_identity)
        != {
            "device",
            "inode",
            "identity_guarded",
            "wal_aware",
            "readonly_transaction",
        }
        or type(state_identity.get("device")) is not int
        or state_identity.get("device", -1) < 0
        or type(state_identity.get("inode")) is not int
        or state_identity.get("inode", -1) < 0
        or not all(
            state_identity.get(field) is True
            for field in ("identity_guarded", "wal_aware", "readonly_transaction")
        )
    ):
        mismatches["native_readback.state_store_identity"] = {
            "expected": "guarded canonical read-only transaction",
            "actual": state_identity,
        }
    if not isinstance(readback.get("model_turns_observed"), int) or readback.get(
        "model_turns_observed", 0
    ) < 1:
        mismatches["native_readback.model_turns_observed"] = {
            "expected": ">= 1",
            "actual": readback.get("model_turns_observed"),
        }
    for field in ("prompt_sha256", "rollout_sha256"):
        value = readback.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            mismatches[f"native_readback.{field}"] = {
                "expected": "64 lowercase hex characters",
                "actual": value,
            }
    if not isinstance(readback.get("state_source"), str) or not readback.get(
        "state_source", ""
    ).strip():
        mismatches["native_readback.state_source"] = {
            "expected": "non-empty string",
            "actual": readback.get("state_source"),
        }
    try:
        created_ms = _iso_milliseconds(session.get("created_at"))
        bound_ms = _iso_milliseconds(session.get("bound_at"))
        observed_ms = _iso_milliseconds(readback.get("observed_at"))
        if (
            bound_ms < created_ms
            or observed_ms < created_ms - 5_000
            or bound_ms < observed_ms - 5_000
        ):
            raise ValueError("binding timestamps are out of order")
    except ValueError as exc:
        mismatches["binding_timestamps"] = {
            "expected": "valid ordered UTC timestamps",
            "actual": str(exc),
        }
    if mismatches:
        raise ValueError(
            "bound execution session is inconsistent: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    return session


def bind_execution_session(
    project: Path,
    *,
    task_id: str,
    native_task_id: str,
    codex_bin: str = "codex",
    codex_home: Path | None = None,
    state_db: Path | None = None,
    timeout_seconds: int = 20,
    apply: bool,
    _index_lock_held: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    if apply and not _index_lock_held:
        with task_index_lock(root):
            return bind_execution_session(
                root,
                task_id=task_id,
                native_task_id=native_task_id,
                codex_bin=codex_bin,
                codex_home=codex_home,
                state_db=state_db,
                timeout_seconds=timeout_seconds,
                apply=True,
                _index_lock_held=True,
            )
    task_dir = active_task_dir(root, task_id)
    plan_path = task_dir / "task-plan.json"
    plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    session_path = task_dir / "execution-session.json"
    session = load_json(session_path)
    if plan["status"] not in {"execution_ready", "executing"}:
        raise ValueError("execution-session binding requires execution_ready or executing state")
    if session.get("session_status") not in READY_SESSION_STATUSES | {"executing"}:
        raise ValueError("execution session is not ready for a native binding")
    if session.get("model_resolution_status") != "resolved" or not session.get(
        "resolved_model_id"
    ):
        raise ValueError("execution model is not resolved")
    observed = _mechanical_readback(
        root,
        plan,
        session,
        native_task_id,
        codex_bin=codex_bin,
        codex_home=codex_home,
        state_db=state_db,
        timeout_seconds=timeout_seconds,
    )
    bound = copy.deepcopy(session)
    bound.update(
        {
            "session_status": "executing",
            "native_task_id": native_task_id,
            "native_readback": observed,
            "native_readback_attestation": MECHANICAL_ATTESTATION,
            "bound_at": utc_now(),
        }
    )
    executing_plan = copy.deepcopy(plan)
    executing_plan["status"] = "executing"
    validate_bound_execution_session(bound, executing_plan, root)
    if session.get("session_status") == "executing":
        validate_bound_execution_session(session, plan, root)
        stored_readback = session["native_readback"]
        legacy_raw_readback = not any(
            field in stored_readback for field in TRANSPORT_READBACK_FIELDS
        )
        stable_fields = (
            "native_task_id",
            "provider",
            "actual_model_id",
            "actual_reasoning_effort",
            "cwd",
            "isolated_worktree",
            "worktree_path",
            "status",
            "prompt_sha256",
        )
        if any(
            stored_readback.get(field) != observed.get(field)
            for field in stable_fields
        ):
            raise ValueError("existing executing session does not match current host readback")
        if legacy_raw_readback:
            expected_raw_transport = {
                "prompt_transport": "raw",
                "source_thread_id": None,
                "source_thread_readback": False,
                "source_user_root_readback": False,
            }
            if any(
                observed.get(field) != expected
                for field, expected in expected_raw_transport.items()
            ):
                raise ValueError("legacy executing session is not a raw prompt binding")
            result = {
                "status": "would-backfill-legacy-transport-readback",
                "task_id": task_id,
                "native_task_id": native_task_id,
                "lifecycle_status": plan["status"],
                "native_readback": observed,
                "new_conversation_created": True,
            }
            if not apply:
                return result
            session_snapshot = _snapshot(session_path)
            try:
                atomic_write_json(session_path, bound)
            except Exception as exc:
                _rollback({session_path: session_snapshot}, exc)
                raise
            return {**result, "status": "backfilled-legacy-transport-readback"}
        if any(
            stored_readback.get(field) != observed.get(field)
            for field in TRANSPORT_READBACK_FIELDS
        ):
            raise ValueError("existing executing session transport readback has drifted")
        return {
            "status": "already-bound-currently-reverified",
            "task_id": task_id,
            "native_task_id": native_task_id,
            "lifecycle_status": plan["status"],
            "native_readback": observed,
            "new_conversation_created": True,
        }
    result = {
        "status": "would-bind",
        "task_id": task_id,
        "native_task_id": native_task_id,
        "lifecycle_status": plan["status"],
        "native_readback": observed,
        "new_conversation_created": True,
    }
    if not apply:
        return result

    managed_paths = (
        session_path,
        plan_path,
        task_dir / "TASK_EXECUTION_CHECKLIST.md",
        root / ".agency/task-index.json",
        task_dir / "progress.jsonl",
        task_dir / "PROGRESS.md",
    )
    snapshots = {path: _snapshot(path) for path in managed_paths}
    try:
        atomic_write_json(session_path, bound)
        transition_task(root, task_id, "executing")
        progress = update_progress(
            root,
            task_id=task_id,
            event_type="team_plan_changed",
            work_id=None,
            actor="execution-root",
            summary="Native Execution Root task created and mechanically read back",
            artifacts=[f".agency/tasks/active/{task_id}/execution-session.json"],
            verification=[
                f"Codex task {native_task_id} provider/model/effort/CWD read back"
            ],
            idempotency_key=f"execution-session-bound:{native_task_id}",
        )
    except Exception as exc:
        _rollback(snapshots, exc)
        raise
    return {
        **result,
        "status": "bound",
        "lifecycle_status": "executing",
        "progress_event": progress["event_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mechanically bind one prepared Agency execution session to a Codex task."
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--native-task-id", required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 120:
        raise ValueError("--timeout-seconds must be between 1 and 120")
    result = bind_execution_session(
        args.project,
        task_id=args.task_id,
        native_task_id=args.native_task_id,
        codex_bin=args.codex_bin,
        codex_home=args.codex_home,
        state_db=args.state_db,
        timeout_seconds=args.timeout_seconds,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Execution session binding failed: {exc}")
