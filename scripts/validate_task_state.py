#!/usr/bin/env python3
"""Validate durable task plans, indexes, and lifecycle transitions."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from agency_task import (
    LEGAL_TRANSITIONS,
    SCHEMA_VERSION,
    active_task_dir,
    agency_paths,
    create_task,
    load_json,
    load_or_initialize_index,
    transition_task,
    validate_task_plan,
    validate_transition,
)


def sample_plan() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-self-test",
        "title": "Lifecycle self test",
        "objective": "Prove durable plan validation",
        "source_discussion": {
            "summary": "The objective and boundary were accepted.",
            "accepted_decisions": ["Persist a checklist"],
            "constraints": ["Do not auto execute"],
            "assumptions": [],
            "open_questions": [],
        },
        "acceptance_criteria": ["The state machine rejects skipped validation"],
        "out_of_scope": [],
        "execution_model_request": {
            "display_request": "GPT-5.6 Sol",
            "reasoning_request": "ultra",
            "resolved_model_id": None,
            "resolution_status": "pending",
        },
        "work_items": [
            {
                "work_id": "W-01",
                "title": "Validate state",
                "outcome": "State transitions are proven",
                "work_type": "testing",
                "dependencies": [],
                "read_scope": ["task-plan.json"],
                "write_scope": [],
                "verification": ["run self-test"],
                "risk": "low",
                "uncertainty": "low",
                "context_coupling": "low",
                "parallelizable": False,
                "isolated_worktree_required": False,
                "accountable_position": "项目总负责人",
                "profile": None,
                "review_profile": None,
                "status": "pending",
                "evidence_refs": [],
                "blockers": [],
            }
        ],
        "status": "plan_ready",
    }


def validate_project(project: Path) -> dict[str, object]:
    root = project.resolve()
    index = load_or_initialize_index(root)
    active_ids = index["active_task_ids"]
    if len(active_ids) != len(set(active_ids)):
        raise ValueError("task index has duplicate active task ids")
    checked: list[str] = []
    for task_id in active_ids:
        entry = index["tasks"].get(task_id)
        if not isinstance(entry, dict):
            raise ValueError(f"active task is missing index metadata: {task_id}")
        task_dir = active_task_dir(root, task_id)
        plan = validate_task_plan(load_json(task_dir / "task-plan.json"), expected_task_id=task_id)
        if entry.get("status") != plan["status"]:
            raise ValueError(f"task status differs between index and plan: {task_id}")
        checked.append(task_id)
    _, _, archive_root = agency_paths(root)
    return {
        "status": "valid",
        "active_tasks_checked": checked,
        "archive_root": str(archive_root),
    }


def run_self_test() -> dict[str, object]:
    plan = sample_plan()
    validate_task_plan(plan)
    for status_before, targets in LEGAL_TRANSITIONS.items():
        for status_after in targets:
            validate_transition(status_before, status_after)
    rejected: list[str] = []
    for before, after in (
        ("discussion", "archived"),
        ("plan_ready", "completed"),
        ("executing", "completed"),
    ):
        try:
            validate_transition(before, after)
        except ValueError:
            rejected.append(f"{before}->{after}")
    if len(rejected) != 3:
        raise AssertionError("illegal lifecycle transitions were accepted")

    cyclic = sample_plan()
    cyclic["work_items"] = [dict(cyclic["work_items"][0])]
    cyclic["work_items"][0]["dependencies"] = ["W-01"]
    try:
        validate_task_plan(cyclic)
    except ValueError as exc:
        if "depend on itself" not in str(exc):
            raise
    else:
        raise AssertionError("dependency cycle was accepted")

    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw)
        result = create_task(project, sample_plan())
        task_id = str(result["task_id"])
        if result["execution_started"] is not False:
            raise AssertionError("plan creation started execution")
        transition_task(project, task_id, "execution_ready")
        transition_task(project, task_id, "executing")
        transition_task(project, task_id, "blocked")
        transition_task(project, task_id, "executing")
        project_result = validate_project(project)
    return {
        "status": "self-test-passed",
        "illegal_transitions_rejected": rejected,
        "project_validation": project_result["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Agency task state.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_self_test() if args.self_test else validate_project(args.project)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json or args.self_test else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"Task state validation failed: {exc}")

