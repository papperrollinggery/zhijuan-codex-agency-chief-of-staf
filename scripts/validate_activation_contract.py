#!/usr/bin/env python3
"""Validate activation and dispatch hardening for the COS skill."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"ACTIVATION CONTRACT FAIL: {message}")


def read(path: Path) -> str:
    if not path.exists():
        fail(f"missing file: {path}")
    return path.read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frontmatter(text: str) -> str:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        fail("SKILL.md missing YAML frontmatter")
    return match.group(1)


def frontmatter_value(front: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", front)
    if not match:
        fail(f"frontmatter missing {key}")
    return match.group(1).strip().strip('"')


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate activation and dispatch hardening for the COS skill."
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--receipt",
        type=Path,
        help="Write a machine-readable activation validation receipt.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    skill = read(root / "SKILL.md")
    fm = frontmatter(skill)
    desc = frontmatter_value(fm, "description")
    if not desc.startswith("Use when "):
        fail("description must start with trigger-focused 'Use when '")
    if len(desc) > 700:
        fail(f"description too long for reliable trigger scanning: {len(desc)} chars")
    if "COS_BOOT_RECEIPT" not in skill:
        fail("SKILL.md must define COS_BOOT_RECEIPT")
    if "thread_dispatch_decision" not in skill:
        fail("SKILL.md must define thread_dispatch_decision")
    if "THREAD_DISPATCH_RECEIPT" not in skill:
        fail("SKILL.md must define THREAD_DISPATCH_RECEIPT")
    if re.search(r"allow_implicit_invocation:\s*false", read(root / "agents/openai.yaml")):
        fail("agents/openai.yaml disables implicit invocation")
    if not re.search(r"allow_implicit_invocation:\s*true", read(root / "agents/openai.yaml")):
        fail("agents/openai.yaml must explicitly allow implicit invocation")

    required_boot_files = [
        "assets/CHIEF_OF_STAFF_PROMPT.md",
        "assets/COS_BOOT_RECEIPT_TEMPLATE.yaml",
        "references/ACTIVATION_PROTOCOL.md",
        "references/USAGE.md",
        "README.md",
        "examples/real-world-prompts.md",
    ]
    for rel in required_boot_files:
        if "COS_BOOT_RECEIPT" not in read(root / rel):
            fail(f"{rel} must mention COS_BOOT_RECEIPT")
    if "THREAD_DISPATCH_RECEIPT" not in read(root / "assets/THREAD_DISPATCH_RECEIPT_TEMPLATE.yaml"):
        fail("thread dispatch receipt template missing marker")

    routing = read(root / "references/AGENTS_ROUTING_SNIPPET.md")
    for phrase in ["真实 Codex Threads", "TOOL_BLOCKED", "COS_BOOT_RECEIPT"]:
        if phrase not in routing:
            fail(f"AGENTS routing snippet missing {phrase}")

    eval_path = root / "evals/activation.prompts.csv"
    rows = list(csv.DictReader(eval_path.open(encoding="utf-8", newline="")))
    if len(rows) < 10:
        fail("activation eval prompt set must contain at least 10 rows")
    triggers = [row for row in rows if row["should_trigger"].lower() == "true"]
    non_triggers = [row for row in rows if row["should_trigger"].lower() == "false"]
    dispatch_cases = [
        row
        for row in rows
        if row["requires_thread_dispatch_or_tool_blocked"].lower() == "true"
    ]
    if len(triggers) < 8 or len(non_triggers) < 2 or len(dispatch_cases) < 4:
        fail("activation evals need >=8 trigger, >=2 non-trigger, >=4 dispatch cases")
    for row in triggers:
        if row["requires_boot_receipt"].lower() != "true":
            fail(f"trigger case must require boot receipt: {row['id']}")

    if args.receipt:
        watched = [
            "SKILL.md",
            "agents/openai.yaml",
            "assets/CHIEF_OF_STAFF_PROMPT.md",
            "assets/COS_BOOT_RECEIPT_TEMPLATE.yaml",
            "assets/THREAD_DISPATCH_RECEIPT_TEMPLATE.yaml",
            "references/ACTIVATION_PROTOCOL.md",
            "references/AGENTS_ROUTING_SNIPPET.md",
            "references/DELEGATION_CHAIN.md",
            "README.md",
            "evals/activation.prompts.csv",
        ]
        receipt = {
            "receipt_type": "ACTIVATION_CONTRACT_RECEIPT",
            "status": "valid",
            "root": str(root.resolve()),
            "skill_name": frontmatter_value(fm, "name"),
            "description_chars": len(desc),
            "implicit_invocation_allowed": True,
            "required_markers": {
                "COS_BOOT_RECEIPT": True,
                "THREAD_DISPATCH_RECEIPT": True,
                "thread_dispatch_decision": True,
                "TOOL_BLOCKED": True,
            },
            "eval_summary": {
                "total": len(rows),
                "should_trigger": len(triggers),
                "should_not_trigger": len(non_triggers),
                "dispatch_or_tool_blocked": len(dispatch_cases),
            },
            "source_hashes": {
                rel: sha256(root / rel)
                for rel in watched
                if (root / rel).exists()
            },
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("Activation contract valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
