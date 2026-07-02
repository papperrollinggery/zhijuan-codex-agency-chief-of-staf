#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


REQUIRED_ROLES = {"SKS", "AGS", "DEV", "REV"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def field(block: str, name: str) -> str:
    match = re.search(
        rf"^\s*(?:-\s*)?{re.escape(name)}:\s*\"?([^\"\n]+)\"?\s*$",
        block,
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def section(text: str, name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(name)}:\s*\n(.*?)(?=^\w|\Z)", text)
    return match.group(1) if match else ""


def child_blocks(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"(?ms)^\s*-\s+thread_id:\s*\"?[^\n\"]+\"?.*?(?=^\s*-\s+thread_id:|^\w|\Z)", text):
        blocks.append(match.group(0))
    return blocks


def fail(message: str) -> None:
    raise SystemExit(f"AGENCY_FLOW_RECEIPT_INVALID: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate that real Agency-flow ThreadOps receipts are present and converged."
    )
    parser.add_argument(
        "receipt",
        nargs="?",
        default="validation/AGENCY_FLOW_PILOT.md",
        type=Path,
        help="Agency-flow pilot receipt path.",
    )
    args = parser.parse_args()

    if not args.receipt.exists():
        fail(f"missing receipt file: {args.receipt}")

    text = args.receipt.read_text(encoding="utf-8")
    required_sections = [
        "AGENCY_FLOW_PILOT_RECEIPT:",
        "child_threads:",
        "commands_run:",
        "artifacts:",
        "adoption_rejection:",
        "cleanup_status:",
        "blocking_findings:",
        "required_fix:",
    ]
    for marker in required_sections:
        if marker not in text:
            fail(f"missing marker: {marker}")

    verdict = field(text, "verdict")
    status = field(text, "status")
    if verdict != "flow-pass":
        fail(f"verdict must be flow-pass for release readiness, got {verdict or '<missing>'}")
    if status != "done":
        fail(f"status must be done, got {status or '<missing>'}")

    blocks_by_role: dict[str, str] = {}
    adopted_children = section(text, "child_threads")
    if re.search(r"(?m)^\s*status:\s*\"?thread_not_converged\"?\s*$", adopted_children):
        fail("adopted child_threads still contain status=thread_not_converged")

    for block in child_blocks(adopted_children):
        role = field(block, "role")
        if role:
            blocks_by_role[role] = block

    missing_roles = REQUIRED_ROLES - blocks_by_role.keys()
    if missing_roles:
        fail(f"missing child role(s): {', '.join(sorted(missing_roles))}")

    for role in sorted(REQUIRED_ROLES):
        block = blocks_by_role[role]
        thread_id = field(block, "thread_id")
        if not UUID_RE.match(thread_id):
            fail(f"{role} has invalid thread_id: {thread_id or '<missing>'}")
        thread_class = field(block, "thread_class")
        if thread_class != role:
            fail(f"{role} thread_class must equal role, got {thread_class or '<missing>'}")
        if field(block, "status") != "done":
            fail(f"{role} status must be done")
        if field(block, "receipt_status") != "received":
            fail(f"{role} receipt_status must be received")
        if field(block, "cleanup_status") != "archived":
            fail(f"{role} cleanup_status must be archived")

    if field(blocks_by_role["REV"], "verdict") != "PASS":
        fail("REV verdict must be PASS")

    print(f"Agency-flow receipt valid: {args.receipt}")


if __name__ == "__main__":
    main()
