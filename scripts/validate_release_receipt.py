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
SKILL_PREVIOUS_SELF_HARDENING_COMMIT = "a822df2"
SKILL_LATEST_ADOPTION_COMMIT = "e4066fc"
SKILL_LATEST_ADOPTION_WORKER_THREAD_ID = "019f339a-6907-7ff3-9dfc-2457e7a8db29"
SKILL_LATEST_ADOPTION_VALIDATION_THREAD_ID = "019f33a3-a120-70d1-af52-d3739df4395d"
SKILL_REBUTTAL_REVIEW_THREAD_ID = "019f33a8-9dd3-7741-ab18-025a657c025a"


def fail(message: str) -> None:
    raise ValueError(message)


def require_uuid(value: str, label: str) -> None:
    if not UUID_RE.match(value or ""):
        fail(f"{label} must be a real-looking Codex thread id, got {value or '<missing>'}")


def as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be boolean")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    return value


def require_marker(values: list[Any], marker: str, label: str) -> None:
    marker_lower = marker.lower()
    if not any(marker_lower in str(value).lower() for value in values):
        fail(f"{label} missing marker: {marker}")


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


def validate_cross_project_sync_evidence(data: dict[str, Any]) -> None:
    evidence = data.get("cross_project_sync_evidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        fail("cross_project_sync_evidence must be an object")
    if evidence.get("status") != "local_evidence_recorded":
        fail("cross_project_sync_evidence status must be local_evidence_recorded")
    if evidence.get("remote_push") != "not_performed":
        fail("cross_project_sync_evidence remote_push must be not_performed")
    if evidence.get("DOMAIN_DELIVERABLE_RECEIPT") != "not_applicable":
        fail("cross_project_sync_evidence DOMAIN_DELIVERABLE_RECEIPT must be not_applicable")

    rows = data.get("unified_release_thread_table", [])
    row_ids = {str(row.get("thread_id")) for row in rows if isinstance(row, dict)}
    for thread_id in [
        "019f3382-2e19-7300-af88-2adf22eddbc0",
        "019f3387-af55-7522-a24a-18a86ebe9885",
        "019f338d-cc9a-7fc2-a1c2-d90c572ce88d",
        "019f338d-3964-77f0-8a6f-4fa5d5c95ae5",
        "019f3393-3a08-78b3-8082-6af9e68d1dda",
        SKILL_LATEST_ADOPTION_WORKER_THREAD_ID,
        SKILL_LATEST_ADOPTION_VALIDATION_THREAD_ID,
        SKILL_REBUTTAL_REVIEW_THREAD_ID,
    ]:
        if thread_id not in row_ids:
            fail(f"cross-project sync evidence missing unified table row for {thread_id}")

    projects = require_list(evidence.get("projects"), "cross_project_sync_evidence.projects")
    projects_by_name = {str(project.get("project")): project for project in projects if isinstance(project, dict)}
    expected_commits = {
        "zhijuan-codex-agency-chief-of-staf": SKILL_LATEST_ADOPTION_COMMIT,
        "ad-creative-orchestrator": "9f2ae62",
        "DIR SKILL": "24bc7bb",
    }
    for project, commit in expected_commits.items():
        row = projects_by_name.get(project)
        if not isinstance(row, dict):
            fail(f"cross_project_sync_evidence missing project: {project}")
        if row.get("local_commit") != commit:
            fail(f"{project} local_commit must be {commit}")
        if row.get("remote_push") != "not_performed":
            fail(f"{project} remote_push must be not_performed")
        if row.get("DOMAIN_DELIVERABLE_RECEIPT") != "not_applicable":
            fail(f"{project} DOMAIN_DELIVERABLE_RECEIPT must be not_applicable")

    skill = projects_by_name["zhijuan-codex-agency-chief-of-staf"]
    if skill.get("previous_self_hardening_commit") != SKILL_PREVIOUS_SELF_HARDENING_COMMIT:
        fail("skill previous_self_hardening_commit must preserve a822df2")
    latest_relation = skill.get("latest_evidence_relation")
    if not isinstance(latest_relation, dict):
        fail("skill latest_evidence_relation must be an object")
    expected_relation = {
        "previous_self_hardening_commit": SKILL_PREVIOUS_SELF_HARDENING_COMMIT,
        "adoption_commit": SKILL_LATEST_ADOPTION_COMMIT,
        "adoption_worker_thread_id": SKILL_LATEST_ADOPTION_WORKER_THREAD_ID,
        "handoff_adoption_validation_thread_id": SKILL_LATEST_ADOPTION_VALIDATION_THREAD_ID,
        "rebuttal_review_thread_id": SKILL_REBUTTAL_REVIEW_THREAD_ID,
        "rebuttal_verdict": "NEEDS_HUMAN",
    }
    for field, expected in expected_relation.items():
        if latest_relation.get(field) != expected:
            fail(f"skill latest_evidence_relation {field} must be {expected}")
    if "cross-project evidence sync/adoption commit" not in str(latest_relation.get("adoption_commit_role", "")):
        fail("skill latest_evidence_relation must describe e4066fc as cross-project evidence sync/adoption commit")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "validate_release_receipt.py", "skill validation_chain")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "validate_activation_contract.py", "skill validation_chain")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "evals/activation_contract.fixture.json", "skill validation_chain")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "quality_gate.sh", "skill validation_chain")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "release_smoke.sh", "skill validation_chain")
    require_marker(require_list(skill.get("validation_chain"), "skill validation_chain"), "git diff --check", "skill validation_chain")
    workers = require_list(skill.get("worker_threads"), "skill worker_threads")
    worker_ids = {str(worker.get("thread_id")) for worker in workers if isinstance(worker, dict)}
    if worker_ids != {
        "019f3382-2e19-7300-af88-2adf22eddbc0",
        "019f3387-af55-7522-a24a-18a86ebe9885",
        SKILL_LATEST_ADOPTION_WORKER_THREAD_ID,
    }:
        fail("skill worker_threads must record self-hardening SKM/REV ids and latest adoption SKM worker id")
    for worker in workers:
        if not isinstance(worker, dict):
            fail("skill worker_threads entries must be objects")
        require_uuid(str(worker.get("thread_id")), "skill worker thread_id")
        if worker.get("cleanup_status") != "archived":
            fail("skill worker cleanup_status must be archived")
        if worker.get("adoption_status") != "adopted":
            fail("skill worker adoption_status must be adopted")
    validation_threads = require_list(skill.get("validation_threads"), "skill validation_threads")
    validation_ids = {str(thread.get("thread_id")) for thread in validation_threads if isinstance(thread, dict)}
    if SKILL_LATEST_ADOPTION_VALIDATION_THREAD_ID not in validation_ids:
        fail("skill validation_threads must record corrected handoff/adoption validation thread")
    for thread in validation_threads:
        if not isinstance(thread, dict):
            fail("skill validation_threads entries must be objects")
        require_uuid(str(thread.get("thread_id")), "skill validation thread_id")
        if thread.get("cleanup_status") != "archived":
            fail("skill validation thread cleanup_status must be archived")
        if thread.get("adoption_status") != "adopted":
            fail("skill validation thread adoption_status must be adopted")
    rebuttal = skill.get("rebuttal_review")
    if not isinstance(rebuttal, dict):
        fail("skill rebuttal_review must be an object")
    if rebuttal.get("thread_id") != SKILL_REBUTTAL_REVIEW_THREAD_ID:
        fail("skill rebuttal_review thread_id mismatch")
    if rebuttal.get("verdict") != "NEEDS_HUMAN":
        fail("skill rebuttal_review verdict must remain NEEDS_HUMAN")
    if rebuttal.get("adoption_status") != "adopted_as_blocking_evidence":
        fail("skill rebuttal_review adoption_status must preserve blocking evidence")

    adco = projects_by_name["ad-creative-orchestrator"]
    require_uuid(str(adco.get("main_cos_thread_id")), "ADCO main_cos_thread_id")
    require_uuid(str(adco.get("worker_thread_id")), "ADCO worker_thread_id")
    if adco.get("worker_thread_id") != "019f338d-cc9a-7fc2-a1c2-d90c572ce88d":
        fail("ADCO worker_thread_id mismatch")
    require_marker(require_list(adco.get("changed_files"), "ADCO changed_files"), "AGENTS.md", "ADCO changed_files")
    for marker in [
        "tools/check_gate_fixtures.py",
        "tools/run_checks.py",
        "tools/check_distribution.py",
        "git diff --check",
    ]:
        require_marker(require_list(adco.get("validation_commands"), "ADCO validation_commands"), marker, "ADCO validation_commands")
    if adco.get("remote_ci_current_head") != "not_verified":
        fail("ADCO remote_ci_current_head must be not_verified")

    directory = projects_by_name["DIR SKILL"]
    require_uuid(str(directory.get("main_cos_thread_id")), "DIR main_cos_thread_id")
    require_uuid(str(directory.get("worker_thread_id")), "DIR worker_thread_id")
    require_uuid(str(directory.get("validation_worker_thread_id")), "DIR validation_worker_thread_id")
    if directory.get("worker_thread_id") != "019f338d-3964-77f0-8a6f-4fa5d5c95ae5":
        fail("DIR worker_thread_id mismatch")
    if directory.get("validation_worker_thread_id") != "019f3393-3a08-78b3-8082-6af9e68d1dda":
        fail("DIR validation_worker_thread_id mismatch")
    if directory.get("readback_branch") != "codex/p01th09r01-skillskmdirtaskdirroutingsync":
        fail("DIR readback_branch must preserve the local branch name")
    for marker in [
        "AGENTS.md",
        "docs/film-preproduction/project-agents-protocol.md",
        "scripts/dircreative_project_agents.py",
        "scripts/validate_project.py",
    ]:
        require_marker(require_list(directory.get("changed_files"), "DIR changed_files"), marker, "DIR changed_files")
    require_marker(require_list(directory.get("validation_commands"), "DIR validation_commands"), "scripts/validate_project.py", "DIR validation_commands")
    require_marker(require_list(directory.get("validation_commands"), "DIR validation_commands"), "git diff --check", "DIR validation_commands")
    cleanup = directory.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("residual_worktree_removed") is not True:
        fail("DIR cleanup must record residual_worktree_removed true")
    if cleanup.get("removed_worktree") != "/Users/jinjungao/.codex/worktrees/7298/DIR SKILL":
        fail("DIR cleanup removed_worktree mismatch")

    hard_blockers = require_list(evidence.get("hard_blockers"), "cross_project_sync_evidence.hard_blockers")
    for marker in [
        "No remote push",
        "remote CI",
        "DOMAIN_DELIVERABLE_RECEIPT",
        "DIR live acceptance",
        "user authorization",
    ]:
        require_marker(hard_blockers, marker, "cross_project_sync_evidence.hard_blockers")
    convention_only = require_list(evidence.get("still_convention_only"), "cross_project_sync_evidence.still_convention_only")
    for marker in ["routing boundaries", "client-ready", "public release"]:
        require_marker(convention_only, marker, "cross_project_sync_evidence.still_convention_only")


def validate(data: dict[str, Any]) -> None:
    if data.get("receipt_type") != "RELEASE_CONVERGENCE_RECEIPT":
        fail("receipt_type must be RELEASE_CONVERGENCE_RECEIPT")
    require_uuid(str(data.get("root_thread_id", "")), "root_thread_id")
    budget = validate_config(data)
    cold, domain = validate_review_waves(data, budget)
    validate_unified_table(data)
    validate_release_decision(data, cold, domain)
    validate_cross_project_sync_evidence(data)


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
