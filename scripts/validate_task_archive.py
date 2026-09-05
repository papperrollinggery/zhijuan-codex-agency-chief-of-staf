#!/usr/bin/env python3
"""Validate archive readiness and archived task manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from agency_task import (
    SCHEMA_VERSION,
    atomic_write_json,
    load_json,
    read_regular_text,
    validate_task_plan,
)


ARCHIVE_DISPOSITIONS = frozenset({"completed", "cancelled", "superseded"})
CLEANUP_STATUSES = frozenset({"closed", "cleanup_blocked", "not_applicable"})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_artifact(project: Path, raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"archive artifact path is unsafe: {raw}")
    root = project.resolve(strict=True)
    current = root
    for index, part in enumerate(candidate.parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ValueError(f"archive artifact is missing or unsafe: {raw}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"archive artifact is missing or a symlink: {raw}")
        if index < len(candidate.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"archive artifact parent is not a directory: {raw}")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"archive artifact escapes project: {raw}")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError(f"archive artifact must be a regular file: {raw}")
    return resolved


def snapshot_artifact(project: Path, raw: str) -> dict[str, Any]:
    """Bind a regular artifact's bytes without loading large media into memory."""
    path = safe_artifact(project, raw)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"artifact must be a regular file: {raw}")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.fstat(descriptor)
        current = path.lstat()
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise ValueError(f"artifact changed while reading: {raw}")
        return {"sha256": digest.hexdigest(), "bytes": after.st_size}
    finally:
        os.close(descriptor)


def _progress_kind(event: dict[str, Any]) -> str | None:
    """Read legacy logs conservatively; new writers persist the event type."""
    if "event_type" in event:
        return event["event_type"]
    before, after = event.get("status_before"), event.get("status_after")
    if event.get("blockers"):
        return "verification_failed"
    if before == "in_progress" and after == "completed":
        return "work_completed"
    if before in {"pending", "blocked"} and after == "in_progress":
        return "work_started"
    if before == after and event.get("verification"):
        return "verification_completed"
    return None


