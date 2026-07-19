#!/usr/bin/env python3
"""Validate archive readiness and archived task manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from agency_task import SCHEMA_VERSION, atomic_write_json, load_json, validate_task_plan


ARCHIVE_DISPOSITIONS = frozenset({"completed", "cancelled", "superseded"})
CLEANUP_STATUSES = frozenset({"closed", "cleanup_blocked", "not_applicable"})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_artifact(project: Path, raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"archive artifact path is unsafe: {raw}")
    resolved = (project / candidate).resolve()
    if not resolved.is_relative_to(project.resolve()):
        raise ValueError(f"archive artifact escapes project: {raw}")
    if resolved.is_symlink() or not resolved.exists():
        raise ValueError(f"archive artifact is missing or a symlink: {raw}")
    return resolved


def _string_list(value: object, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if nonempty and not value:
        raise ValueError(f"{label} must not be empty")
    return [item.strip() for item in value]


def validate_closure(closure: dict[str, Any], *, reviewer_required: bool) -> dict[str, Any]:
    if closure.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("archive closure schema_version is invalid")
    review = closure.get("review")
    cleanup = closure.get("execution_cleanup")
    validations = closure.get("validation_results")
    artifacts = closure.get("artifacts")
    if not isinstance(review, dict) or review.get("status") not in {"handled", "not_required"}:
        raise ValueError("archive review status must be handled or not_required")
    review_refs = _string_list(review.get("evidence_refs"), "review.evidence_refs")
    if reviewer_required and (review["status"] != "handled" or not review_refs):
        raise ValueError("selected Reviewer has no handled review evidence")
    if review["status"] == "handled" and not review_refs:
        raise ValueError("handled review must include evidence")
    if not isinstance(cleanup, dict) or cleanup.get("status") not in CLEANUP_STATUSES:
        raise ValueError("execution cleanup status is invalid")
    cleanup_refs = _string_list(cleanup.get("evidence_refs"), "execution_cleanup.evidence_refs")
    blocker = cleanup.get("blocker")
    if blocker is not None and (not isinstance(blocker, str) or not blocker.strip()):
        raise ValueError("execution cleanup blocker must be a non-empty string or null")
    if cleanup["status"] == "cleanup_blocked" and not blocker:
        raise ValueError("cleanup_blocked requires an explicit blocker")
    if not isinstance(validations, list) or not validations:
        raise ValueError("archive requires current validation results")
    for index, result in enumerate(validations):
        if not isinstance(result, dict) or result.get("status") != "passed":
            raise ValueError(f"validation result {index} is not passed")
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            raise ValueError(f"validation result {index} has no summary")
        _string_list(result.get("evidence_refs"), f"validation result {index} evidence", nonempty=True)
    artifact_list = _string_list(artifacts, "archive artifacts", nonempty=True)
    return {
        **closure,
        "review": {**review, "evidence_refs": review_refs},
        "execution_cleanup": {**cleanup, "evidence_refs": cleanup_refs},
        "artifacts": artifact_list,
    }


def validate_archive_readiness(
    project: Path,
    task_dir: Path,
    closure: dict[str, Any],
    *,
    disposition: str = "completed",
) -> dict[str, Any]:
    root = project.resolve()
    if disposition not in ARCHIVE_DISPOSITIONS:
        raise ValueError("archive disposition is invalid")
    plan = validate_task_plan(load_json(task_dir / "task-plan.json"))
    if plan["status"] != disposition:
        raise ValueError(
            f"archive disposition {disposition} does not match task status {plan['status']}"
        )
    if disposition in {"cancelled", "superseded"} and (
        not isinstance(plan.get("status_reason"), str) or not plan["status_reason"].strip()
    ):
        raise ValueError(f"{disposition} archive requires an explicit status reason")
    open_required = [
        item["work_id"]
        for item in plan["work_items"]
        if item.get("required", True) and item["status"] not in {"completed", "waived"}
    ]
    if disposition == "completed" and open_required:
        raise ValueError("required work remains open: " + ", ".join(open_required))
    for item in plan["work_items"]:
        if item["status"] == "waived" and (
            not isinstance(item.get("waiver_reason"), str) or not item["waiver_reason"].strip()
        ):
            raise ValueError(f"waived work has no explicit reason: {item['work_id']}")
        if item["blockers"]:
            raise ValueError(f"unresolved work blocker: {item['work_id']}")
    if disposition == "completed":
        evidence = plan.get("acceptance_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("acceptance evidence map is missing")
        for criterion in plan["acceptance_criteria"]:
            _string_list(
                evidence.get(criterion),
                f"acceptance evidence for {criterion}",
                nonempty=True,
            )

    team_path = task_dir / "TEAM_PLAN.json"
    team = load_json(team_path) if team_path.is_file() else {}
    positions = team.get("positions", [])
    reviewer_required = any(
        isinstance(position, dict) and position.get("profile") == "reviewer"
        for position in positions
    )
    normalized_closure = validate_closure(closure, reviewer_required=reviewer_required)
    session_path = task_dir / "execution-session.json"
    if session_path.is_file():
        session = load_json(session_path)
        if session.get("native_task_id") and normalized_closure["execution_cleanup"]["status"] not in {
            "closed",
            "cleanup_blocked",
        }:
            raise ValueError("native task/thread lacks closed or cleanup_blocked evidence")
    resolved_artifacts = [safe_artifact(root, raw) for raw in normalized_closure["artifacts"]]
    return {
        "status": "ready",
        "task_id": plan["task_id"],
        "disposition": disposition,
        "required_work_verified": not open_required,
        "acceptance_criteria_verified": disposition != "completed"
        or bool(plan["acceptance_criteria"]),
        "review_verified": normalized_closure["review"]["status"],
        "cleanup_status": normalized_closure["execution_cleanup"]["status"],
        "artifact_paths": [str(path.relative_to(root)) for path in resolved_artifacts],
        "validation_count": len(normalized_closure["validation_results"]),
        "closure": normalized_closure,
    }


def validate_archive_directory(archive_dir: Path) -> dict[str, Any]:
    root = archive_dir.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("archive directory is missing or unsafe")
    required = {
        "task-plan.json",
        "ARCHIVE_REPORT.md",
        "archive-manifest.json",
        "knowledge-candidates.json",
    }
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise ValueError("archive is missing files: " + ", ".join(missing))
    manifest = load_json(root / "archive-manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("archive manifest schema_version is invalid")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("archive manifest files must be a list")
    checked = 0
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("archive manifest file entry is invalid")
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("archive manifest file path is unsafe")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"archived file is missing or unsafe: {relative}")
        if entry.get("sha256") != sha256(path) or entry.get("bytes") != path.stat().st_size:
            raise ValueError(f"archived file manifest mismatch: {relative}")
        checked += 1
    plan = validate_task_plan(load_json(root / "task-plan.json"))
    if plan["status"] not in {"archived", "cancelled", "superseded"}:
        raise ValueError("archived task plan has an active status")
    candidates = json.loads((root / "knowledge-candidates.json").read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise ValueError("knowledge-candidates.json must contain a list")
    return {
        "status": "valid",
        "task_id": plan["task_id"],
        "files_checked": checked,
        "knowledge_candidates": len(candidates),
    }


def run_self_test() -> dict[str, Any]:
    from validate_task_state import sample_plan

    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw)
        task_dir = project / ".agency" / "tasks" / "active" / "task-self-test"
        task_dir.mkdir(parents=True)
        artifact = project / "artifact.txt"
        artifact.write_text("verified\n", encoding="utf-8")
        plan = sample_plan()
        plan["status"] = "completed"
        plan["work_items"][0]["status"] = "completed"
        plan["acceptance_evidence"] = {
            plan["acceptance_criteria"][0]: ["self-test exit 0"]
        }
        atomic_write_json(task_dir / "task-plan.json", plan)
        atomic_write_json(
            task_dir / "TEAM_PLAN.json",
            {"positions": [{"profile": "execution-root"}]},
        )
        closure = {
            "schema_version": SCHEMA_VERSION,
            "review": {"status": "not_required", "evidence_refs": []},
            "execution_cleanup": {
                "status": "not_applicable",
                "evidence_refs": [],
                "blocker": None,
            },
            "validation_results": [
                {
                    "status": "passed",
                    "summary": "self-test passed",
                    "evidence_refs": ["self-test exit 0"],
                }
            ],
            "artifacts": ["artifact.txt"],
        }
        readiness = validate_archive_readiness(project, task_dir, closure)
        incomplete = dict(plan)
        incomplete["status"] = "executing"
        atomic_write_json(task_dir / "task-plan.json", incomplete)
        try:
            validate_archive_readiness(project, task_dir, closure)
        except ValueError:
            rejected = True
        else:
            rejected = False
        if not rejected:
            raise AssertionError("incomplete task was archive-ready")

        archive_dir = project / ".agency" / "tasks" / "archive" / "2026" / "07" / "task-self-test"
        archive_dir.mkdir(parents=True)
        plan["status"] = "archived"
        atomic_write_json(archive_dir / "task-plan.json", plan)
        (archive_dir / "ARCHIVE_REPORT.md").write_text("# Archive\n", encoding="utf-8")
        (archive_dir / "knowledge-candidates.json").write_text("[]\n", encoding="utf-8")
        files = []
        for name in ("task-plan.json", "ARCHIVE_REPORT.md", "knowledge-candidates.json"):
            path = archive_dir / name
            files.append({"path": name, "sha256": sha256(path), "bytes": path.stat().st_size})
        atomic_write_json(
            archive_dir / "archive-manifest.json",
            {"schema_version": SCHEMA_VERSION, "task_id": plan["task_id"], "files": files},
        )
        archive_validation = validate_archive_directory(archive_dir)
    return {
        "status": "self-test-passed",
        "ready_disposition": readiness["disposition"],
        "incomplete_rejected": rejected,
        "manifest_files_checked": archive_validation["files_checked"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Agency task archive readiness.")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--task-dir", type=Path)
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--disposition", choices=sorted(ARCHIVE_DISPOSITIONS), default="completed")
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = run_self_test()
    elif args.archive_dir:
        result = validate_archive_directory(args.archive_dir)
    else:
        if args.project is None or args.task_dir is None or args.closure is None:
            raise ValueError("--project, --task-dir, and --closure are required")
        result = validate_archive_readiness(
            args.project,
            args.task_dir,
            load_json(args.closure),
            disposition=args.disposition,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json or args.self_test else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Task archive validation failed: {exc}")
