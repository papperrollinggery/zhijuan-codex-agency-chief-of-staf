#!/usr/bin/env python3
"""Archive a completed, cancelled, or superseded Agency task after validation."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agency_task import (
    SCHEMA_VERSION,
    active_task_dir,
    atomic_write_json,
    atomic_write_text,
    load_json,
    load_or_initialize_index,
    render_checklist,
    safe_project_root,
    utc_now,
    validate_task_plan,
    validate_transition,
    write_index,
)
from deposit_knowledge import (
    deposit_knowledge,
    load_candidates,
    plan_deposits,
    validate_candidate_provenance,
    validate_knowledge_candidates,
)
from update_task_progress import append_event, event_id_for, load_events, render_progress
from validate_task_archive import (
    ARCHIVE_DISPOSITIONS,
    sha256,
    validate_archive_directory,
    validate_archive_readiness,
)


def archive_relative_path(task_id: str, moment: datetime) -> str:
    return f".agency/tasks/archive/{moment:%Y}/{moment:%m}/{task_id}"


def closure_path_for(project: Path, task_id: str, supplied: Path | None) -> Path:
    """Use an explicit legacy closure or the completion command's current closure."""
    if supplied is not None:
        return supplied
    return active_task_dir(safe_project_root(project), task_id) / "closure.json"


def render_archive_report(
    plan: dict[str, Any], readiness: dict[str, Any], candidate_count: int, archived_at: str
) -> str:
    closure = readiness["closure"]
    lines = [
        f"# {plan['title']} — 归档报告",
        "",
        f"- 任务 ID：{plan['task_id']}",
        f"- 归档处置：{readiness['disposition']}",
        f"- 归档时间：{archived_at}",
        f"- Review：{closure['review']['status']}",
        f"- Task/Thread 清理：{closure['execution_cleanup']['status']}",
        f"- 当前验证结果：{len(closure['validation_results'])} 项",
        f"- 长期知识候选：{candidate_count} 项",
        "",
        "## 完成标准证据",
        "",
    ]
    evidence = plan.get("acceptance_evidence", {})
    if readiness["disposition"] == "completed":
        for criterion in plan["acceptance_criteria"]:
            lines.append(f"- {criterion}：{'；'.join(evidence[criterion])}")
    else:
        lines.append(f"- 任务按 {readiness['disposition']} 处置，不标记为 completed。")
        lines.append(f"- 处置原因：{plan.get('status_reason', '未记录')}")
        unresolved = [
            f"{item['work_id']}：{'；'.join(item['blockers'])}"
            for item in plan["work_items"]
            if item["blockers"]
        ]
        if unresolved:
            lines.append(f"- 保留阻塞：{'；'.join(unresolved)}")
    lines.extend(["", "## 验证结果", ""])
    for result in closure["validation_results"]:
        lines.append(f"- {result['summary']}：{result['status']}")
    lines.extend(
        [
            "",
            "归档只记录当前证据；历史自述、占位 Task ID 或计划文本不作为完成证明。",
            "",
        ]
    )
    return "\n".join(lines)


