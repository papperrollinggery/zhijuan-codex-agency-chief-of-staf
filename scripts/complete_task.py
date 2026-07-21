#!/usr/bin/env python3
"""Complete a durable Agency task from current evidence in one guarded step."""

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
    load_json,
    read_regular_text,
    safe_project_root,
    task_index_lock,
    transition_task,
    validate_task_plan,
)
from update_task_progress import record_terminal_progress
from validate_task_archive import safe_artifact, task_requires_reviewer, validate_closure


def _snapshot(path: Path) -> tuple[bool, str]:
    if path.is_symlink():
        raise ValueError(f"managed completion output must not be a symlink: {path}")
    return (True, read_regular_text(path)) if path.exists() else (False, "")


def _restore(path: Path, snapshot: tuple[bool, str]) -> None:
    existed, text = snapshot
    if existed:
        atomic_write_text(path, text)
    elif path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"cannot remove unsafe completion output: {path}")
        path.unlink()


def _restore_transaction(snapshots: dict[Path, tuple[bool, str]], exc: Exception) -> None:
    rollback_errors: list[str] = []
    for path, snapshot in reversed(list(snapshots.items())):
        try:
            _restore(path, snapshot)
        except (OSError, ValueError) as rollback_exc:
            rollback_errors.append(f"{path}: {rollback_exc}")
    if rollback_errors:
        raise RuntimeError(
            "task completion failed and rollback was incomplete: "
            + "; ".join(rollback_errors)
        ) from exc


def _nonempty_strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a non-empty list of strings")
    return [item.strip() for item in value]


def _strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _normalize_acceptance_evidence(
    plan: dict[str, Any], evidence: dict[str, list[str]]
) -> dict[str, list[str]]:
    if not isinstance(evidence, dict):
        raise ValueError("acceptance evidence must be an object")
    expected = set(plan["acceptance_criteria"])
    received = set(evidence)
    if received != expected:
        missing = sorted(expected - received)
        unknown = sorted(received - expected)
        details = []
        if missing:
            details.append("missing: " + "; ".join(missing))
        if unknown:
            details.append("unknown: " + "; ".join(unknown))
        raise ValueError("acceptance evidence does not match criteria (" + ", ".join(details) + ")")
    return {
        criterion: _nonempty_strings(evidence[criterion], f"evidence for {criterion}")
        for criterion in plan["acceptance_criteria"]
    }


def _is_cleanup_resolution(
    existing: dict[str, Any], requested: dict[str, Any]
) -> bool:
    """Allow only the parent-owned cleanup_blocked -> closed reconciliation."""
    existing_without_cleanup = {
        key: value for key, value in existing.items() if key != "execution_cleanup"
    }
    requested_without_cleanup = {
        key: value for key, value in requested.items() if key != "execution_cleanup"
    }
    if existing_without_cleanup != requested_without_cleanup:
        return False

    existing_cleanup = existing["execution_cleanup"]
    requested_cleanup = requested["execution_cleanup"]
    if (
        existing_cleanup.get("status") != "cleanup_blocked"
        or requested_cleanup.get("status") != "closed"
        or not requested_cleanup.get("evidence_refs")
        or requested_cleanup.get("blocker") is not None
    ):
        return False

    mutable_keys = {"status", "evidence_refs", "blocker"}
    existing_fixed = {
        key: value for key, value in existing_cleanup.items() if key not in mutable_keys
    }
    requested_fixed = {
        key: value for key, value in requested_cleanup.items() if key not in mutable_keys
    }
    return existing_fixed == requested_fixed


