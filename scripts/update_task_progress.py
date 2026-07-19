#!/usr/bin/env python3
"""Record idempotent, event-driven progress owned by the Execution Root."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any

from agency_task import (
    active_task_dir,
    atomic_write_json,
    atomic_write_text,
    load_json,
    render_checklist,
    safe_project_root,
    transition_task,
    utc_now,
    validate_task_plan,
)


EVENT_TYPES = frozenset(
    {
        "work_started",
        "work_completed",
        "artifact_generated",
        "verification_completed",
        "verification_failed",
        "blocker_found",
        "team_plan_changed",
        "review_returned",
        "task_completed",
        "task_archived",
    }
)
WORK_EVENTS = frozenset(
    {
        "work_started",
        "work_completed",
        "artifact_generated",
        "verification_completed",
        "verification_failed",
        "blocker_found",
    }
)
ROOT_ACTORS = frozenset({"execution-root", "Execution Root"})


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def event_id_for(
    *,
    task_id: str,
    event_type: str,
    work_id: str | None,
    summary: str,
    artifacts: list[str],
    verification: list[str],
    blockers: list[str],
    idempotency_key: str | None,
) -> str:
    semantic = {
        "task_id": task_id,
        "event_type": event_type,
        "work_id": work_id,
        "summary": summary,
        "artifacts": artifacts,
        "verification": verification,
        "blockers": blockers,
        "idempotency_key": idempotency_key,
    }
    digest = hashlib.sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"evt-{digest[:24]}"


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid progress event JSON on line {number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"progress event line {number} is not an object")
        result.append(value)
    return result


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing = [
            json.loads(line)
            for line in handle.read().splitlines()
            if line.strip()
        ]
        duplicate = next(
            (item for item in existing if item.get("event_id") == event["event_id"]), None
        )
        if duplicate is not None:
            comparable = dict(event)
            comparable["timestamp"] = duplicate.get("timestamp")
            if duplicate != comparable:
                raise ValueError("progress event id collides with different content")
            return
        handle.seek(0, 2)
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def _work_by_id(plan: dict[str, Any], work_id: str) -> dict[str, Any]:
    matches = [item for item in plan["work_items"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise ValueError(f"work item not found: {work_id}")
    return matches[0]


def _status_for_event(
    plan: dict[str, Any], event_type: str, work_id: str | None
) -> tuple[str, str]:
    if event_type in WORK_EVENTS:
        if work_id is None:
            raise ValueError(f"{event_type} requires work_id")
        item = _work_by_id(plan, work_id)
        before = item["status"]
        after = before
        if event_type == "work_started":
            if before not in {"pending", "blocked"}:
                raise ValueError("work_started requires pending or blocked work")
            dependencies = {
                dependency: _work_by_id(plan, dependency)["status"]
                for dependency in item["dependencies"]
            }
            incomplete = [
                dependency
                for dependency, status in dependencies.items()
                if status not in {"completed", "waived"}
            ]
            if incomplete:
                raise ValueError(
                    "work_started has incomplete dependencies: " + ", ".join(incomplete)
                )
            after = "in_progress"
        elif event_type == "work_completed":
            if before != "in_progress":
                raise ValueError("work_completed requires in_progress work")
            if item["blockers"]:
                raise ValueError("work_completed has unresolved blockers")
            after = "completed"
        elif event_type == "blocker_found":
            if before not in {"pending", "in_progress", "blocked"}:
                raise ValueError("blocker_found cannot block completed or waived work")
            after = "blocked"
        return before, after
    before = plan["status"]
    if event_type == "task_completed":
        if before != "verifying":
            raise ValueError("task_completed requires verifying task state")
        required_open = [
            item["work_id"]
            for item in plan["work_items"]
            if item.get("required", True) and item["status"] not in {"completed", "waived"}
        ]
        if required_open:
            raise ValueError("task_completed has open required work: " + ", ".join(required_open))
        if any(item["blockers"] for item in plan["work_items"]):
            raise ValueError("task_completed has unresolved blockers")
        evidence = plan.get("acceptance_evidence")
        if not isinstance(evidence, dict) or any(
            not isinstance(evidence.get(criterion), list) or not evidence[criterion]
            for criterion in plan["acceptance_criteria"]
        ):
            raise ValueError("task_completed lacks evidence for every acceptance criterion")
        return before, "completed"
    if event_type == "task_archived" and before != "completed":
        raise ValueError("task_archived progress requires completed task state")
    return before, before


def render_progress(plan: dict[str, Any], events: list[dict[str, Any]]) -> str:
    completed = [item for item in plan["work_items"] if item["status"] in {"completed", "waived"}]
    in_progress = [item for item in plan["work_items"] if item["status"] == "in_progress"]
    blocked = [item for item in plan["work_items"] if item["status"] == "blocked"]
    done_ids = {item["work_id"] for item in completed}
    next_items = [
        item
        for item in plan["work_items"]
        if item["status"] == "pending"
        and all(dependency in done_ids for dependency in item["dependencies"])
    ]
    verification_events = [
        event
        for event in events
        if event.get("verification") or event.get("status_after") in {"completed", "blocked"}
    ]

    def bullets(items: list[str]) -> list[str]:
        return [f"- {item}" for item in items] if items else ["- 无。"]

    lines = [
        f"# {plan['title']} — 进度",
        "",
        "## 当前阶段",
        "",
        f"- {plan['status']}",
        "",
        "## 已完成",
        "",
        *bullets([f"{item['work_id']} · {item['title']}" for item in completed]),
        "",
        "## 正在进行",
        "",
        *bullets([f"{item['work_id']} · {item['title']}" for item in in_progress]),
        "",
        "## 被阻塞",
        "",
        *bullets(
            [
                f"{item['work_id']} · {item['title']}：{'；'.join(item['blockers']) or '已记录阻塞'}"
                for item in blocked
            ]
        ),
        "",
        "## 下一步",
        "",
        *bullets([f"{item['work_id']} · {item['title']}" for item in next_items[:3]]),
        "",
        "## 验证状态",
        "",
        *bullets([event["summary"] for event in verification_events[-5:]]),
        "",
    ]
    return "\n".join(lines)


def update_progress(
    project: Path,
    *,
    task_id: str,
    event_type: str,
    work_id: str | None,
    actor: str,
    summary: str,
    artifacts: list[str] | None = None,
    verification: list[str] | None = None,
    blockers: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    root = safe_project_root(project)
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported progress event type: {event_type}")
    if actor not in ROOT_ACTORS:
        raise ValueError("only the Execution Root may update global task progress")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("progress summary must be non-empty")
    artifacts = _string_list(artifacts or [], "artifacts")
    verification = _string_list(verification or [], "verification")
    blockers = _string_list(blockers or [], "blockers")
    if event_type == "verification_completed" and not verification:
        raise ValueError("verification_completed requires verification evidence")
    if event_type in {"verification_failed", "blocker_found"} and not blockers:
        raise ValueError(f"{event_type} requires blockers")

    task_dir = active_task_dir(root, task_id)
    plan_path = task_dir / "task-plan.json"
    plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    progress_path = task_dir / "progress.jsonl"
    identifier = event_id_for(
        task_id=task_id,
        event_type=event_type,
        work_id=work_id,
        summary=summary.strip(),
        artifacts=artifacts,
        verification=verification,
        blockers=blockers,
        idempotency_key=idempotency_key,
    )
    existing = next(
        (event for event in load_events(progress_path) if event.get("event_id") == identifier),
        None,
    )
    if existing is not None:
        return {
            "status": "duplicate",
            "event_id": identifier,
            "task_id": task_id,
            "progress_file": str(progress_path),
        }

    status_before, status_after = _status_for_event(plan, event_type, work_id)
    if event_type in WORK_EVENTS and work_id is not None:
        item = _work_by_id(plan, work_id)
        item["status"] = status_after
        for blocker in blockers:
            if blocker not in item["blockers"]:
                item["blockers"].append(blocker)
        for reference in artifacts + verification:
            if reference not in item["evidence_refs"]:
                item["evidence_refs"].append(reference)
        if event_type == "work_started" and status_before == "blocked":
            item["blockers"] = []
        atomic_write_json(plan_path, plan)
        atomic_write_text(task_dir / "TASK_EXECUTION_CHECKLIST.md", render_checklist(plan))

    event = {
        "event_id": identifier,
        "task_id": task_id,
        "work_id": work_id,
        "timestamp": utc_now(),
        "actor": "execution-root",
        "status_before": status_before,
        "status_after": status_after,
        "summary": summary.strip(),
        "artifacts": artifacts,
        "verification": verification,
        "blockers": blockers,
    }
    append_event(progress_path, event)
    if event_type == "task_completed":
        transition_task(root, task_id, "completed")
        plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    events = load_events(progress_path)
    atomic_write_text(task_dir / "PROGRESS.md", render_progress(plan, events))
    return {
        "status": "recorded",
        "event_id": identifier,
        "task_id": task_id,
        "event_type": event_type,
        "status_before": status_before,
        "status_after": status_after,
        "progress_file": str(progress_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an event-driven Agency progress update.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--event-type", required=True, choices=sorted(EVENT_TYPES))
    parser.add_argument("--work-id")
    parser.add_argument("--actor", default="execution-root")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--verification", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--idempotency-key")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = update_progress(
        args.project,
        task_id=args.task_id,
        event_type=args.event_type,
        work_id=args.work_id,
        actor=args.actor,
        summary=args.summary,
        artifacts=args.artifact,
        verification=args.verification,
        blockers=args.blocker,
        idempotency_key=args.idempotency_key,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Task progress update failed: {exc}")
