#!/usr/bin/env python3
"""Prepare a new Execution Root session and verify native launch readback."""

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
    safe_project_root,
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


def verify_native_environment_readback(
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
        "status": "verified",
        "resolution_status": "resolved",
        "native_task_id": native_task_id,
        "model_readback_verified": True,
        "cwd_readback_verified": True,
        "worktree_readback_verified": not _writes_required(plan)
        or readback.get("isolated_worktree") is True,
    }


def prepare_execution_launch(
    project: Path,
    *,
    task_id: str | None = None,
    catalog: dict[str, Any],
    native_capabilities: dict[str, Any] | None = None,
    native_readback: dict[str, Any] | None = None,
    require_native: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    selected_task_id = choose_task(root, task_id)
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
    resolution = resolve_execution_model(catalog)
    plan["execution_model_request"]["resolved_model_id"] = resolution.get(
        "resolved_model_id"
    )
    plan["execution_model_request"]["resolution_status"] = resolution[
        "resolution_status"
    ]
    atomic_write_json(task_dir / "task-plan.json", plan)
    packet = execution_packet(root, selected_task_id)
    atomic_write_text(task_dir / "EXECUTION_LAUNCH_PROMPT.md", packet)

    launch_policy = "require_native" if require_native else "prefer_native"
    session_status: str
    native_task_id: str | None = None
    verified_readback: dict[str, Any] | None = None
    if not resolution["launch_allowed"]:
        session_status = "user_choice_required"
    else:
        capabilities = native_capabilities or {}
        native_available = capabilities.get("task_thread_create") is True
        if _writes_required(plan) and capabilities.get("isolated_worktree") is not True:
            native_available = False
        if native_readback is not None:
            native_available = True
            verified_readback = verify_native_environment_readback(
                root, plan, resolution, native_readback
            )
            if verified_readback["status"] != "verified":
                session_status = "readback_mismatch"
                plan["execution_model_request"]["resolution_status"] = "readback_mismatch"
                atomic_write_json(task_dir / "task-plan.json", plan)
            else:
                native_task_id = str(verified_readback["native_task_id"])
                session_status = "executing"
        elif native_available:
            session_status = "native_launch_ready"
        elif require_native:
            session_status = "TOOL_BLOCKED"
        else:
            session_status = "manual_launch_ready"

    session = {
        "schema_version": SCHEMA_VERSION,
        "task_id": selected_task_id,
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
        "native_readback": native_readback,
        "created_at": utc_now(),
    }
    atomic_write_json(task_dir / "execution-session.json", session)

    if session_status in {"manual_launch_ready", "native_launch_ready", "executing"}:
        current = validate_task_plan(load_json(task_dir / "task-plan.json"))["status"]
        if current == "plan_ready":
            transition_task(root, selected_task_id, "execution_ready")
        if session_status == "executing":
            transition_task(root, selected_task_id, "executing")
        update_progress(
            root,
            task_id=selected_task_id,
            event_type="team_plan_changed",
            work_id=None,
            actor="execution-root",
            summary=(
                "Execution session launched with verified native readback"
                if session_status == "executing"
                else "Execution session prepared; launch handoff is ready"
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
        "native_readback_verification": verified_readback,
        "execution_session": str(task_dir / "execution-session.json"),
        "manual_launch_prompt": str(task_dir / "EXECUTION_LAUNCH_PROMPT.md"),
        "new_conversation_created": session_status == "executing",
    }


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
    catalog = (
        load_json(args.catalog)
        if args.catalog
        else live_catalog(
            codex_bin=args.codex_bin,
            project=args.project,
            codex_home=args.codex_home,
            state_db=args.state_db,
            thread_id=args.thread_id,
        )
    )
    result = prepare_execution_launch(
        args.project,
        task_id=args.task_id,
        catalog=catalog,
        native_capabilities=(
            load_json(args.native_capabilities) if args.native_capabilities else None
        ),
        native_readback=load_json(args.native_readback) if args.native_readback else None,
        require_native=args.require_native,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    if result["status"] in {"TOOL_BLOCKED", "readback_mismatch"}:
        raise SystemExit(2 if result["status"] == "TOOL_BLOCKED" else 1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"Execution launch preparation failed: {exc}")
