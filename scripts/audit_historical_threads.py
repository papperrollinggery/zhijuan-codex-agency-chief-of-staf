#!/usr/bin/env python3
"""Audit local Codex thread history for Chief-of-Staff skill failure modes."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_TERMS = [
    "agency-chief-of-staff",
    "zhijuan-codex-agency-chief-of-staf",
    "codex-agency-chief-of-staf",
    "COS_BOOT_RECEIPT",
    "THREAD_DISPATCH_RECEIPT",
    "幕僚长",
    "Chief of Staff",
]

REAL_THREAD_TERMS = [
    "真实 Codex task",
    "真实 Codex thread",
    "真实 Codex Threads",
    "独立 sidebar 任务",
    "隔离 worktree",
    "另一个 Codex 线程",
    "新 Codex 线程",
    "thread id",
    "task id",
]

HISTORY_AUDIT_CHALLENGES = [
    "线程没归档",
    "没有归档",
    "没真实执行",
    "没有真实执行",
    "没按 Skill 跑",
    "没有按 Skill 跑",
    "为什么都没有合并或者或者归档",
    "你还是自己在执行",
    "没安排别的线程",
]

MISSING_CWD_TERMS = [
    "当前工作目录缺失",
    "工作目录缺失",
    "current working directory missing",
    "cwd_missing",
    "worktree_missing",
    "thread_cwd_missing",
    "cwd no longer exists",
    "worktree no longer exists",
]

AUTOMATION_LIFECYCLE_TERMS = [
    "heartbeat",
    "automation",
    "自动化",
    "心跳",
    "due_now",
    "overdue",
    "automation_goal_status: complete",
    "automation_complete: true",
    "目标已完成",
]

DUE_STATUS_RE = re.compile(
    r"(?:current_due_status|due_status)\s*:\s*"
    r"(NOT_DUE|DUE_NOW|OVERDUE|未到期)(?![\w-])",
    flags=re.IGNORECASE,
)

NATURAL_TEST_GIVEAWAY_TERMS = [
    "请派发 worker",
    "派发 worker",
    "worker thread",
    "thread id",
    "receipt",
    "cleanup",
    "COS_BOOT_RECEIPT",
    "THREAD_DISPATCH_RECEIPT",
    "$agency-chief-of-staff",
    "$zhijuan-codex-agency-chief-of-staf",
    "幕僚长",
    "真实 Codex Threads",
    "完整团队",
]


def read_text(path: Path, max_bytes: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="ignore")


def contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def latest_due_status(text: str) -> str | None:
    matches = DUE_STATUS_RE.findall(text)
    if not matches:
        return None
    value = matches[-1]
    return value if value == "未到期" else value.upper()


def has_current_work_receipt(text: str) -> bool:
    if "WORK_RECEIPT" not in text:
        return False
    kind = re.search(r"worker_kind:\s*(codex_task|codex_thread)\b", text)
    worker_id = re.search(r"worker_id:\s*['\"]?([^\s'\"]+)", text)
    if not kind or not worker_id:
        return False
    return worker_id.group(1).lower() not in {
        "",
        "pending",
        "unknown",
        "same-thread",
        "none",
        "null",
    }


def normalize_thread(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id", "")),
        "cwd": str(row.get("cwd", "")),
        "title": str(row.get("title", "")),
        "first_user_message": str(row.get("first_user_message", "")),
        "preview": str(row.get("preview", "")),
        "rollout_path": str(row.get("rollout_path", "")),
        "archived": int(row.get("archived", 0) or 0),
        "rollout_text": str(row.get("rollout_text", "")),
    }


def load_fixture(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("fixture must be a JSON array")
    return [normalize_thread(item) for item in data]


def load_live(codex_home: Path, scan_rollouts: bool, max_bytes: int) -> list[dict[str, Any]]:
    db = codex_home / "state_5.sqlite"
    if not db.exists():
        raise SystemExit(f"missing Codex state DB: {db}")
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        select id, cwd, title, first_user_message, preview, rollout_path, archived
        from threads
        order by created_at
        """
    ).fetchall()
    threads: list[dict[str, Any]] = []
    for row in rows:
        item = normalize_thread(dict(row))
        metadata = " ".join(
            [item["id"], item["cwd"], item["title"], item["first_user_message"], item["preview"]]
        )
        rollout_text = ""
        if scan_rollouts or contains_any(metadata, SKILL_TERMS):
            rollout_text = read_text(Path(item["rollout_path"]), max_bytes)
        item["rollout_text"] = rollout_text
        if contains_any(metadata + "\n" + rollout_text, SKILL_TERMS):
            threads.append(item)
    return threads


