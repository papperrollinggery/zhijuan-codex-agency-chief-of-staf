#!/usr/bin/env python3
"""Validate domain-deliverable hardening for COS-managed creative work."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DOMAIN_TYPES = {
    "creative",
    "storyboard",
    "proposal",
    "research",
    "copy",
    "story",
    "execution_plan",
    "planning",
}

CLIENT_READY_MARKERS = [
    "client-ready",
    "ready to send",
    "release-ready",
    "可交付",
    "可发布",
    "可以发给客户",
]


def fail(message: str) -> None:
    raise SystemExit(f"DOMAIN DELIVERABLE CONTRACT FAIL: {message}")


def read(path: Path) -> str:
    if not path.exists():
        fail(f"missing file: {path}")
    return path.read_text(encoding="utf-8")


def field_value(output: str, field: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(field)}:\s*[\"']?([^\"'\n]+)[\"']?\s*$", output)
    return match.group(1).strip() if match else ""


def has_nonempty_sequence(output: str, field: str) -> bool:
    inline_empty = re.search(rf"(?m)^\s*{re.escape(field)}:\s*\[\]\s*$", output)
    if inline_empty:
        return False
    match = re.search(rf"(?ms)^\s*{re.escape(field)}:\s*\n(?P<body>(?:[ \t]{{4,}}|[ \t]*-\s).+?)(?:\n\S|\Z)", output)
    return bool(match and re.search(r"(?m)^\s*-\s*\S", match.group("body")))


def indented_mapping(output: str, field: str) -> dict[str, str]:
    match = re.search(
        rf"(?m)^[ \t]*{re.escape(field)}:\s*\n(?P<body>(?:[ \t]{{4,}}[^\n]*\n?)+)",
        output,
    )
    if not match:
        return {}
    values: dict[str, str] = {}
    for key, value in re.findall(r"(?m)^[ \t]{4,}([A-Za-z0-9_ -]+):\s*(.+?)\s*$", match.group("body")):
        values[key.strip()] = value.strip().strip("\"'")
    return values


def gate_value_is_acceptable(value: str) -> bool:
    normalized = value.strip().upper()
    return normalized.startswith("PASS") or normalized.startswith("NOT_APPLICABLE")


def validate_domain_output_case(case: dict) -> tuple[bool, list[str]]:
    output = str(case.get("output", ""))
    reasons: list[str] = []
    has_receipt = "DOMAIN_DELIVERABLE_RECEIPT" in output
    claims_client_ready = any(marker.lower() in output.lower() for marker in CLIENT_READY_MARKERS)
    if claims_client_ready and not has_receipt:
        reasons.append("client-ready domain claim without DOMAIN_DELIVERABLE_RECEIPT")
    if not has_receipt:
        return not reasons, reasons

    deliverable_type = field_value(output, "deliverable_type")
    if deliverable_type not in DOMAIN_TYPES:
        reasons.append("missing or invalid deliverable_type")
    if not field_value(output, "audience"):
        reasons.append("missing audience")
    if "brief_trace:" not in output:
        reasons.append("missing brief_trace")
    if not has_nonempty_sequence(output, "artifacts"):
        reasons.append("missing non-empty artifacts")
    if "domain_quality_gates:" not in output:
        reasons.append("missing domain_quality_gates")
    if "validation:" not in output:
        reasons.append("missing validation")

    gate_values = indented_mapping(output, "domain_quality_gates")
    verdict = field_value(output, "verdict")
    review_status = field_value(output, "review_status")
    if claims_client_ready:
        if verdict != "PASS":
            reasons.append("client-ready domain claim requires PASS verdict")
        if review_status != "cold_reviewed_and_domain_reviewed":
            reasons.append("client-ready domain claim requires cold and domain review")
        if not gate_values:
            reasons.append("client-ready domain claim requires explicit domain quality gates")
        elif not any(value.strip().upper().startswith("PASS") for value in gate_values.values()):
            reasons.append("client-ready domain claim lacks passing domain gate evidence")
        elif any(not gate_value_is_acceptable(value) for value in gate_values.values()):
            reasons.append("client-ready domain claim has failing domain_quality_gates")
    if verdict == "PASS" and review_status != "cold_reviewed_and_domain_reviewed":
        reasons.append("PASS verdict requires cold and domain review")
    if verdict == "PASS" and not gate_values:
        reasons.append("PASS verdict requires explicit domain quality gates")
    if verdict == "PASS" and gate_values and not any(
        value.strip().upper().startswith("PASS") for value in gate_values.values()
    ):
        reasons.append("PASS verdict lacks passing domain gate evidence")
    if verdict == "PASS" and any(
        not gate_value_is_acceptable(value) for value in gate_values.values()
    ):
        reasons.append("PASS verdict has failing domain_quality_gates")

    return not reasons, reasons


def validate_fixture(root: Path) -> dict:
    path = root / "evals/domain_deliverable_contract.fixture.json"
    cases = json.loads(read(path))
    if not isinstance(cases, list) or len(cases) < 5:
        fail("domain deliverable fixture must contain at least five cases")
    required_ids = {
        "valid-domain-deliverable-pass",
        "thread-pass-without-domain-receipt-invalid",
        "missing-brief-trace-invalid",
        "pass-without-domain-review-invalid",
        "artifactless-deliverable-invalid",
        "failing-domain-gates-pass-invalid",
        "client-ready-fail-verdict-invalid",
    }
    seen = {str(case.get("id", "")) for case in cases}
    missing = required_ids - seen
    if missing:
        fail(f"domain deliverable fixture missing cases: {sorted(missing)}")

    results = []
    for case in cases:
        valid, reasons = validate_domain_output_case(case)
        expected = bool(case.get("expected_valid"))
        if valid != expected:
            fail(
                f"domain fixture {case.get('id')} expected valid={expected} "
                f"but got valid={valid}: {reasons}"
            )
        results.append(
            {
                "id": case.get("id"),
                "expected_valid": expected,
                "observed_valid": valid,
                "reasons": reasons,
            }
        )
    return {
        "total": len(cases),
        "valid_cases": sum(1 for item in results if item["observed_valid"]),
        "invalid_cases": sum(1 for item in results if not item["observed_valid"]),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate COS domain-deliverable gates for creative and client-facing work."
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--receipt", type=Path, help="Write a JSON validation receipt.")
    args = parser.parse_args()

    root = Path(args.root)
    required_markers = {
        "SKILL.md": "DOMAIN_DELIVERABLE_RECEIPT",
        "assets/CHIEF_OF_STAFF_PROMPT.md": "DOMAIN_DELIVERABLE_RECEIPT",
        "assets/DOMAIN_DELIVERABLE_RECEIPT_TEMPLATE.yaml": "domain_quality_gates",
        "references/DOMAIN_DELIVERABLE_GATES.md": "client-ready",
        "README.md": "DOMAIN_DELIVERABLE_RECEIPT",
        "references/USAGE.md": "DOMAIN_DELIVERABLE_RECEIPT",
    }
    for rel, marker in required_markers.items():
        if marker not in read(root / rel):
            fail(f"{rel} missing marker: {marker}")

    summary = validate_fixture(root)
    if args.receipt:
        receipt = {
            "receipt_type": "DOMAIN_DELIVERABLE_CONTRACT_RECEIPT",
            "status": "valid",
            "root": str(root.resolve()),
            "domain_types": sorted(DOMAIN_TYPES),
            "fixture_summary": summary,
            "hard_blocks": [
                "client-ready domain claim without DOMAIN_DELIVERABLE_RECEIPT",
                "client-ready domain claim requires PASS verdict",
                "client-ready domain claim has failing domain_quality_gates",
                "PASS verdict requires cold and domain review",
                "PASS verdict has failing domain_quality_gates",
                "missing brief_trace",
                "missing non-empty artifacts",
            ],
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("Domain deliverable contract valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