def _manifest_files(task_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(task_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"task archive contains a symlink: {path.relative_to(task_dir)}")
        if not path.is_file() or path.name == "archive-manifest.json":
            continue
        result.append(
            {
                "path": str(path.relative_to(task_dir)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return result


def _refresh_manifest(task_dir: Path) -> None:
    path = task_dir / "archive-manifest.json"
    manifest = load_json(path)
    manifest["files"] = _manifest_files(task_dir)
    atomic_write_json(path, manifest)


def _record_archive_event(
    task_dir: Path, plan: dict[str, Any], *, disposition: str
) -> None:
    summary = (
        "Task archive preconditions verified"
        if disposition == "completed"
        else f"Task archived with disposition {disposition}"
    )
    verification = ["archive readiness validated"] if disposition == "completed" else []
    identifier = event_id_for(
        task_id=plan["task_id"],
        event_type="task_archived",
        work_id=None,
        summary=summary,
        artifacts=[],
        verification=verification,
        blockers=[],
        idempotency_key="archive",
    )
    append_event(
        task_dir / "progress.jsonl",
        {
            "event_id": identifier,
            "task_id": plan["task_id"],
            "work_id": None,
            "timestamp": utc_now(),
            "actor": "execution-root",
            "status_before": plan["status"],
            "status_after": "archived" if disposition == "completed" else disposition,
            "summary": summary,
            "artifacts": [],
            "verification": verification,
            "blockers": [],
        },
    )


def _prepare_archive_stage(
    source: Path,
    staging: Path,
    *,
    plan: dict[str, Any],
    readiness: dict[str, Any],
    disposition: str,
    candidates: list[dict[str, Any]],
    archived_at: str,
) -> tuple[dict[str, Any], str]:
    # Copy symlinks as links so validation rejects them instead of following them.
    if validate_task_plan(
        load_json(source / "task-plan.json"), expected_task_id=plan["task_id"]
    ) != plan:
        raise ValueError("active task changed before archive staging")
    source_files = _manifest_files(source)
    shutil.copytree(source, staging, symlinks=True)
    if _manifest_files(source) != source_files or _manifest_files(staging) != source_files:
        raise ValueError("active task changed while archive staging was copied")
    staged_plan = copy.deepcopy(plan)
    atomic_write_json(staging / "knowledge-candidates.json", candidates)
    atomic_write_text(
        staging / "ARCHIVE_REPORT.md",
        render_archive_report(plan, readiness, len(candidates), archived_at),
    )
    _record_archive_event(staging, staged_plan, disposition=disposition)
    if disposition == "completed":
        validate_transition("completed", "archived")
        staged_plan["status"] = "archived"
        final_status = "archived"
    else:
        final_status = disposition
    atomic_write_json(staging / "task-plan.json", staged_plan)
    atomic_write_text(
        staging / "TASK_EXECUTION_CHECKLIST.md", render_checklist(staged_plan)
    )
    atomic_write_text(
        staging / "PROGRESS.md",
        render_progress(staged_plan, load_events(staging / "progress.jsonl")),
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "task_id": staged_plan["task_id"],
        "archive_disposition": disposition,
        "source_status": plan["status"],
        "final_status": final_status,
        "archived_at": archived_at,
        "disposition_reason": (
            plan.get("status_reason") if disposition != "completed" else None
        ),
        "unresolved_blockers": [
            {"work_id": item["work_id"], "blockers": item["blockers"]}
            for item in plan["work_items"]
            if item["blockers"]
        ],
        "closure": readiness["closure"],
        "acceptance_evidence": staged_plan.get("acceptance_evidence", {}),
        "artifacts": readiness["artifact_paths"],
        "files": _manifest_files(staging),
    }
    atomic_write_json(staging / "archive-manifest.json", manifest)
    validate_archive_directory(staging)
    return staged_plan, final_status


def archive_task(
    project: Path,
    *,
    task_id: str,
    closure: dict[str, Any],
    disposition: str = "completed",
    candidates: list[dict[str, Any]] | None = None,
    apply: bool,
    deposit: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    if disposition not in ARCHIVE_DISPOSITIONS:
        raise ValueError("archive disposition is invalid")
    task_dir = active_task_dir(root, task_id)
    plan = validate_task_plan(load_json(task_dir / "task-plan.json"), expected_task_id=task_id)
    normalized_candidates = validate_knowledge_candidates(candidates or [])
    readiness = validate_archive_readiness(
        root, task_dir, closure, disposition=disposition
    )
    allowed_evidence_refs = {
        reference
        for item in plan["work_items"]
        for reference in item["evidence_refs"]
    }
    for references in plan.get("acceptance_evidence", {}).values():
        allowed_evidence_refs.update(references)
    allowed_evidence_refs.update(readiness["closure"]["review"]["evidence_refs"])
    allowed_evidence_refs.update(
        readiness["closure"]["execution_cleanup"]["evidence_refs"]
    )
    allowed_evidence_refs.update(readiness["closure"]["artifacts"])
    for result in readiness["closure"]["validation_results"]:
        allowed_evidence_refs.update(result["evidence_refs"])
    validate_candidate_provenance(
        normalized_candidates,
        source_task_id=task_id,
        allowed_evidence_refs=allowed_evidence_refs,
    )
    if deposit and normalized_candidates:
        # Validate duplicate/conflict/target policy before mutating task state.
        plan_deposits(root, normalized_candidates)
    moment = datetime.now(timezone.utc)
    relative = archive_relative_path(task_id, moment)
    destination = root / relative
    if destination.exists():
        raise ValueError(f"archive destination already exists: {relative}")
    if not apply:
        return {
            "status": "would-archive",
            "task_id": task_id,
            "disposition": disposition,
            "destination": str(destination),
            "readiness": readiness,
            "knowledge_candidates": len(normalized_candidates),
            "knowledge_deposited": False,
        }

    archived_at = utc_now()
    index = load_or_initialize_index(root)
    original_index = copy.deepcopy(index)
    if task_id not in index["tasks"]:
        raise ValueError("task is missing from task index")
    if index["tasks"][task_id].get("status") != plan["status"]:
        raise ValueError("task plan and task index status are inconsistent")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{task_id}.archive-", dir=destination.parent)
    )
    staging = staging_root / "prepared"
    backup = staging_root / "active-backup"
    source_moved = False
    destination_moved = False
    index_write_attempted = False
    final_status = disposition
    try:
        _staged_plan, final_status = _prepare_archive_stage(
            task_dir,
            staging,
            plan=plan,
            readiness=readiness,
            disposition=disposition,
            candidates=normalized_candidates,
            archived_at=archived_at,
        )
        task_dir.rename(backup)
        source_moved = True
        staging.rename(destination)
        destination_moved = True
        if load_or_initialize_index(root) != original_index:
            raise ValueError("task index changed while archive staging was prepared")
        updated_index = copy.deepcopy(index)
        entry = updated_index["tasks"][task_id]
        entry["status"] = final_status
        entry["path"] = relative
        entry["updated_at"] = archived_at
        entry["archived_at"] = archived_at
        entry["archive_disposition"] = disposition
        updated_index["active_task_ids"] = [
            value for value in updated_index["active_task_ids"] if value != task_id
        ]
        if task_id not in updated_index["archived_task_ids"]:
            updated_index["archived_task_ids"].append(task_id)
        index_write_attempted = True
        write_index(root, updated_index)
    except Exception as exc:
        rollback_errors: list[str] = []
        if destination_moved and destination.exists():
            try:
                destination.rename(staging)
            except OSError as rollback_exc:
                rollback_errors.append(f"destination: {rollback_exc}")
        if source_moved and backup.exists() and not task_dir.exists():
            try:
                backup.rename(task_dir)
            except OSError as rollback_exc:
                rollback_errors.append(f"active task: {rollback_exc}")
        if index_write_attempted:
            try:
                atomic_write_json(root / ".agency/task-index.json", original_index)
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append(f"task index: {rollback_exc}")
        if not rollback_errors:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise
        raise RuntimeError(
            "archive transaction failed and rollback was incomplete: "
            + "; ".join(rollback_errors)
        ) from exc

    knowledge_report: dict[str, Any] | None = None
    post_archive_blockers: list[str] = []
    try:
        shutil.rmtree(backup)
        staging_root.rmdir()
    except OSError as exc:
        post_archive_blockers.append(f"archive transaction cleanup failed: {exc}")
    if deposit and normalized_candidates:
        try:
            knowledge_report = deposit_knowledge(
                root,
                destination / "knowledge-candidates.json",
                apply=True,
                report_path=destination / "knowledge-deposit-report.json",
                expected_source_task_id=task_id,
                allowed_evidence_refs=allowed_evidence_refs,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            post_archive_blockers.append(f"knowledge deposit failed: {exc}")
            knowledge_report = {
                "schema_version": SCHEMA_VERSION,
                "status": "blocked",
                "project": str(root),
                "source_candidates": str(destination / "knowledge-candidates.json"),
                "actions": [],
                "deposited_count": 0,
                "limited_candidates_skipped": 0,
                "generated_at": utc_now(),
                "blocker": str(exc),
            }
            try:
                atomic_write_json(
                    destination / "knowledge-deposit-report.json", knowledge_report
                )
            except (OSError, ValueError) as report_exc:
                post_archive_blockers.append(
                    f"knowledge blocker report could not be written: {report_exc}"
                )
    try:
        _refresh_manifest(destination)
        archive_validation = validate_archive_directory(destination)
    except (OSError, ValueError) as exc:
        post_archive_blockers.append(f"archive manifest refresh failed: {exc}")
        archive_validation = {
            "status": "invalid",
            "task_id": task_id,
            "error": str(exc),
        }
    return {
        "status": "archived" if not post_archive_blockers else "archived_with_blocker",
        "task_id": task_id,
        "disposition": disposition,
        "destination": str(destination),
        "archive_validation": archive_validation,
        "knowledge_candidates": len(normalized_candidates),
        "knowledge_deposit": knowledge_report,
        "post_archive_blockers": post_archive_blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a validated Agency task.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--closure",
        type=Path,
        help="Closure JSON; defaults to the active task closure created by complete_task.py.",
    )
    parser.add_argument("--disposition", choices=sorted(ARCHIVE_DISPOSITIONS), default="completed")
    parser.add_argument("--knowledge-candidates", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--deposit-knowledge", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.deposit_knowledge and not args.apply:
        raise ValueError("--deposit-knowledge requires --apply")
    candidates = load_candidates(args.knowledge_candidates) if args.knowledge_candidates else []
    closure_path = closure_path_for(args.project, args.task_id, args.closure)
    result = archive_task(
        args.project,
        task_id=args.task_id,
        closure=load_json(closure_path),
        disposition=args.disposition,
        candidates=candidates,
        apply=args.apply,
        deposit=args.deposit_knowledge,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    if result["status"] == "archived_with_blocker":
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Task archive failed: {exc}")
