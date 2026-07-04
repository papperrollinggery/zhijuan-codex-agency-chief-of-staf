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
    "zhijuan-codex-agency-chief-of-staf",
    "codex-agency-chief-of-staf",
    "COS_BOOT_RECEIPT",
    "THREAD_DISPATCH_RECEIPT",
    "幕僚长",
    "Chief of Staff",
]

REAL_THREAD_TERMS = [
    "真实 Codex Threads",
    "Codex Thread",
    "worker thread",
    "另一个线程",
    "新线程",
    "完整团队",
    "thread id",
    "receipt",
    "cleanup",
    "派发",
]

SELF_EXECUTION_COMPLAINTS = [
    "你还是自己在执行",
    "没安排别的线程",
    "不会自动启动",
    "不会自己去安排其他线程",
    "必须得我要求",
    "没真实执行",
    "没有真实执行",
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


def read_text(path: Path, max_bytes: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="ignore")


def contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


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
    has_dispatch = "THREAD_DISPATCH_RECEIPT" in text
    has_tool_blocked = "TOOL_BLOCKED" in text
    categories: list[str] = []

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
    if contains_any(text, SELF_EXECUTION_COMPLAINTS):
        categories.append("main_thread_self_execution_complaint")
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
    if thread["cwd"] and not in_repo:
        categories.append("cross_project_routing_requires_agents_snippet")

    markers = {
        "explicit_trigger": explicit_trigger,
        "real_thread_requested": real_thread_requested,
        "has_boot_receipt_marker": has_boot,
        "has_dispatch_receipt_marker": has_dispatch,
        "has_tool_blocked_marker": has_tool_blocked,
    }
    return sorted(set(categories)), markers


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
    for thread in threads:
        categories, markers = classify(thread, repo_root)
        category_counts.update(categories)
        cwd_counts.update([thread["cwd"] or "(unknown)"])
        entry = {
            "thread_id": thread["id"],
            "cwd": thread["cwd"],
            "archived": bool(thread["archived"]),
            "categories": categories,
            "markers": markers,
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
                "cross_project_routing_requires_agents_snippet", 0
            ),
            "issue_categories": dict(sorted(category_counts.items())),
            "top_cwds": dict(cwd_counts.most_common(12)),
        },
        "threads": audited,
        "recommendations": [
            "Do not use sidebar title or worker self-report alone as evidence; read thread metadata and receipts.",
            "Treat pendingWorktreeId as dispatch_pending until a real thread_id is observed.",
            "Classify non-converged review threads as rejected evidence until a receipt exists.",
            "When a user challenges archive, real execution, or skipped Skill flow, run the historical audit path.",
            "For cross-project default routing, install the AGENTS routing snippet where the work runs.",
            "When real Codex Threads are requested, dispatch with THREAD_DISPATCH_RECEIPT or stop with TOOL_BLOCKED.",
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
