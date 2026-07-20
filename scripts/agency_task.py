#!/usr/bin/env python3
"""Create and manage durable Agency task plans inside one project.

Discussion stays in the conversation. This module starts writing only when a
caller explicitly creates the execution checklist for a project.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
TASK_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,95}\Z")
WORK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}\Z")
TASK_STATUSES = (
    "discussion",
    "plan_ready",
    "execution_ready",
    "executing",
    "verifying",
    "completed",
    "archived",
    "cancelled",
    "superseded",
    "blocked",
)
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "discussion": frozenset({"plan_ready", "cancelled"}),
    "plan_ready": frozenset({"execution_ready", "superseded"}),
    "execution_ready": frozenset({"executing", "superseded"}),
    "executing": frozenset({"verifying", "blocked"}),
    "verifying": frozenset({"completed"}),
    "completed": frozenset({"archived"}),
    "blocked": frozenset({"executing"}),
    "archived": frozenset(),
    "cancelled": frozenset(),
    "superseded": frozenset(),
}
INACTIVE_STATUSES = frozenset({"archived", "cancelled", "superseded"})
GUARDED_TERMINAL_STATUSES = frozenset({"completed", "archived"})
WORK_TYPES = frozenset(
    {
        "research",
        "architecture",
        "implementation",
        "writing",
        "testing",
        "review",
        "integration",
        "release",
    }
)
LEVELS = frozenset({"low", "medium", "high"})
RISKS = frozenset({"low", "medium", "high", "critical"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_project_root(raw: Path) -> Path:
    root = raw.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project root is not a directory: {root}")
    return root


def generate_task_id(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ").lower()
    return f"task-{stamp}-{uuid.uuid4().hex[:10]}"


def require_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"unsafe task id: {task_id!r}")
    return task_id


def read_regular_text(path: Path) -> str:
    """Read one stable, single-link regular file without following a symlink."""
    candidate = path.absolute()
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise ValueError(f"managed input must be a regular non-symlink file: {candidate}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"managed input must be a single regular file: {candidate}")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            text = handle.read()
        current = candidate.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise ValueError(f"managed input changed while it was read: {candidate}")
        return text
    except UnicodeError as exc:
        raise ValueError(f"managed input must be UTF-8: {candidate}") from exc
    finally:
        os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(read_regular_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"refusing managed write through symlink: {path}")
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _require_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _require_scope_list(value: object, label: str) -> list[str]:
    result = _require_string_list(value, label)
    for item in result:
        candidate = Path(item)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"{label} must contain project-relative safe paths")
    return result


def validate_work_items(work_items: object) -> list[dict[str, Any]]:
    if not isinstance(work_items, list):
        raise ValueError("work_items must be a list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    required = {"work_id", "title", "outcome", "work_type"}
    for index, raw in enumerate(work_items):
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise ValueError(f"work item {index} is missing required fields")
        item = {
            "dependencies": [],
            "read_scope": [],
            "write_scope": [],
            "verification": [],
            "risk": "medium",
            "uncertainty": "medium",
            "context_coupling": "high",
            "parallelizable": False,
            "isolated_worktree_required": False,
            "accountable_position": "",
            "profile": None,
            "review_profile": None,
            "status": "pending",
            "evidence_refs": [],
            "blockers": [],
            "required": True,
            **raw,
        }
        work_id = item["work_id"]
        if not isinstance(work_id, str) or not WORK_ID_RE.fullmatch(work_id):
            raise ValueError(f"invalid work_id: {work_id!r}")
        if work_id in seen:
            raise ValueError(f"duplicate work_id: {work_id}")
        seen.add(work_id)
        for key in ("title", "outcome"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"{work_id}.{key} must be non-empty")
        if item["work_type"] not in WORK_TYPES:
            raise ValueError(f"{work_id}.work_type is invalid")
        item["dependencies"] = _require_string_list(item["dependencies"], f"{work_id}.dependencies")
        item["read_scope"] = _require_scope_list(item["read_scope"], f"{work_id}.read_scope")
        item["write_scope"] = _require_scope_list(item["write_scope"], f"{work_id}.write_scope")
        item["verification"] = _require_string_list(item["verification"], f"{work_id}.verification")
        item["evidence_refs"] = _require_string_list(item["evidence_refs"], f"{work_id}.evidence_refs")
        item["blockers"] = _require_string_list(item["blockers"], f"{work_id}.blockers")
        if item["risk"] not in RISKS:
            raise ValueError(f"{work_id}.risk is invalid")
        if item["uncertainty"] not in LEVELS or item["context_coupling"] not in LEVELS:
            raise ValueError(f"{work_id} uncertainty/context_coupling is invalid")
        for key in ("parallelizable", "isolated_worktree_required"):
            if type(item[key]) is not bool:
                raise ValueError(f"{work_id}.{key} must be boolean")
        for key in ("accountable_position", "profile", "review_profile"):
            if item[key] is not None and not isinstance(item[key], str):
                raise ValueError(f"{work_id}.{key} must be a string or null")
        if item["status"] not in {"pending", "in_progress", "completed", "blocked", "waived"}:
            raise ValueError(f"{work_id}.status is invalid")
        if "required" in item and type(item["required"]) is not bool:
            raise ValueError(f"{work_id}.required must be boolean")
        if "waiver_reason" in item:
            if not isinstance(item["waiver_reason"], str) or not item["waiver_reason"].strip():
                raise ValueError(f"{work_id}.waiver_reason must be a non-empty string")
            item["waiver_reason"] = item["waiver_reason"].strip()
        normalized.append(item)

    graph = {item["work_id"]: item["dependencies"] for item in normalized}
    for work_id, dependencies in graph.items():
        missing = [dependency for dependency in dependencies if dependency not in graph]
        if missing:
            raise ValueError(f"{work_id} has unknown dependencies: {', '.join(missing)}")
        if work_id in dependencies:
            raise ValueError(f"{work_id} cannot depend on itself")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(work_id: str) -> None:
        if work_id in visiting:
            raise ValueError("work item dependency cycle detected")
        if work_id in visited:
            return
        visiting.add(work_id)
        for dependency in graph[work_id]:
            visit(dependency)
        visiting.remove(work_id)
        visited.add(work_id)

    for work_id in graph:
        visit(work_id)
    return normalized


def validate_task_plan(plan: object, *, expected_task_id: str | None = None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("task plan must be an object")
    required = {
        "title",
        "objective",
        "source_discussion",
        "acceptance_criteria",
        "work_items",
    }
    if not required.issubset(plan):
        raise ValueError("task plan is missing required fields")
    result = dict(plan)
    result.setdefault("schema_version", SCHEMA_VERSION)
    if "task_id" not in result:
        result["task_id"] = expected_task_id or generate_task_id()
    result.setdefault("out_of_scope", [])
    result.setdefault("status", "plan_ready")
    if result["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported task plan schema_version")
    task_id = require_task_id(result["task_id"])
    if expected_task_id is not None and task_id != expected_task_id:
        raise ValueError("task plan id does not match its directory")
    for key in ("title", "objective"):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f"task plan {key} must be non-empty")
    discussion = result["source_discussion"]
    allowed_discussion_fields = {
        "summary",
        "accepted_decisions",
        "constraints",
        "assumptions",
        "open_questions",
    }
    if not isinstance(discussion, dict) or not set(discussion).issubset(
        allowed_discussion_fields
    ):
        raise ValueError("source_discussion fields are invalid")
    if "summary" not in discussion:
        raise ValueError("source_discussion.summary must be non-empty")
    discussion = dict(discussion)
    for key in ("accepted_decisions", "constraints", "assumptions", "open_questions"):
        discussion.setdefault(key, [])
    if not isinstance(discussion["summary"], str) or not discussion["summary"].strip():
        raise ValueError("source_discussion.summary must be non-empty")
    for key in ("accepted_decisions", "constraints", "assumptions", "open_questions"):
        discussion[key] = _require_string_list(discussion[key], f"source_discussion.{key}")
    result["source_discussion"] = discussion
    result["acceptance_criteria"] = _require_string_list(
        result["acceptance_criteria"], "acceptance_criteria"
    )
    if not result["acceptance_criteria"]:
        raise ValueError("acceptance_criteria must not be empty")
    result["out_of_scope"] = _require_string_list(result["out_of_scope"], "out_of_scope")
    if "execution_model_request" in result:
        model = result["execution_model_request"]
        if not isinstance(model, dict) or set(model) != {
            "display_request",
            "reasoning_request",
            "resolved_model_id",
            "resolution_status",
        }:
            raise ValueError("execution_model_request fields are invalid")
        if model["display_request"] != "GPT-5.6 Sol" or model["reasoning_request"] != "ultra":
            raise ValueError("execution model request must default to GPT-5.6 Sol ultra")
        if model["resolved_model_id"] is not None and not isinstance(
            model["resolved_model_id"], str
        ):
            raise ValueError("resolved_model_id must be a string or null")
        if model["resolution_status"] not in {
            "pending",
            "resolved",
            "user_choice_required",
            "unavailable",
            "readback_mismatch",
        }:
            raise ValueError("execution model resolution_status is invalid")
    if "acceptance_evidence" in result:
        evidence = result["acceptance_evidence"]
        if not isinstance(evidence, dict):
            raise ValueError("acceptance_evidence must be an object")
        result["acceptance_evidence"] = {
            criterion.strip(): _require_string_list(
                references, f"acceptance_evidence.{criterion}"
            )
            for criterion, references in evidence.items()
            if isinstance(criterion, str) and criterion.strip()
        }
        if len(result["acceptance_evidence"]) != len(evidence):
            raise ValueError("acceptance_evidence keys must be non-empty strings")
    result["work_items"] = validate_work_items(result["work_items"])
    if result["status"] not in TASK_STATUSES:
        raise ValueError("task plan status is invalid")
    return result


def validate_transition(status_before: str, status_after: str) -> None:
    if status_before not in LEGAL_TRANSITIONS or status_after not in TASK_STATUSES:
        raise ValueError("unknown task lifecycle status")
    if status_after not in LEGAL_TRANSITIONS[status_before]:
        raise ValueError(f"illegal task transition: {status_before} -> {status_after}")


def agency_paths(project: Path) -> tuple[Path, Path, Path]:
    project_root = safe_project_root(project)
    paths = (
        project_root / ".agency",
        project_root / ".agency" / "tasks",
        project_root / ".agency" / "tasks" / "active",
        project_root / ".agency" / "tasks" / "archive",
    )
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"Agency managed path must not be a symlink: {path}")
        if path.exists() and not path.is_dir():
            raise ValueError(f"Agency managed path must be a directory: {path}")
        if path.exists() and not path.resolve().is_relative_to(project_root):
            raise ValueError(f"Agency managed path escapes project: {path}")
    return paths[0], paths[2], paths[3]


def load_or_initialize_index(project: Path) -> dict[str, Any]:
    agency_root, _, _ = agency_paths(project)
    path = agency_root / "task-index.json"
    if path.is_symlink():
        raise ValueError("task index must not be a symlink")
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "tasks": {},
            "active_task_ids": [],
            "archived_task_ids": [],
        }
    value = load_json(path)
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported task index schema_version")
    if not isinstance(value.get("tasks"), dict):
        raise ValueError("task index tasks must be an object")
    for key in ("active_task_ids", "archived_task_ids"):
        _require_string_list(value.get(key), f"task index {key}")
    return value


def write_index(project: Path, index: dict[str, Any]) -> None:
    agency_root, _, _ = agency_paths(project)
    index["updated_at"] = utc_now()
    atomic_write_json(agency_root / "task-index.json", index)


def _restore_index_snapshot(
    project: Path, index: dict[str, Any], *, existed: bool
) -> None:
    agency_root, _, _ = agency_paths(project)
    path = agency_root / "task-index.json"
    if existed:
        atomic_write_json(path, index)
    elif path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError("cannot remove unsafe task index during rollback")
        path.unlink()


def _remove_created_task_dir(task_dir: Path) -> None:
    if not task_dir.exists():
        return
    if task_dir.is_symlink() or not task_dir.is_dir():
        raise ValueError("cannot roll back an unsafe task directory")
    for child in sorted(task_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        info = child.lstat()
        if stat.S_ISDIR(info.st_mode):
            child.rmdir()
        else:
            child.unlink()
    task_dir.rmdir()


def task_relative_path(task_id: str) -> str:
    return f".agency/tasks/active/{require_task_id(task_id)}"


def _checklist_mark(status: str) -> str:
    if status in {"completed", "waived"}:
        return "x"
    return " "


def render_checklist(plan: dict[str, Any]) -> str:
    lines = [
        f"# {plan['title']} — 任务执行清单",
        "",
        f"- 任务 ID：{plan['task_id']}",
        f"- 当前状态：{plan['status']}",
        f"- 目标：{plan['objective']}",
        "",
        "## 完成标准",
        "",
    ]
    lines.extend(f"- [ ] {criterion}" for criterion in plan["acceptance_criteria"])
    lines.extend(["", "## 工作项", ""])
    for item in plan["work_items"]:
        dependencies = "、".join(item["dependencies"]) if item["dependencies"] else "无"
        verification = "；".join(item["verification"]) or "未定义"
        lines.extend(
            [
                f"### [{_checklist_mark(item['status'])}] {item['work_id']} · {item['title']}",
                "",
                f"- 状态：{item['status']}",
                f"- 结果：{item['outcome']}",
                f"- 依赖：{dependencies}",
                f"- 完成验证：{verification}",
                "",
            ]
        )
    lines.extend(
        [
            "## 执行边界",
            "",
            "本清单创建后不会自动开始执行。只有明确启动阶段三时才准备执行会话和项目级 Profile。",
            "",
        ]
    )
    return "\n".join(lines)


def create_task(project: Path, raw_plan: dict[str, Any]) -> dict[str, Any]:
    root = safe_project_root(project)
    plan = dict(raw_plan)
    plan["task_id"] = plan.get("task_id") or generate_task_id()
    plan.setdefault("schema_version", SCHEMA_VERSION)
    plan.setdefault("status", "plan_ready")
    if plan["status"] != "plan_ready":
        raise ValueError("new persisted execution checklists must start at plan_ready")
    normalized = validate_task_plan(plan)
    _, active_root, _ = agency_paths(root)
    task_dir = active_root / normalized["task_id"]
    if task_dir.exists():
        raise ValueError(f"task already exists: {normalized['task_id']}")
    agency_root, _, _ = agency_paths(root)
    index_path = agency_root / "task-index.json"
    index_existed = index_path.exists()
    index = load_or_initialize_index(root)
    original_index = copy.deepcopy(index)
    if normalized["task_id"] in index["tasks"]:
        raise ValueError(f"task id already exists in index: {normalized['task_id']}")

    task_dir.mkdir(parents=True, exist_ok=False)
    try:
        atomic_write_json(task_dir / "task-plan.json", normalized)
        atomic_write_text(task_dir / "TASK_EXECUTION_CHECKLIST.md", render_checklist(normalized))
        created_at = utc_now()
        index["tasks"][normalized["task_id"]] = {
            "title": normalized["title"],
            "status": "plan_ready",
            "path": task_relative_path(normalized["task_id"]),
            "created_at": created_at,
            "updated_at": created_at,
            "superseded_by": None,
        }
        index["active_task_ids"] = [
            item for item in index["active_task_ids"] if item != normalized["task_id"]
        ] + [normalized["task_id"]]
        write_index(root, index)
    except Exception as exc:
        rollback_errors: list[str] = []
        try:
            _restore_index_snapshot(root, original_index, existed=index_existed)
        except (OSError, ValueError) as rollback_exc:
            rollback_errors.append(f"index: {rollback_exc}")
        try:
            _remove_created_task_dir(task_dir)
        except (OSError, ValueError) as rollback_exc:
            rollback_errors.append(f"task directory: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "task creation failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    return {
        "status": "created",
        "lifecycle_phase": "plan_ready",
        "task_id": normalized["task_id"],
        "task_dir": str(task_dir),
        "execution_started": False,
    }


def active_task_dir(project: Path, task_id: str) -> Path:
    _, active_root, _ = agency_paths(project)
    path = active_root / require_task_id(task_id)
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"active task not found: {task_id}")
    return path


def _transition_task(
    project: Path,
    task_id: str,
    status_after: str,
    *,
    reason: str | None = None,
    superseded_by: str | None = None,
) -> dict[str, Any]:
    root = safe_project_root(project)
    task_dir = active_task_dir(root, task_id)
    plan_path = task_dir / "task-plan.json"
    checklist_path = task_dir / "TASK_EXECUTION_CHECKLIST.md"
    plan = validate_task_plan(load_json(plan_path), expected_task_id=task_id)
    original_plan = copy.deepcopy(plan)
    original_checklist = read_regular_text(checklist_path)
    status_before = plan["status"]
    validate_transition(status_before, status_after)
    if status_after == "superseded":
        if superseded_by is None:
            raise ValueError("superseded transition requires superseded_by")
        require_task_id(superseded_by)
        if superseded_by == task_id:
            raise ValueError("a task cannot supersede itself")
    elif superseded_by is not None:
        raise ValueError("superseded_by is only valid for superseded transitions")
    index = load_or_initialize_index(root)
    original_index = copy.deepcopy(index)
    entry = index["tasks"].get(task_id)
    if not isinstance(entry, dict):
        raise ValueError("task is missing from task index")
    if entry.get("status") != status_before or task_id not in index["active_task_ids"]:
        raise ValueError("task plan and task index status are inconsistent")

    plan["status"] = status_after
    if reason:
        plan["status_reason"] = reason
    entry["status"] = status_after
    entry["updated_at"] = utc_now()
    entry["superseded_by"] = superseded_by
    if status_after in INACTIVE_STATUSES:
        index["active_task_ids"] = [item for item in index["active_task_ids"] if item != task_id]
    elif task_id not in index["active_task_ids"]:
        index["active_task_ids"].append(task_id)
    try:
        atomic_write_json(plan_path, plan)
        atomic_write_text(checklist_path, render_checklist(plan))
        write_index(root, index)
    except Exception as exc:
        rollback_errors: list[str] = []
        for label, restore in (
            ("task plan", lambda: atomic_write_json(plan_path, original_plan)),
            ("checklist", lambda: atomic_write_text(checklist_path, original_checklist)),
            (
                "task index",
                lambda: _restore_index_snapshot(root, original_index, existed=True),
            ),
        ):
            try:
                restore()
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append(f"{label}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "task transition failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    return {
        "task_id": task_id,
        "status_before": status_before,
        "status_after": status_after,
        "active": status_after not in INACTIVE_STATUSES,
    }


def transition_task(
    project: Path,
    task_id: str,
    status_after: str,
    *,
    reason: str | None = None,
    superseded_by: str | None = None,
) -> dict[str, Any]:
    if status_after in GUARDED_TERMINAL_STATUSES:
        command = "complete_task.py" if status_after == "completed" else "archive_task.py"
        raise ValueError(f"{status_after} is guarded; use {command}")
    return _transition_task(
        project,
        task_id,
        status_after,
        reason=reason,
        superseded_by=superseded_by,
    )


def _transition_guarded_terminal(
    project: Path, task_id: str, status_after: str
) -> dict[str, Any]:
    if status_after not in GUARDED_TERMINAL_STATUSES:
        raise ValueError("internal terminal transition only accepts completed or archived")
    return _transition_task(project, task_id, status_after)


def list_active_tasks(project: Path) -> list[dict[str, Any]]:
    index = load_or_initialize_index(project)
    result: list[dict[str, Any]] = []
    for task_id in index["active_task_ids"]:
        entry = index["tasks"].get(task_id)
        if isinstance(entry, dict) and entry.get("status") not in INACTIVE_STATUSES:
            result.append({"task_id": task_id, **entry})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage durable project Agency tasks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a plan_ready execution checklist.")
    create.add_argument("--project", type=Path, default=Path.cwd())
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--json", action="store_true")

    transition = subparsers.add_parser("transition", help="Apply one legal lifecycle transition.")
    transition.add_argument("--project", type=Path, default=Path.cwd())
    transition.add_argument("--task-id", required=True)
    transition.add_argument(
        "--to",
        required=True,
        choices=tuple(status for status in TASK_STATUSES if status not in GUARDED_TERMINAL_STATUSES),
    )
    transition.add_argument("--reason")
    transition.add_argument("--superseded-by")
    transition.add_argument("--json", action="store_true")

    listing = subparsers.add_parser("list", help="List active tasks from the project index.")
    listing.add_argument("--project", type=Path, default=Path.cwd())
    listing.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "create":
        result: object = create_task(args.project, load_json(args.input))
    elif args.command == "transition":
        result = transition_task(
            args.project,
            args.task_id,
            args.to,
            reason=args.reason,
            superseded_by=args.superseded_by,
        )
    else:
        result = {"active_tasks": list_active_tasks(args.project)}
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Agency task error: {exc}")