def complete_task(
    project: Path,
    *,
    task_id: str,
    acceptance_evidence: dict[str, list[str]],
    validation_results: list[dict[str, Any]],
    artifacts: list[str],
    review_evidence: list[str] | None = None,
    cleanup_status: str = "not_applicable",
    cleanup_evidence: list[str] | None = None,
    cleanup_blocker: str | None = None,
    apply: bool,
    _index_lock_held: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    if apply and not _index_lock_held:
        with task_index_lock(root):
            return complete_task(
                root,
                task_id=task_id,
                acceptance_evidence=acceptance_evidence,
                validation_results=validation_results,
                artifacts=artifacts,
                review_evidence=review_evidence,
                cleanup_status=cleanup_status,
                cleanup_evidence=cleanup_evidence,
                cleanup_blocker=cleanup_blocker,
                apply=True,
                _index_lock_held=True,
            )
    task_dir = active_task_dir(root, task_id)
    plan_path = task_dir / "task-plan.json"
    plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    if plan["status"] not in {"executing", "verifying", "completed"}:
        raise ValueError("task completion requires executing, verifying, or completed state")

    open_required = [
        item["work_id"]
        for item in plan["work_items"]
        if item.get("required", True) and item["status"] not in {"completed", "waived"}
    ]
    if open_required:
        raise ValueError("required work remains open: " + ", ".join(open_required))
    for item in plan["work_items"]:
        if item["status"] == "waived" and not str(item.get("waiver_reason", "")).strip():
            raise ValueError(f"waived work has no explicit reason: {item['work_id']}")
        if item["blockers"]:
            raise ValueError(f"unresolved work blocker: {item['work_id']}")

    normalized_evidence = _normalize_acceptance_evidence(plan, acceptance_evidence)
    review_refs = _strings(review_evidence or [], "review evidence")
    cleanup_refs = _strings(cleanup_evidence or [], "cleanup evidence")
    closure = validate_closure(
        {
            "schema_version": SCHEMA_VERSION,
            "review": {
                "status": "handled" if review_refs else "not_required",
                "evidence_refs": review_refs,
            },
            "execution_cleanup": {
                "status": cleanup_status,
                "evidence_refs": cleanup_refs,
                "blocker": cleanup_blocker,
            },
            "validation_results": validation_results,
            "artifacts": artifacts,
        },
        reviewer_required=task_requires_reviewer(plan, task_dir),
    )
    artifact_paths = [
        str(safe_artifact(root, raw).relative_to(root)) for raw in closure["artifacts"]
    ]
    session_path = task_dir / "execution-session.json"
    if session_path.is_file():
        session = load_json(session_path)
        if session.get("native_task_id") and cleanup_status not in {
            "closed",
            "cleanup_blocked",
        }:
            raise ValueError("native task/thread lacks closed or cleanup_blocked evidence")
        if session.get("native_task_id") and cleanup_status == "closed" and not cleanup_refs:
            raise ValueError("closed native task/thread requires cleanup readback evidence")

    closure_path = task_dir / "closure.json"
    cleanup_resolution = False
    closure_missing = not closure_path.is_file()
    if plan["status"] == "completed":
        if plan.get("acceptance_evidence") != normalized_evidence:
            raise ValueError("completed task acceptance evidence does not match current input")
        if not closure_missing:
            existing = validate_closure(
                load_json(closure_path),
                reviewer_required=task_requires_reviewer(plan, task_dir),
            )
            if existing != closure:
                if not _is_cleanup_resolution(existing, closure):
                    raise ValueError("completed task closure does not match current input")
                cleanup_resolution = True

    result = {
        "status": "would-complete",
        "task_id": task_id,
        "status_before": plan["status"],
        "acceptance_criteria_verified": len(normalized_evidence),
        "validation_count": len(closure["validation_results"]),
        "artifacts": artifact_paths,
        "review_status": closure["review"]["status"],
        "cleanup_status": closure["execution_cleanup"]["status"],
        "cleanup_resolution": cleanup_resolution,
    }
    if not apply:
        return result

    if plan["status"] == "completed":
        if closure_missing or cleanup_resolution:
            atomic_write_json(closure_path, closure)
        return {
            **result,
            "status": "completed",
            "status_after": "completed",
            "closure": str(closure_path),
            "closure_updated": closure_missing or cleanup_resolution,
            "progress_event": None,
        }

    managed_paths = (
        plan_path,
        task_dir / "TASK_EXECUTION_CHECKLIST.md",
        root / ".agency/task-index.json",
        task_dir / "progress.jsonl",
        task_dir / "PROGRESS.md",
        closure_path,
    )
    snapshots = {path: _snapshot(path) for path in managed_paths}
    try:
        plan["acceptance_evidence"] = normalized_evidence
        atomic_write_json(plan_path, plan)
        if plan["status"] == "executing":
            transition_task(root, task_id, "verifying")

        # Closure is part of the same transaction and exists before the terminal
        # state is exposed. A later failure restores every managed file exactly.
        atomic_write_json(closure_path, closure)
        verification = [
            reference
            for validation in closure["validation_results"]
            for reference in validation["evidence_refs"]
        ]
        completion = record_terminal_progress(
            root,
            task_id=task_id,
            event_type="task_completed",
            actor="execution-root",
            summary="Current acceptance evidence and validation results verified",
            artifacts=artifact_paths,
            verification=verification,
            idempotency_key="complete",
        )
    except Exception as exc:
        _restore_transaction(snapshots, exc)
        raise
    return {
        **result,
        "status": "completed",
        "status_after": completion["status_after"],
        "closure": str(closure_path),
        "progress_event": completion["event_id"],
    }


def _pairs(values: list[str], label: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for value in values:
        if "::" not in value:
            raise ValueError(f"{label} must use '<name>::<evidence>'")
        name, evidence = (part.strip() for part in value.split("::", 1))
        if not name or not evidence:
            raise ValueError(f"{label} name and evidence must be non-empty")
        grouped.setdefault(name, []).append(evidence)
    return grouped


def _pair_items(values: list[list[str]], label: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for value in values:
        if len(value) != 2:
            raise ValueError(f"{label} must provide exactly <name> <evidence>")
        name, evidence = (part.strip() for part in value)
        if not name or not evidence:
            raise ValueError(f"{label} name and evidence must be non-empty")
        grouped.setdefault(name, []).append(evidence)
    return grouped


def _merge_pair_groups(*groups: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for group in groups:
        for name, evidence in group.items():
            merged.setdefault(name, []).extend(evidence)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate evidence and complete an Agency task.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--criterion-evidence", action="append", default=[], metavar="CRITERION::EVIDENCE")
    parser.add_argument(
        "--criterion-evidence-item",
        action="append",
        nargs=2,
        default=[],
        metavar=("CRITERION", "EVIDENCE"),
        help="Unambiguous criterion/evidence argv pair; preferred over the legacy :: form.",
    )
    parser.add_argument("--validation", action="append", default=[], metavar="SUMMARY::EVIDENCE")
    parser.add_argument(
        "--validation-item",
        action="append",
        nargs=2,
        default=[],
        metavar=("SUMMARY", "EVIDENCE"),
        help="Unambiguous validation/evidence argv pair; preferred over the legacy :: form.",
    )
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--review-evidence", action="append", default=[])
    parser.add_argument(
        "--cleanup-status",
        choices=("closed", "cleanup_blocked", "not_applicable"),
        default="not_applicable",
    )
    parser.add_argument("--cleanup-evidence", action="append", default=[])
    parser.add_argument("--cleanup-blocker")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    acceptance = _merge_pair_groups(
        _pairs(args.criterion_evidence, "criterion evidence"),
        _pair_items(args.criterion_evidence_item, "criterion evidence item"),
    )
    validation_evidence = _merge_pair_groups(
        _pairs(args.validation, "validation"),
        _pair_items(args.validation_item, "validation item"),
    )
    validations = [
        {"status": "passed", "summary": summary, "evidence_refs": refs}
        for summary, refs in validation_evidence.items()
    ]
    result = complete_task(
        args.project,
        task_id=args.task_id,
        acceptance_evidence=acceptance,
        validation_results=validations,
        artifacts=args.artifact,
        review_evidence=args.review_evidence,
        cleanup_status=args.cleanup_status,
        cleanup_evidence=args.cleanup_evidence,
        cleanup_blocker=args.cleanup_blocker,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Task completion failed: {exc}")