def validate_completion_evidence(
    project: Path,
    task_dir: Path,
    plan: dict[str, Any],
    closure: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Check recorded execution and current bytes, not the truth of prose claims.

    Verification references are Root-recorded observations. Matching them cannot
    prove a command ran or judge domain quality; model evals and review do that.
    """
    from update_task_progress import load_events

    events = load_events(task_dir / "progress.jsonl")
    known_refs: set[str] = set()
    verified_refs: set[str] = set()
    snapshots: dict[str, dict[str, Any]] = {}
    accepted_event_ids: set[str] = set()
    for item in plan["work_items"]:
        if item["status"] != "completed":
            continue
        successful: list[dict[str, Any]] = []
        completed = False
        for event in events:
            if event.get("work_id") != item["work_id"]:
                continue
            if event.get("task_id") != plan["task_id"]:
                raise ValueError("work completion evidence belongs to a different task")
            kind = _progress_kind(event)
            if kind in {"work_started", "verification_failed", "blocker_found"}:
                successful = []
                completed = False
            elif kind in {"work_completed", "verification_completed"} and event.get("verification"):
                successful.append(event)
                completed = completed or kind == "work_completed"
        if not completed:
            raise ValueError(f"missing current work completion evidence: {item['work_id']}")
        for event in successful:
            accepted_event_ids.add(event["event_id"])
            verified_refs.update(_string_list(event.get("verification"), "recorded verification"))
            known_refs.update(_string_list(event.get("artifacts"), "recorded artifacts"))
    # Preserve global chronology when different work items verify the same file.
    for event in events:
        if event.get("event_id") in accepted_event_ids:
            snapshot_map = event.get("artifact_snapshots", {})
            if not isinstance(snapshot_map, dict):
                raise ValueError("recorded artifact verification must be an object")
            snapshots.update(snapshot_map)
    known_refs.update(verified_refs)
    for result in closure["validation_results"]:
        if not set(result["evidence_refs"]).issubset(verified_refs):
            raise ValueError("completion validation must reference recorded verification")
    for refs in plan.get("acceptance_evidence", {}).values():
        if not set(refs).issubset(known_refs):
            raise ValueError("acceptance must reference recorded work evidence")
    current_snapshots = {}
    for raw in closure["artifacts"]:
        current = snapshot_artifact(project, raw)
        if raw not in snapshots:
            raise ValueError(f"missing current artifact verification: {raw}; record a verification_completed event")
        if snapshots[raw] != current:
            raise ValueError(f"artifact changed since verification: {raw}")
        current_snapshots[raw] = current
    bound = closure.get("artifact_snapshots")
    if bound is not None and bound != current_snapshots:
        raise ValueError("artifact changed since task completion")
    return current_snapshots


def _safe_archive_entry(root: Path, relative: Path) -> Path:
    """Resolve one manifest entry while rejecting every in-archive symlink."""
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("archive manifest file path is unsafe")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise ValueError(f"archived file is missing or unsafe: {relative}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"archived file is missing or unsafe: {relative}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"archived file parent is unsafe: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ValueError(f"archived file is missing or unsafe: {relative}")
    return current


def _string_list(value: object, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if nonempty and not value:
        raise ValueError(f"{label} must not be empty")
    return [item.strip() for item in value]


def validate_closure(
    closure: dict[str, Any],
    *,
    reviewer_required: bool,
    completion_evidence_required: bool = True,
) -> dict[str, Any]:
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
    if cleanup["status"] != "cleanup_blocked" and blocker is not None:
        raise ValueError("execution cleanup blocker is only valid for cleanup_blocked")
    if not isinstance(validations, list) or (completion_evidence_required and not validations):
        raise ValueError("completed archive requires current validation results")
    for index, result in enumerate(validations):
        if not isinstance(result, dict) or result.get("status") != "passed":
            raise ValueError(f"validation result {index} is not passed")
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            raise ValueError(f"validation result {index} has no summary")
        _string_list(result.get("evidence_refs"), f"validation result {index} evidence", nonempty=True)
    artifact_list = _string_list(
        artifacts,
        "archive artifacts",
        nonempty=completion_evidence_required,
    )
    return {
        **closure,
        "review": {**review, "evidence_refs": review_refs},
        "execution_cleanup": {**cleanup, "evidence_refs": cleanup_refs},
        "artifacts": artifact_list,
    }


def task_requires_reviewer(plan: dict[str, Any], task_dir: Path) -> bool:
    """Derive the review gate from task risk as well as the generated team plan."""
    team_path = task_dir / "TEAM_PLAN.json"
    team = load_json(team_path) if team_path.is_file() else {}
    positions = team.get("positions", [])
    selected = any(
        isinstance(position, dict) and position.get("profile") == "reviewer"
        for position in positions
    )
    risk_required = any(
        item.get("risk") in {"high", "critical"}
        or item.get("work_type") in {"review", "release"}
        for item in plan["work_items"]
    )
    return selected or risk_required


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
    if disposition == "completed":
        for item in plan["work_items"]:
            if item["status"] == "waived" and (
                not isinstance(item.get("waiver_reason"), str)
                or not item["waiver_reason"].strip()
            ):
                raise ValueError(f"waived work has no explicit reason: {item['work_id']}")
            if item["blockers"]:
                raise ValueError(f"unresolved work blocker: {item['work_id']}")
        evidence = plan.get("acceptance_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("acceptance evidence map is missing")
        for criterion in plan["acceptance_criteria"]:
            _string_list(
                evidence.get(criterion),
                f"acceptance evidence for {criterion}",
                nonempty=True,
            )

    reviewer_required = disposition == "completed" and task_requires_reviewer(plan, task_dir)
    normalized_closure = validate_closure(
        closure,
        reviewer_required=reviewer_required,
        completion_evidence_required=disposition == "completed",
    )
    session_path = task_dir / "execution-session.json"
    if session_path.is_file():
        session = load_json(session_path)
        if session.get("native_task_id"):
            cleanup = normalized_closure["execution_cleanup"]
            if cleanup["status"] not in {"closed", "cleanup_blocked"}:
                raise ValueError("native task/thread lacks closed or cleanup_blocked evidence")
            if cleanup["status"] == "closed" and not cleanup["evidence_refs"]:
                raise ValueError("closed native task/thread requires cleanup readback evidence")
    resolved_artifacts = [safe_artifact(root, raw) for raw in normalized_closure["artifacts"]]
    if disposition == "completed":
        normalized_closure["artifact_snapshots"] = validate_completion_evidence(
            root, task_dir, plan, normalized_closure
        )
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
        "evidence_scope": "recorded-verification-and-current-artifact-bytes" if disposition == "completed" else "disposition-only",
        "closure": normalized_closure,
    }


def validate_archive_directory(archive_dir: Path) -> dict[str, Any]:
    supplied = archive_dir.expanduser().absolute()
    try:
        supplied_info = supplied.lstat()
    except OSError as exc:
        raise ValueError("archive directory is missing or unsafe") from exc
    if stat.S_ISLNK(supplied_info.st_mode) or not stat.S_ISDIR(supplied_info.st_mode):
        raise ValueError("archive directory is missing or unsafe")
    root = supplied.resolve(strict=True)
    required = {
        "task-plan.json",
        "ARCHIVE_REPORT.md",
        "archive-manifest.json",
        "knowledge-candidates.json",
    }
    unsafe_entries = [
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_symlink()
    ]
    if unsafe_entries:
        raise ValueError(
            "archive contains symlinks: " + ", ".join(map(str, unsafe_entries))
        )
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
    declared_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("archive manifest file entry is invalid")
        relative = Path(entry["path"])
        relative_text = str(relative)
        if relative_text in declared_paths:
            raise ValueError(f"archive manifest contains duplicate file: {relative}")
        declared_paths.add(relative_text)
        path = _safe_archive_entry(root, relative)
        if entry.get("sha256") != sha256(path) or entry.get("bytes") != path.stat().st_size:
            raise ValueError(f"archived file manifest mismatch: {relative}")
        checked += 1
    actual_paths = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "archive-manifest.json"
    }
    if declared_paths != actual_paths:
        missing_from_manifest = sorted(actual_paths - declared_paths)
        missing_from_archive = sorted(declared_paths - actual_paths)
        raise ValueError(
            "archive manifest coverage mismatch "
            f"(unlisted={missing_from_manifest}, missing={missing_from_archive})"
        )
    plan = validate_task_plan(load_json(root / "task-plan.json"))
    if plan["status"] not in {"archived", "cancelled", "superseded"}:
        raise ValueError("archived task plan has an active status")
    if manifest.get("task_id") != plan["task_id"]:
        raise ValueError("archive manifest task_id does not match task plan")
    disposition = manifest.get("archive_disposition")
    source_status = manifest.get("source_status")
    final_status = manifest.get("final_status")
    if plan["status"] == "archived":
        if (disposition, source_status, final_status) != (
            "completed",
            "completed",
            "archived",
        ):
            raise ValueError("completed archive disposition/status fields are inconsistent")
    elif (disposition, source_status, final_status) != (
        plan["status"],
        plan["status"],
        plan["status"],
    ):
        raise ValueError("noncompleted archive disposition/status fields are inconsistent")
    expected_reason = plan.get("status_reason") if plan["status"] != "archived" else None
    if manifest.get("disposition_reason") != expected_reason:
        raise ValueError("archive disposition reason does not match task plan")
    expected_blockers = [
        {"work_id": item["work_id"], "blockers": item["blockers"]}
        for item in plan["work_items"]
        if item["blockers"]
    ]
    if manifest.get("unresolved_blockers") != expected_blockers:
        raise ValueError("archive blocker summary does not match task plan")
    if manifest.get("acceptance_evidence") != plan.get("acceptance_evidence", {}):
        raise ValueError("archive acceptance evidence does not match task plan")
    closure = manifest.get("closure")
    normalized_closure = validate_closure(
        closure,
        reviewer_required=plan["status"] == "archived"
        and task_requires_reviewer(plan, root),
        completion_evidence_required=plan["status"] == "archived",
    )
    if manifest.get("artifacts") != normalized_closure["artifacts"]:
        raise ValueError("archive artifacts do not match closure")
    try:
        candidates = json.loads(read_regular_text(root / "knowledge-candidates.json"))
    except json.JSONDecodeError as exc:
        raise ValueError("knowledge-candidates.json must contain valid JSON") from exc
    from deposit_knowledge import (
        validate_candidate_provenance,
        validate_knowledge_candidates,
    )

    normalized_candidates = validate_knowledge_candidates(candidates)
    closure = normalized_closure
    evidence_refs = {
        reference
        for item in plan["work_items"]
        for reference in item["evidence_refs"]
    }
    for references in manifest.get("acceptance_evidence", {}).values():
        if isinstance(references, list):
            evidence_refs.update(item for item in references if isinstance(item, str))
    if isinstance(closure, dict):
        for section in ("review", "execution_cleanup"):
            value = closure.get(section, {})
            if isinstance(value, dict) and isinstance(value.get("evidence_refs"), list):
                evidence_refs.update(
                    item for item in value["evidence_refs"] if isinstance(item, str)
                )
        for result in closure.get("validation_results", []):
            if isinstance(result, dict) and isinstance(result.get("evidence_refs"), list):
                evidence_refs.update(
                    item for item in result["evidence_refs"] if isinstance(item, str)
                )
        artifacts = closure.get("artifacts", [])
        if isinstance(artifacts, list):
            evidence_refs.update(item for item in artifacts if isinstance(item, str))
    validate_candidate_provenance(
        normalized_candidates,
        source_task_id=plan["task_id"],
        allowed_evidence_refs=evidence_refs,
    )
    return {
        "status": "valid",
        "task_id": plan["task_id"],
        "files_checked": checked,
        "knowledge_candidates": len(normalized_candidates),
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
            {
                "schema_version": SCHEMA_VERSION,
                "task_id": plan["task_id"],
                "archive_disposition": "completed",
                "source_status": "completed",
                "final_status": "archived",
                "disposition_reason": None,
                "unresolved_blockers": [],
                "closure": closure,
                "acceptance_evidence": plan["acceptance_evidence"],
                "artifacts": closure["artifacts"],
                "files": files,
            },
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