def classify(thread: dict[str, Any], repo_root: Path) -> tuple[list[str], dict[str, bool]]:
    text = "\n".join(
        [
            thread["cwd"],
            thread["title"],
            thread["first_user_message"],
            thread["preview"],
            thread.get("rollout_text", ""),
        ]
    )
    first_visible = "\n".join(
        [thread["title"], thread["first_user_message"], thread["preview"]]
    )
    explicit_trigger = contains_any(first_visible, SKILL_TERMS)
    real_thread_requested = contains_any(first_visible, REAL_THREAD_TERMS)
    has_boot = "COS_BOOT_RECEIPT" in text
    has_legacy_dispatch = "THREAD_DISPATCH_RECEIPT" in text
    has_work_receipt = has_current_work_receipt(text)
    has_dispatch = has_legacy_dispatch or has_work_receipt
    has_tool_blocked = "TOOL_BLOCKED" in text
    categories: list[str] = []
    cwd_path = Path(thread["cwd"]).expanduser() if thread["cwd"] else None
    cwd_exists = bool(cwd_path and cwd_path.exists())

    if explicit_trigger and not has_boot:
        categories.append("activation_missing_or_unproven")
    if real_thread_requested and not (has_dispatch or has_tool_blocked):
        categories.append("dispatch_missing_or_unproven")
    if "pendingWorktreeId" in text:
        categories.append("pending_worktree_not_thread_id")
    if "thread_not_converged" in text:
        categories.append("nonconverged_evidence_must_be_rejected")
    if contains_any(text, ["set_thread_title", "title_update_blocked", "dispatcher_set", "self_set"]):
        categories.append("title_receipt_metadata_requires_readback")
    if contains_any(text, AUTOMATION_LIFECYCLE_TERMS):
        current_due_status = latest_due_status(text)
        not_due_claim = current_due_status in {"NOT_DUE", "未到期"}
        has_run_receipt = "HEARTBEAT_RUN_RECEIPT" in text or "COS_HEARTBEAT_RUN_RECEIPT" in text
        has_dispatch_outcome = "dispatch_outcome:" in text
        has_self_recycle = "self_recycle_status:" in text
        complete_claim = contains_any(
            text,
            [
                "automation_goal_status: complete",
                "automation_complete: true",
                "目标已完成",
                "automation lifecycle complete",
                "自动化已完成",
            ],
        )
        complete_has_recycle = re.search(r"self_recycle_status:\s*(deleted|paused)", text)
        due_claim = current_due_status in {"DUE_NOW", "OVERDUE"} or contains_any(
            text, ["due_now", "overdue", "到期", "已到期"]
        )
        due_has_action = has_work_receipt or contains_any(
            text,
            [
                "dispatch_outcome: dispatched",
                "dispatch_outcome: dispatch_pending",
                "dispatch_outcome: tool_blocked",
                "dispatch_outcome: thread_not_converged",
                "TOOL_BLOCKED",
                "THREAD_DISPATCH_RECEIPT",
            ],
        )
        if not not_due_claim and (
            not has_run_receipt
            or not has_dispatch_outcome
            or not has_self_recycle
            or (complete_claim and not complete_has_recycle)
            or (due_claim and not due_has_action)
        ):
            categories.append("automation_lifecycle_missing_evidence")
    if contains_any(first_visible, ["自然测试", "自然业务测试", "blackbox", "黑盒"]) and contains_any(
        first_visible + "\n" + text,
        NATURAL_TEST_GIVEAWAY_TERMS,
    ):
        categories.append("natural_test_prompt_overdisclosure")
    if contains_any(text, HISTORY_AUDIT_CHALLENGES) and not contains_any(
        text,
        [
            "HISTORICAL_THREAD_AUDIT_RECEIPT",
            "audit_historical_threads.py",
            "历史线程审计",
        ],
    ):
        categories.append("history_audit_not_triggered")

    try:
        in_repo = Path(thread["cwd"]).resolve().is_relative_to(repo_root.resolve())
    except Exception:
        in_repo = False
    if thread["cwd"] and (
        not cwd_exists
        or contains_any(text, MISSING_CWD_TERMS)
    ):
        categories.append("thread_cwd_missing_requires_archive_or_rehome")
    if thread["cwd"] and not in_repo:
        categories.append("cross_project_context_requires_readback")

    markers = {
        "explicit_trigger": explicit_trigger,
        "real_thread_requested": real_thread_requested,
        "has_boot_receipt_marker": has_boot,
        "has_dispatch_receipt_marker": has_dispatch,
        "has_current_work_receipt": has_work_receipt,
        "has_legacy_dispatch_receipt": has_legacy_dispatch,
        "has_tool_blocked_marker": has_tool_blocked,
        "cwd_exists": cwd_exists,
    }
    return sorted(set(categories)), markers


