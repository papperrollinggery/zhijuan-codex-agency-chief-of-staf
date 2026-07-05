#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CONVERGED_VERDICTS = {"PASS", "CONVERGED", "conditional-go", "go"}
REVIEW_TYPES = {"cold_review", "domain_review", "rebuttal_review", "domain_rebuttal_review"}
TERMINAL_CLEANUP = {"archived", "cleanup_blocked"}


def fail(message: str) -> None:
    raise ValueError(message)


def require_uuid(value: str, label: str) -> None:
    if not UUID_RE.match(value or ""):
        fail(f"{label} must be a real-looking Codex thread id, got {value or '<missing>'}")


def as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be boolean")
    return value


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        fail("release receipt root must be an object")
    return data


def validate_config(data: dict[str, Any]) -> dict[str, int]:
    config = data.get("review_convergence_budget")
    if not isinstance(config, dict):
        fail("missing review_convergence_budget")

    max_waves = config.get("max_review_waves")
    max_parallel = config.get("max_parallel_reviewers_per_deliverable")
    poll_limit = config.get("review_receipt_poll_limit")
    if not isinstance(max_waves, int) or max_waves < 2 or max_waves > 4:
        fail("max_review_waves must be an integer between 2 and 4")
    if not isinstance(max_parallel, int) or max_parallel < 1 or max_parallel > 3:
        fail("max_parallel_reviewers_per_deliverable must be an integer between 1 and 3")
    if not isinstance(poll_limit, int) or poll_limit < 1 or poll_limit > 5:
        fail("review_receipt_poll_limit must be an integer between 1 and 5")

    if "add_review_wave_reason" not in config.get("required_fields_for_new_review_wave", []):
        fail("new review waves must require add_review_wave_reason")
    stuck_policy = str(config.get("stuck_review_policy", ""))
    for marker in ("thread_not_converged", "cleanup_blocked", "bounded_rescue_reviewer"):
        if marker not in stuck_policy:
            fail(f"stuck_review_policy must mention {marker}")

    return {
        "max_waves": max_waves,
        "max_parallel": max_parallel,
        "poll_limit": poll_limit,
    }


def validate_review_waves(data: dict[str, Any], budget: dict[str, int]) -> tuple[bool, bool]:
    waves = data.get("review_waves")
    if not isinstance(waves, list) or not waves:
        fail("review_waves must be a non-empty list")
    if len(waves) > budget["max_waves"]:
        fail("review_waves exceeds max_review_waves")

    cold_converged = False
    domain_rebuttal_converged = False
    reviewers_by_wave_deliverable: dict[tuple[int, str], int] = defaultdict(int)

    for wave in waves:
        if not isinstance(wave, dict):
            fail("each review wave must be an object")
        wave_no = wave.get("wave")
        wave_type = str(wave.get("type", ""))
        deliverable = str(wave.get("deliverable", "")).strip()
        reason = str(wave.get("add_review_wave_reason", "")).strip()
        reviewers = wave.get("reviewer_thread_ids")

        if not isinstance(wave_no, int) or wave_no < 1:
            fail("review wave must have positive integer wave")
        if wave_type not in REVIEW_TYPES:
            fail(f"unsupported review wave type: {wave_type or '<missing>'}")
        if not deliverable:
            fail(f"review wave {wave_no} missing deliverable")
        if not reason:
            fail(f"review wave {wave_no} missing add_review_wave_reason")
        if not isinstance(reviewers, list) or not reviewers:
            fail(f"review wave {wave_no} must list reviewer_thread_ids")
        if len(reviewers) > budget["max_parallel"]:
            fail(f"review wave {wave_no} exceeds max_parallel_reviewers_per_deliverable")
        for idx, thread_id in enumerate(reviewers, 1):
            require_uuid(str(thread_id), f"review wave {wave_no} reviewer {idx}")

        reviewers_by_wave_deliverable[(wave_no, deliverable)] += len(reviewers)
        if reviewers_by_wave_deliverable[(wave_no, deliverable)] > budget["max_parallel"]:
            fail(f"review wave {wave_no} has too many reviewers for deliverable {deliverable}")

        verdict = str(wave.get("verdict", ""))
        receipt_status = str(wave.get("receipt_status", ""))
        cleanup_status = str(wave.get("cleanup_status", ""))
        converged = (
            verdict in CONVERGED_VERDICTS
            and receipt_status == "received"
            and cleanup_status in TERMINAL_CLEANUP
        )
        if wave_type == "cold_review" and converged:
            cold_converged = True
        if wave_type in {"domain_review", "rebuttal_review", "domain_rebuttal_review"} and converged:
            domain_rebuttal_converged = True

    return cold_converged, domain_rebuttal_converged


