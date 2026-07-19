from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agency_task import atomic_write_json, create_task  # noqa: E402


def work_item(
    work_id: str,
    *,
    work_type: str = "implementation",
    read_scope: list[str] | None = None,
    write_scope: list[str] | None = None,
    dependencies: list[str] | None = None,
    risk: str = "low",
    uncertainty: str = "low",
    context_coupling: str = "low",
    parallelizable: bool = False,
    isolated_worktree_required: bool = False,
    title: str | None = None,
    outcome: str | None = None,
) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "title": title or f"Work {work_id}",
        "outcome": outcome or f"Verified outcome for {work_id}",
        "work_type": work_type,
        "dependencies": dependencies or [],
        "read_scope": read_scope or [],
        "write_scope": write_scope or [],
        "verification": [f"verify {work_id}"],
        "risk": risk,
        "uncertainty": uncertainty,
        "context_coupling": context_coupling,
        "parallelizable": parallelizable,
        "isolated_worktree_required": isolated_worktree_required,
        "accountable_position": "",
        "profile": None,
        "review_profile": None,
        "status": "pending",
        "evidence_refs": [],
        "blockers": [],
        "required": True,
    }


def task_plan(
    task_id: str = "task-test-001",
    *,
    items: list[dict[str, Any]] | None = None,
    title: str = "Lifecycle test task",
    objective: str = "Deliver a verified lifecycle fixture",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "title": title,
        "objective": objective,
        "source_discussion": {
            "summary": "The objective and boundaries were discussed.",
            "accepted_decisions": ["Use the durable lifecycle"],
            "constraints": ["Do not invent evidence"],
            "assumptions": [],
            "open_questions": [],
        },
        "acceptance_criteria": ["The fixture has current evidence"],
        "out_of_scope": ["Remote publication"],
        "execution_model_request": {
            "display_request": "GPT-5.6 Sol",
            "reasoning_request": "ultra",
            "resolved_model_id": None,
            "resolution_status": "pending",
        },
        "work_items": items
        or [
            work_item(
                "W-01",
                read_scope=["src/example.py"],
                write_scope=["src/example.py"],
                context_coupling="high",
            )
        ],
        "status": "plan_ready",
    }


def create_fixture_task(
    project: Path,
    task_id: str = "task-test-001",
    *,
    items: list[dict[str, Any]] | None = None,
    title: str = "Lifecycle test task",
    objective: str = "Deliver a verified lifecycle fixture",
) -> tuple[str, Path]:
    result = create_task(
        project,
        task_plan(task_id, items=items, title=title, objective=objective),
    )
    return result["task_id"], Path(result["task_dir"])


def live_catalog(*, ultra: bool = True, include_sol: bool = True) -> dict[str, Any]:
    efforts = ["high", "xhigh"] + (["ultra"] if ultra else [])
    models = (
        [
            {
                "id": "gpt-5.6-sol",
                "display_name": "GPT-5.6-Sol",
                "provider": "openai",
                "supported_reasoning": efforts,
                "provider_evidence": "catalog-advertised",
            }
        ]
        if include_sol
        else []
    )
    return {
        "schema_version": "1.0",
        "source": "active-host-catalog",
        "live_readback_verified": True,
        "models": models,
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def completed_task(
    project: Path,
    task_id: str = "task-archive-001",
    *,
    reviewer: bool = False,
) -> tuple[Path, dict[str, Any]]:
    _, task_dir = create_fixture_task(project, task_id)
    plan = read_json(task_dir / "task-plan.json")
    plan["status"] = "completed"
    for item in plan["work_items"]:
        item["status"] = "completed"
        item["evidence_refs"] = ["artifact.txt", "test exit 0"]
    plan["acceptance_evidence"] = {
        criterion: ["test exit 0"] for criterion in plan["acceptance_criteria"]
    }
    atomic_write_json(task_dir / "task-plan.json", plan)
    positions = [{"profile": "execution-root"}]
    if reviewer:
        positions.append({"profile": "reviewer"})
    atomic_write_json(task_dir / "TEAM_PLAN.json", {"positions": positions})
    (project / "artifact.txt").write_text("verified\n", encoding="utf-8")
    closure = {
        "schema_version": "1.0",
        "review": {
            "status": "handled" if reviewer else "not_required",
            "evidence_refs": ["review PASS"] if reviewer else [],
        },
        "execution_cleanup": {
            "status": "not_applicable",
            "evidence_refs": [],
            "blocker": None,
        },
        "validation_results": [
            {
                "status": "passed",
                "summary": "unit tests passed",
                "evidence_refs": ["test exit 0"],
            }
        ],
        "artifacts": ["artifact.txt"],
    }
    return task_dir, closure


def knowledge_candidate(
    knowledge_id: str = "knowledge-testing-001",
    *,
    statement: str = "Run the focused unit test before the full suite.",
    confidence: str = "verified",
    category: str = "testing",
    target: str = "docs/testing/unit-tests.md",
) -> dict[str, Any]:
    return {
        "knowledge_id": knowledge_id,
        "category": category,
        "statement": statement,
        "applicability": "Future changes to this repository",
        "evidence_refs": ["test exit 0"],
        "source_task_id": "task-archive-001",
        "confidence": confidence,
        "sensitivity": "internal",
        "recommended_target": target,
        "status": "candidate",
    }