def cleanup_status_for(thread: dict[str, Any], categories: list[str], repo_root: Path) -> dict[str, Any]:
    """Return audit-only cleanup guidance; this script never deletes files or kills processes."""
    try:
        in_repo = Path(thread["cwd"]).resolve().is_relative_to(repo_root.resolve())
    except Exception:
        in_repo = False

    if "thread_cwd_missing_requires_archive_or_rehome" in categories:
        cwd_path = Path(thread["cwd"]).expanduser() if thread["cwd"] else None
        cwd_exists = bool(cwd_path and cwd_path.exists())
        if cwd_exists:
            status = "cleanup_blocked_readback_required"
            action = "verify_thread_metadata_before_archive_or_cleanup"
        elif thread["archived"]:
            status = "no_action_already_archived"
            action = "none"
        else:
            status = "cleanup_candidate_archive_thread_only"
            action = "archive_or_mark_cleanup_blocked_after_readback"
        return {
            "status": status,
            "safe_action": action,
            "delete_files_allowed": False,
            "kill_process_allowed": False,
            "rule": (
                "Missing-cwd workers are rejected evidence. Archive the thread or record cleanup_blocked; "
                "do not delete worktrees from this audit."
            ),
        }

    if "cross_project_context_requires_readback" in categories and not in_repo:
        return {
            "status": "cleanup_blocked_target_project_scope_required",
            "safe_action": "rehome_or_dispatch_in_target_project",
            "delete_files_allowed": False,
            "kill_process_allowed": False,
            "rule": "Cross-project entries require target-project adoption; source COS cannot clean them.",
        }

    return {
        "status": "no_cleanup_candidate",
        "safe_action": "none",
        "delete_files_allowed": False,
        "kill_process_allowed": False,
        "rule": "No stale worktree/process/cache cleanup candidate was established by this audit.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit local Codex history for COS skill activation and ThreadOps issues."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    parser.add_argument("--fixture", type=Path, help="Use fixture JSON instead of live Codex DB.")
    parser.add_argument("--scan-rollouts", action="store_true", help="Scan rollout JSONL text.")
    parser.add_argument("--max-rollout-bytes", type=int, default=2_000_000)
    parser.add_argument("--output", type=Path, help="Write receipt JSON.")
    parser.add_argument("--include-titles", action="store_true", help="Include thread titles in output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if args.fixture:
        threads = load_fixture(args.fixture)
        source = str(args.fixture)
    else:
        threads = load_live(Path(args.codex_home), args.scan_rollouts, args.max_rollout_bytes)
        source = str(Path(args.codex_home) / "state_5.sqlite")

    category_counts: Counter[str] = Counter()
    cwd_counts: Counter[str] = Counter()
    audited = []
    cleanup_counts: Counter[str] = Counter()
    for thread in threads:
        categories, markers = classify(thread, repo_root)
        cleanup_status = cleanup_status_for(thread, categories, repo_root)
        category_counts.update(categories)
        cleanup_counts.update([cleanup_status["status"]])
        cwd_counts.update([thread["cwd"] or "(unknown)"])
        entry = {
            "thread_id": thread["id"],
            "cwd": thread["cwd"],
            "archived": bool(thread["archived"]),
            "categories": categories,
            "markers": markers,
            "cleanup_status": cleanup_status,
        }
        if args.include_titles:
            entry["title"] = thread["title"][:160]
        audited.append(entry)

    receipt = {
        "receipt_type": "HISTORICAL_THREAD_AUDIT_RECEIPT",
        "status": "valid",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "repo_root": str(repo_root),
        "scan_rollouts": bool(args.scan_rollouts),
        "summary": {
            "matching_threads": len(threads),
            "cross_project_threads": category_counts.get(
                "cross_project_context_requires_readback", 0
            ),
            "missing_cwd_threads": category_counts.get(
                "thread_cwd_missing_requires_archive_or_rehome", 0
            ),
            "issue_categories": dict(sorted(category_counts.items())),
            "cleanup_candidates": dict(sorted(cleanup_counts.items())),
            "top_cwds": dict(cwd_counts.most_common(12)),
        },
        "threads": audited,
        "cleanup_safety_rules": [
            "This audit is read-only; it must not delete worktrees, caches, user files, or kill processes.",
            "Only archive a Codex worker thread after metadata/readback proves it is stale, missing cwd, or non-converged.",
            "Delete a worktree only when a separate cleanup worker verifies it was created for the current task, has no unadopted content, and the user allowed cleanup.",
            "For cross-project entries, source COS records cleanup_blocked and dispatches/re-homes into the target project instead of cleaning from the source project.",
        ],
        "recommendations": [
            "Do not use sidebar title or worker self-report alone as evidence; read thread metadata and receipts.",
            "Treat pendingWorktreeId as dispatch_pending until a real thread_id is observed.",
            "Classify non-converged review threads as rejected evidence until a receipt exists.",
            "When a user challenges archive, real execution, or skipped Skill flow, run the historical audit path.",
            "For cross-project work, verify the target project and thread context before adoption or cleanup.",
            "When real Codex tasks/threads are requested, use a WORK_RECEIPT backed by tool id/readback or stop with TOOL_BLOCKED.",
            "If a thread cwd/worktree is missing, archive or mark cleanup_blocked, reject its evidence, and re-dispatch in a live project/worktree if work remains.",
        ],
    }
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