def validate_unified_table(data: dict[str, Any]) -> None:
    rows = data.get("unified_release_thread_table")
    if not isinstance(rows, list) or not rows:
        fail("missing unified_release_thread_table")

    required = {
        "thread_id",
        "thread_class",
        "deliverable",
        "dispatch_status",
        "receipt_status",
        "adoption_status",
        "cleanup_status",
        "review_verdict",
    }
    seen_adopted_review = False
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            fail(f"unified table row {idx} must be an object")
        missing = required - set(row)
        if missing:
            fail(f"unified table row {idx} missing fields: {sorted(missing)}")
        require_uuid(str(row.get("thread_id", "")), f"unified table row {idx} thread_id")

        thread_class = str(row.get("thread_class", ""))
        receipt_status = str(row.get("receipt_status", ""))
        adoption_status = str(row.get("adoption_status", ""))
        cleanup_status = str(row.get("cleanup_status", ""))
        review_verdict = str(row.get("review_verdict", ""))
        status = str(row.get("status", ""))

        if cleanup_status not in TERMINAL_CLEANUP:
            fail(f"unified table row {idx} cleanup_status must be archived or cleanup_blocked")
        if status.startswith("invalid_") or receipt_status == "invalid":
            if not status.startswith("invalid_"):
                fail(f"invalid thread row {idx} must use status=invalid_*")
            if adoption_status not in {"rejected_evidence", "rejected"}:
                fail(f"invalid thread row {idx} must be rejected evidence")
            if not row.get("invalid_reason"):
                fail(f"invalid thread row {idx} missing invalid_reason")
            if not row.get("controller_validation") and not row.get("rescue_thread_id"):
                fail(f"invalid thread row {idx} needs controller_validation or rescue_thread_id")
            continue
        if thread_class == "review_worker":
            if review_verdict in CONVERGED_VERDICTS and adoption_status == "adopted":
                seen_adopted_review = True
            if status == "thread_not_converged" or receipt_status != "received":
                if status != "thread_not_converged":
                    fail(f"stuck review row {idx} must use status=thread_not_converged")
                if cleanup_status not in TERMINAL_CLEANUP:
                    fail(f"stuck review row {idx} must be archived or cleanup_blocked")
                if not row.get("rescue_thread_id"):
                    fail(f"stuck review row {idx} missing rescue_thread_id")
                require_uuid(str(row.get("rescue_thread_id", "")), f"stuck review row {idx} rescue_thread_id")
                if row.get("rescue_type") != "bounded_rescue_reviewer":
                    fail(f"stuck review row {idx} must trigger bounded_rescue_reviewer")

    if not seen_adopted_review:
        fail("unified table must contain at least one adopted converged review")


def validate_release_decision(data: dict[str, Any], cold: bool, domain: bool) -> None:
    decision = data.get("release_decision")
    if not isinstance(decision, dict):
        fail("missing release_decision")
    if as_bool(decision.get("cold_review_converged"), "cold_review_converged") != cold:
        fail("release_decision cold_review_converged does not match review_waves")
    if as_bool(decision.get("domain_or_rebuttal_review_converged"), "domain_or_rebuttal_review_converged") != domain:
        fail("release_decision domain_or_rebuttal_review_converged does not match review_waves")

    stop_more = as_bool(decision.get("stop_more_reviewers"), "stop_more_reviewers")
    if cold and domain and not stop_more:
        fail("must stop adding reviewers after cold + domain/rebuttal reviews converge")
    if cold and domain and data.get("additional_review_waves_after_stop") and not decision.get("additional_review_wave_reason"):
        fail("extra review waves after stop condition require additional_review_wave_reason")


def validate(data: dict[str, Any]) -> None:
    if data.get("receipt_type") != "RELEASE_CONVERGENCE_RECEIPT":
        fail("receipt_type must be RELEASE_CONVERGENCE_RECEIPT")
    require_uuid(str(data.get("root_thread_id", "")), "root_thread_id")
    budget = validate_config(data)
    cold, domain = validate_review_waves(data, budget)
    validate_unified_table(data)
    validate_release_decision(data, cold, domain)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate release convergence budget, unified thread table, and stuck-review rescue evidence."
    )
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expect-invalid", action="store_true")
    args = parser.parse_args()

    try:
        validate(load(args.receipt))
    except ValueError as exc:
        if args.expect_invalid:
            print(f"Release receipt invalid as expected: {args.receipt}: {exc}")
            return 0
        raise SystemExit(f"RELEASE_RECEIPT_INVALID: {exc}") from exc

    if args.expect_invalid:
        raise SystemExit(f"RELEASE_RECEIPT_UNEXPECTEDLY_VALID: {args.receipt}")
    print(f"Release convergence receipt valid: {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
