#!/usr/bin/env python3
"""Record idempotent, event-driven progress owned by the Execution Root."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from agency_task import (
    active_task_dir,
    atomic_write_json,
    atomic_write_text,
    _transition_guarded_terminal,
    load_or_initialize_index,
    load_json,
    read_regular_text,
    render_checklist,
    safe_project_root,
    task_index_lock,
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
TERMINAL_EVENTS = frozenset({"task_completed", "task_archived"})
PUBLIC_EVENT_TYPES = EVENT_TYPES - TERMINAL_EVENTS
_TERMINAL_EVENT_AUTHORITY = object()
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
    if path.is_symlink():
        raise ValueError("progress event log must not be a symlink")
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for number, line in enumerate(read_regular_text(path).splitlines(), 1):
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
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("progress event log must not traverse a symlink")
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError("progress event log must be a regular non-symlink file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("progress event log must be a single regular file")
        with os.fdopen(descriptor, "r+", encoding="utf-8", closefd=False) as handle:
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
            os.fsync(handle.fileno())
        current = path.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise ValueError("progress event log changed while it was written")
    finally:
        os.close(descriptor)


def _optional_text_snapshot(path: Path) -> tuple[bool, str]:
    if path.is_symlink():
        raise ValueError("managed progress output must not be a symlink")
    return (True, read_regular_text(path)) if path.exists() else (False, "")


def _restore_optional_text(path: Path, snapshot: tuple[bool, str]) -> None:
    existed, text = snapshot
    if existed:
        atomic_write_text(path, text)
    elif path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("cannot remove unsafe progress output during rollback")
        path.unlink()


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
            if plan["status"] == "verifying" and before != "blocked":
                raise ValueError("new work requires executing task state; verification may only retry blocked work")
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
        elif event_type == "verification_completed":
            if before not in {"in_progress", "completed"}:
                raise ValueError("verification_completed requires in_progress or completed work")
        elif event_type == "verification_failed":
            if before not in {"in_progress", "completed"}:
                raise ValueError("verification_failed requires in_progress or completed work")
            after = "blocked"
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
    _terminal_authority: object | None = None,
    _index_lock_held: bool = False,
) -> dict[str, Any]:
    root = safe_project_root(project)
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported progress event type: {event_type}")
    if event_type in TERMINAL_EVENTS and _terminal_authority is not _TERMINAL_EVENT_AUTHORITY:
        raise ValueError(
            "terminal task events are guarded; use complete_task.py or archive_task.py"
        )
    if actor not in ROOT_ACTORS:
        raise ValueError("only the Execution Root may update global task progress")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("progress summary must be non-empty")
    artifacts = _string_list(artifacts or [], "artifacts")
    verification = _string_list(verification or [], "verification")
    blockers = _string_list(blockers or [], "blockers")
    if event_type == "verification_completed" and not verification:
        raise ValueError("verification_completed requires verification evidence")
    if event_type == "work_completed" and not verification:
        raise ValueError("work_completed requires verification evidence")
    if event_type in {"work_completed", "verification_completed"} and blockers:
        raise ValueError(f"{event_type} cannot include blockers")
    if event_type in {"verification_failed", "blocker_found"} and not blockers:
        raise ValueError(f"{event_type} requires blockers")

    if not _index_lock_held:
        with task_index_lock(root):
            return update_progress(
                root,
                task_id=task_id,
                event_type=event_type,
                work_id=work_id,
                actor=actor,
                summary=summary,
                artifacts=artifacts,
                verification=verification,
                blockers=blockers,
                idempotency_key=idempotency_key,
                _terminal_authority=_terminal_authority,
                _index_lock_held=True,
            )

    task_dir = active_task_dir(root, task_id)
    plan_path = task_dir / "task-plan.json"
    plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    original_plan = copy.deepcopy(plan)
    checklist_path = task_dir / "TASK_EXECUTION_CHECKLIST.md"
    original_checklist = read_regular_text(checklist_path)
    progress_path = task_dir / "progress.jsonl"
    progress_snapshot = _optional_text_snapshot(progress_path)
    progress_markdown_path = task_dir / "PROGRESS.md"
    progress_markdown_snapshot = _optional_text_snapshot(progress_markdown_path)
    events_before = load_events(progress_path)
    artifact_snapshots: dict[str, dict[str, object]] | None = None
    if event_type in {"work_completed", "verification_completed"} and artifacts:
        from validate_task_archive import snapshot_artifact

        artifact_snapshots = {
            artifact: snapshot_artifact(root, artifact) for artifact in artifacts
        }
    event_key = idempotency_key
    if event_type in WORK_EVENTS and work_id is not None:
        item = _work_by_id(plan, work_id)
        attempts = sum(
            event.get("work_id") == work_id and (
                event.get("event_type") == "work_started" or (
                    "event_type" not in event and event.get("status_after") == "in_progress"
                    and event.get("status_before") in {"pending", "blocked"}
                )
            )
            for event in events_before
        )
        if event_type == "work_started" and item["status"] in {"pending", "blocked"}:
            attempts += 1
        event_key = json.dumps(
            {"attempt": attempts, "key": idempotency_key, "artifacts": artifact_snapshots},
            sort_keys=True, separators=(",", ":"),
        )
    identifier = event_id_for(
        task_id=task_id,
        event_type=event_type,
        work_id=work_id,
        summary=summary.strip(),
        artifacts=artifacts,
        verification=verification,
        blockers=blockers,
        idempotency_key=event_key,
    )
    existing = next(
        (event for event in events_before if event.get("event_id") == identifier),
        None,
    )
    if existing is not None:
        return {
            "status": "duplicate",
            "event_id": identifier,
            "task_id": task_id,
            "progress_file": str(progress_path),
        }

    if event_type in WORK_EVENTS and plan["status"] not in {"executing", "verifying"}:
        raise ValueError("work progress mutations require executing task state")
    if event_type in WORK_EVENTS and plan["status"] == "verifying" and event_type not in {
        "verification_completed", "verification_failed", "work_started", "work_completed",
    }:
        raise ValueError("new artifact/blocker work requires executing task state")

    status_before, status_after = _status_for_event(plan, event_type, work_id)
    event = {
        "event_id": identifier,
        "task_id": task_id,
        "event_type": event_type,
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
    if artifact_snapshots is not None:
        event["artifact_snapshots"] = artifact_snapshots
    original_index = (
        copy.deepcopy(load_or_initialize_index(root))
        if event_type == "task_completed"
        else None
    )
    try:
        if event_type in WORK_EVENTS and work_id is not None:
            item = _work_by_id(plan, work_id)
            item["status"] = status_after
            if event_type == "verification_failed":
                # Prior success evidence belongs to the failed attempt and cannot
                # satisfy a later retry.
                item["evidence_refs"] = []
            for blocker in blockers:
                if blocker not in item["blockers"]:
                    item["blockers"].append(blocker)
            for reference in artifacts + verification:
                if reference not in item["evidence_refs"]:
                    item["evidence_refs"].append(reference)
            if event_type == "work_started" and status_before == "blocked":
                item["blockers"] = []
            atomic_write_json(plan_path, plan)
            atomic_write_text(checklist_path, render_checklist(plan))

        append_event(progress_path, event)
        if event_type == "task_completed":
            _transition_guarded_terminal(root, task_id, "completed")
            plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
        atomic_write_text(progress_markdown_path, render_progress(plan, events_before + [event]))
    except Exception as exc:
        rollback_errors: list[str] = []
        restores = [
            ("task plan", lambda: atomic_write_json(plan_path, original_plan)),
            ("checklist", lambda: atomic_write_text(checklist_path, original_checklist)),
            (
                "progress log",
                lambda: _restore_optional_text(progress_path, progress_snapshot),
            ),
            (
                "progress view",
                lambda: _restore_optional_text(
                    progress_markdown_path, progress_markdown_snapshot
                ),
            ),
        ]
        if original_index is not None:
            restores.append(
                (
                    "task index",
                    lambda: atomic_write_json(
                        root / ".agency/task-index.json", original_index
                    ),
                )
            )
        for label, restore in restores:
            try:
                restore()
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append(f"{label}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "progress update failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    return {
        "status": "recorded",
        "event_id": identifier,
        "task_id": task_id,
        "event_type": event_type,
        "status_before": status_before,
        "status_after": status_after,
        "progress_file": str(progress_path),
    }


def record_terminal_progress(
    project: Path,
    *,
    task_id: str,
    event_type: str,
    actor: str,
    summary: str,
    artifacts: list[str] | None = None,
    verification: list[str] | None = None,
    blockers: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if event_type not in TERMINAL_EVENTS:
        raise ValueError("record_terminal_progress only accepts terminal task events")
    return update_progress(
        project,
        task_id=task_id,
        event_type=event_type,
        work_id=None,
        actor=actor,
        summary=summary,
        artifacts=artifacts,
        verification=verification,
        blockers=blockers,
        idempotency_key=idempotency_key,
        _terminal_authority=_TERMINAL_EVENT_AUTHORITY,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an event-driven Agency progress update.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--event-type", required=True, choices=sorted(PUBLIC_EVENT_TYPES))
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
