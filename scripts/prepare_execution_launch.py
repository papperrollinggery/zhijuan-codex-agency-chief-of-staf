#!/usr/bin/env python3
"""Prepare a new Execution Root session without claiming a host launch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agency_task import (
    SCHEMA_VERSION,
    active_task_dir,
    atomic_write_json,
    atomic_write_text,
    list_active_tasks,
    load_json,
    read_regular_text,
    safe_project_root,
    task_index_lock,
    transition_task,
    utc_now,
    validate_task_plan,
)
from protocol_contract import (
    EXECUTION_SESSION_DUTY,
    EXECUTION_SESSION_HEADER,
    EXECUTION_SESSION_STOP,
    parse_execution_session_packet,
)
from resolve_execution_model import live_catalog, resolve_execution_model
from resolve_team_plan import resolve_team_plan, write_team_plan
from update_task_progress import update_progress


def choose_task(project: Path, task_id: str | None) -> str:
    if task_id is not None:
        return task_id
    candidates = [
        item
        for item in list_active_tasks(project)
        if item.get("status") in {"plan_ready", "execution_ready"}
    ]
    if len(candidates) != 1:
        raise ValueError(
            "exactly one plan_ready/execution_ready task is required; pass --task-id"
        )
    return str(candidates[0]["task_id"])


def execution_packet(project: Path, task_id: str) -> str:
    base = f".agency/tasks/active/{task_id}"
    text = "\n".join(
        [
            EXECUTION_SESSION_HEADER,
            f"任务 ID：{task_id}",
            "编排深度：0",
            f"项目根目录：{project}",
            f"任务清单：{base}/task-plan.json",
            f"团队计划：{base}/TEAM_PLAN.json",
            f"进度文件：{base}/PROGRESS.md",
            "执行模型请求：GPT-5.6 Sol",
            "推理强度请求：ultra",
            f"执行职责：{EXECUTION_SESSION_DUTY}",
            f"停止条件：{EXECUTION_SESSION_STOP}",
        ]
    )
    parse_execution_session_packet(text)
    return text + "\n"


def _writes_required(plan: dict[str, Any]) -> bool:
    return any(item["write_scope"] for item in plan["work_items"])


def inspect_native_environment_fields(
    project: Path,
    plan: dict[str, Any],
    resolution: dict[str, Any],
    readback: dict[str, Any],
) -> dict[str, Any]:
    required = {
        "native_task_id",
        "provider",
        "actual_model_id",
        "actual_reasoning_effort",
        "cwd",
        "status",
    }
    missing = sorted(required - set(readback))
    if missing:
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": f"native readback missing fields: {', '.join(missing)}",
        }
    model_result = resolve_execution_model(
        {
            "source": "active-host-catalog",
            "live_readback_verified": True,
            "models": [
                {
                    "id": resolution["resolved_model_id"],
                    "display_name": "GPT-5.6 Sol",
                    "provider": resolution["provider"],
                    "supported_reasoning": [resolution["resolved_reasoning"]],
                }
            ],
        },
        spawn_readback=readback,
        catalog_mechanically_verified=True,
    )
    if model_result.get("status") == "FAIL":
        return model_result
    native_task_id = readback.get("native_task_id")
    if not isinstance(native_task_id, str) or not native_task_id.strip() or native_task_id in {
        "pending",
        "unknown",
        "same-thread",
    }:
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": "native task id is missing or a placeholder",
        }
    if readback.get("status") not in {"active", "running", "in_progress", "working"}:
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": "native task status does not prove an active execution session",
        }
    raw_cwd = readback.get("cwd")
    if not isinstance(raw_cwd, str) or not Path(raw_cwd).is_absolute():
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": "native task cwd is not absolute",
        }
    cwd = Path(raw_cwd).resolve()
    if not cwd.is_dir():
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": "native task cwd does not exist",
        }
    if _writes_required(plan):
        raw_worktree = readback.get("worktree_path")
        if (
            readback.get("isolated_worktree") is not True
            or not isinstance(raw_worktree, str)
            or not Path(raw_worktree).is_absolute()
            or Path(raw_worktree).resolve() != cwd
        ):
            return {
                "status": "FAIL",
                "resolution_status": "readback_mismatch",
                "reason": "write task lacks isolated worktree readback",
            }
    elif cwd != project.resolve():
        return {
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "reason": "read-only native task cwd does not match the project",
        }
    return {
        "status": "fields_consistent_unverified",
        "resolution_status": "resolved",
        "native_task_id": native_task_id,
        "model_fields_consistent": True,
        "cwd_fields_consistent": True,
        "worktree_fields_consistent": not _writes_required(plan)
        or readback.get("isolated_worktree") is True,
    }


def _prepare_execution_launch_locked(
    root: Path,
    selected_task_id: str,
    *,
    catalog: dict[str, Any],
    native_capabilities: dict[str, Any] | None = None,
    native_readback: dict[str, Any] | None = None,
    require_native: bool = False,
    catalog_mechanically_verified: bool = False,
) -> dict[str, Any]:
    task_dir = active_task_dir(root, selected_task_id)
    plan = validate_task_plan(
        load_json(task_dir / "task-plan.json"), expected_task_id=selected_task_id
    )
    if plan["status"] not in {"plan_ready", "execution_ready"}:
        raise ValueError("execution launch requires plan_ready or execution_ready")
    team_plan = resolve_team_plan(plan)
    write_team_plan(task_dir, team_plan)
    plan = validate_task_plan(
        load_json(task_dir / "task-plan.json"), expected_task_id=selected_task_id
    )
    resolution = resolve_execution_model(
        catalog,
        catalog_mechanically_verified=catalog_mechanically_verified,
    )
    model_request = plan.setdefault(
        "execution_model_request",
        {
            "display_request": "GPT-5.6 Sol",
            "reasoning_request": "ultra",
            "resolved_model_id": None,
            "resolution_status": "pending",
        },
    )
    model_request["resolved_model_id"] = resolution.get(
        "resolved_model_id"
    )
    model_request["resolution_status"] = resolution[
        "resolution_status"
    ]
    atomic_write_json(task_dir / "task-plan.json", plan)
    packet = execution_packet(root, selected_task_id)
    atomic_write_text(task_dir / "EXECUTION_LAUNCH_PROMPT.md", packet)

    launch_policy = "require_native" if require_native else "prefer_native"
    session_status: str
    native_task_id: str | None = None
    readback_consistency: dict[str, Any] | None = None
    if not resolution["launch_allowed"]:
        session_status = "user_choice_required"
    else:
        capabilities = native_capabilities or {}
        native_available = capabilities.get("task_thread_create") is True
        if _writes_required(plan) and capabilities.get("isolated_worktree") is not True:
            native_available = False
        if native_readback is not None:
            readback_consistency = inspect_native_environment_fields(
                root, plan, resolution, native_readback
            )
            if readback_consistency["status"] != "fields_consistent_unverified":
                session_status = "readback_mismatch"
                model_request["resolution_status"] = "readback_mismatch"
                atomic_write_json(task_dir / "task-plan.json", plan)
            elif native_available:
                # A caller-provided JSON object can prove field consistency only.
                # It cannot prove that the host actually emitted a create event or
                # bound that event to this packet/current task.
                session_status = "native_launch_ready"
            elif require_native:
                session_status = "TOOL_BLOCKED"
            else:
                session_status = "manual_launch_ready"
        elif native_available:
            session_status = "native_launch_ready"
        elif require_native:
            session_status = "TOOL_BLOCKED"
        else:
            session_status = "manual_launch_ready"

    session = {
        "schema_version": SCHEMA_VERSION,
        "task_id": selected_task_id,
        "orchestration_depth": 0,
        "project_root": str(root),
        "task_plan": f".agency/tasks/active/{selected_task_id}/task-plan.json",
        "team_plan": f".agency/tasks/active/{selected_task_id}/TEAM_PLAN.json",
        "progress_file": f".agency/tasks/active/{selected_task_id}/PROGRESS.md",
        "display_model_request": "GPT-5.6 Sol",
        "reasoning_request": "ultra",
        "resolved_model_id": resolution.get("resolved_model_id"),
        "model_resolution_status": plan["execution_model_request"]["resolution_status"],
        "launch_policy": launch_policy,
        "session_status": session_status,
        "native_task_id": native_task_id,
        # Caller JSON is diagnostic input only and is never persisted as a
        # native-session receipt. bind_execution_session.py is the only public
        # path that can populate these fields and enter executing.
        "native_readback": None,
        "native_readback_attestation": None,
        "created_at": utc_now(),
        "bound_at": None,
    }
    atomic_write_json(task_dir / "execution-session.json", session)

    if session_status in {"manual_launch_ready", "native_launch_ready", "executing"}:
        current = validate_task_plan(load_json(task_dir / "task-plan.json"))["status"]
        if current == "plan_ready":
            transition_task(root, selected_task_id, "execution_ready")
        update_progress(
            root,
            task_id=selected_task_id,
            event_type="team_plan_changed",
            work_id=None,
            actor="execution-root",
            summary=(
                "Execution session prepared; launch handoff is ready"
            ),
            artifacts=[
                f".agency/tasks/active/{selected_task_id}/TEAM_PLAN.json",
                f".agency/tasks/active/{selected_task_id}/execution-session.json",
                f".agency/tasks/active/{selected_task_id}/EXECUTION_LAUNCH_PROMPT.md",
            ],
            idempotency_key=f"execution-launch:{session_status}",
        )
    return {
        "status": session_status,
        "task_id": selected_task_id,
        "lifecycle_status": validate_task_plan(load_json(task_dir / "task-plan.json"))["status"],
        "team_tier": team_plan["team_tier"],
        "selected_profiles": sorted(
            {
                position["profile"]
                for position in team_plan["positions"]
                if position["profile"] != "execution-root"
            }
        ),
        "model_resolution": resolution,
        "native_readback_consistency": readback_consistency,
        "execution_session": str(task_dir / "execution-session.json"),
        "manual_launch_prompt": str(task_dir / "EXECUTION_LAUNCH_PROMPT.md"),
        "new_conversation_created": False,
    }


def _snapshot_launch_file(path: Path) -> tuple[bool, str]:
    if path.is_symlink():
        raise ValueError(f"managed launch output must not be a symlink: {path}")
    return (True, read_regular_text(path)) if path.exists() else (False, "")


def _restore_launch_file(path: Path, snapshot: tuple[bool, str]) -> None:
    existed, text = snapshot
    if existed:
        atomic_write_text(path, text)
    elif path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"cannot remove unsafe launch output: {path}")
        path.unlink()


def _restore_launch_files(
    snapshots: dict[Path, tuple[bool, str]], exc: Exception
) -> None:
    failures: list[str] = []
    for path, snapshot in reversed(list(snapshots.items())):
        try:
            _restore_launch_file(path, snapshot)
        except (OSError, ValueError) as rollback_exc:
            failures.append(f"{path}: {rollback_exc}")
    if failures:
        raise RuntimeError(
            "execution launch failed and rollback was incomplete: "
            + "; ".join(failures)
        ) from exc


def prepare_execution_launch(
    project: Path,
    *,
    task_id: str | None = None,
    catalog: dict[str, Any],
    native_capabilities: dict[str, Any] | None = None,
    native_readback: dict[str, Any] | None = None,
    require_native: bool = False,
    catalog_mechanically_verified: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    with task_index_lock(root):
        selected_task_id = choose_task(root, task_id)
        task_dir = active_task_dir(root, selected_task_id)
        managed_paths = (
            task_dir / "task-plan.json",
            task_dir / "TASK_EXECUTION_CHECKLIST.md",
            task_dir / "TEAM_PLAN.json",
            task_dir / "TEAM_PLAN.md",
            task_dir / "EXECUTION_LAUNCH_PROMPT.md",
            task_dir / "execution-session.json",
            task_dir / "progress.jsonl",
            task_dir / "PROGRESS.md",
            root / ".agency/task-index.json",
        )
        snapshots = {path: _snapshot_launch_file(path) for path in managed_paths}
        try:
            return _prepare_execution_launch_locked(
                root,
                selected_task_id,
                catalog=catalog,
                native_capabilities=native_capabilities,
                native_readback=native_readback,
                require_native=require_native,
                catalog_mechanically_verified=catalog_mechanically_verified,
            )
        except Exception as exc:
            _restore_launch_files(snapshots, exc)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an Agency Execution Root launch.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument("--native-capabilities", type=Path)
    parser.add_argument("--native-readback", type=Path)
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.catalog:
        catalog = load_json(args.catalog)
        catalog_mechanically_verified = False
    else:
        catalog = live_catalog(
            codex_bin=args.codex_bin,
            project=args.project,
            codex_home=args.codex_home,
            state_db=args.state_db,
            thread_id=args.thread_id,
        )
        catalog_mechanically_verified = True
    result = prepare_execution_launch(
        args.project,
        task_id=args.task_id,
        catalog=catalog,
        native_capabilities=(
            load_json(args.native_capabilities) if args.native_capabilities else None
        ),
        native_readback=load_json(args.native_readback) if args.native_readback else None,
        require_native=args.require_native,
        catalog_mechanically_verified=catalog_mechanically_verified,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    if result["status"] in {"TOOL_BLOCKED", "readback_mismatch"}:
        raise SystemExit(2 if result["status"] == "TOOL_BLOCKED" else 1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"Execution launch preparation failed: {exc}")
