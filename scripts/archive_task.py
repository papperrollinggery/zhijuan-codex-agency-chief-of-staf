#!/usr/bin/env python3
"""Archive a completed, cancelled, or superseded Agency task after validation."""

from __future__ import annotations

import argparse
import copy
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
from deposit_knowledge import deposit_knowledge, load_candidates, validate_knowledge_candidates
from update_task_progress import event_id_for, update_progress
from validate_task_archive import (
    ARCHIVE_DISPOSITIONS,
    sha256,
    validate_archive_directory,
    validate_archive_readiness,
)


def archive_relative_path(task_id: str, moment: datetime) -> str:
    return f".agency/tasks/archive/{moment:%Y}/{moment:%m}/{task_id}"


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
        if not path.is_file() or path.name == "archive-manifest.json":
            continue
        if path.is_symlink():
            raise ValueError(f"task archive contains a symlink: {path.relative_to(task_dir)}")
        result.append(
            {
                "path": str(path.relative_to(task_dir)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return result


def _record_noncompleted_archive_event(task_dir: Path, plan: dict[str, Any]) -> None:
    from update_task_progress import append_event, load_events, render_progress

    summary = f"Task archived with disposition {plan['status']}"
    identifier = event_id_for(
        task_id=plan["task_id"],
        event_type="task_archived",
        work_id=None,
        summary=summary,
        artifacts=[],
        verification=[],
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
            "status_after": plan["status"],
            "summary": summary,
            "artifacts": [],
            "verification": [],
            "blockers": [],
        },
    )
    atomic_write_text(
        task_dir / "PROGRESS.md",
        render_progress(plan, load_events(task_dir / "progress.jsonl")),
    )


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
    original_plan = copy.deepcopy(plan)
    index = load_or_initialize_index(root)
    original_index = copy.deepcopy(index)
    if task_id not in index["tasks"]:
        raise ValueError("task is missing from task index")

    atomic_write_json(task_dir / "knowledge-candidates.json", normalized_candidates)
    atomic_write_text(
        task_dir / "ARCHIVE_REPORT.md",
        render_archive_report(plan, readiness, len(normalized_candidates), archived_at),
    )
    if disposition == "completed":
        update_progress(
            root,
            task_id=task_id,
            event_type="task_archived",
            work_id=None,
            actor="execution-root",
            summary="Task archive preconditions verified",
            verification=["archive readiness validated"],
            idempotency_key="archive",
        )
        validate_transition("completed", "archived")
        plan = validate_task_plan(load_json(task_dir / "task-plan.json"), expected_task_id=task_id)
        plan["status"] = "archived"
        atomic_write_json(task_dir / "task-plan.json", plan)
        atomic_write_text(task_dir / "TASK_EXECUTION_CHECKLIST.md", render_checklist(plan))
        from update_task_progress import load_events, render_progress

        atomic_write_text(
            task_dir / "PROGRESS.md",
            render_progress(plan, load_events(task_dir / "progress.jsonl")),
        )
        final_status = "archived"
    else:
        _record_noncompleted_archive_event(task_dir, plan)
        final_status = disposition

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "archive_disposition": disposition,
        "source_status": original_plan["status"],
        "final_status": final_status,
        "archived_at": archived_at,
        "closure": readiness["closure"],
        "acceptance_evidence": plan.get("acceptance_evidence", {}),
        "artifacts": readiness["artifact_paths"],
        "files": _manifest_files(task_dir),
    }
    atomic_write_json(task_dir / "archive-manifest.json", manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    moved = False
    try:
        task_dir.rename(destination)
        moved = True
        entry = index["tasks"][task_id]
        entry["status"] = final_status
        entry["path"] = relative
        entry["updated_at"] = archived_at
        entry["archived_at"] = archived_at
        entry["archive_disposition"] = disposition
        index["active_task_ids"] = [value for value in index["active_task_ids"] if value != task_id]
        if task_id not in index["archived_task_ids"]:
            index["archived_task_ids"].append(task_id)
        write_index(root, index)
    except Exception:
        if moved and destination.exists() and not task_dir.exists():
            destination.rename(task_dir)
        atomic_write_json(task_dir / "task-plan.json", original_plan)
        write_index(root, original_index)
        raise

    archive_validation = validate_archive_directory(destination)
    knowledge_report: dict[str, Any] | None = None
    if deposit and normalized_candidates:
        knowledge_report = deposit_knowledge(
            root,
            destination / "knowledge-candidates.json",
            apply=True,
            report_path=destination / "knowledge-deposit-report.json",
        )
    return {
        "status": "archived",
        "task_id": task_id,
        "disposition": disposition,
        "destination": str(destination),
        "archive_validation": archive_validation,
        "knowledge_candidates": len(normalized_candidates),
        "knowledge_deposit": knowledge_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a validated Agency task.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--disposition", choices=sorted(ARCHIVE_DISPOSITIONS), default="completed")
    parser.add_argument("--knowledge-candidates", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--deposit-knowledge", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.deposit_knowledge and not args.apply:
        raise ValueError("--deposit-knowledge requires --apply")
    candidates = load_candidates(args.knowledge_candidates) if args.knowledge_candidates else []
    result = archive_task(
        args.project,
        task_id=args.task_id,
        closure=load_json(args.closure),
        disposition=args.disposition,
        candidates=candidates,
        apply=args.apply,
        deposit=args.deposit_knowledge,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Task archive failed: {exc}")
