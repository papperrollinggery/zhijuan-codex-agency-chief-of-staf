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


def looks_like_thread_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value))


def has_nonempty_field(output: str, field: str) -> bool:
    match = re.search(rf"(?m)^\s*{re.escape(field)}:\s*[\"']?([^\"'\n]+)[\"']?\s*$", output)
    return bool(match and match.group(1).strip())


def field_values(output: str, field: str) -> list[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(
            rf"(?m)^\s*-?\s*{re.escape(field)}:\s*[\"']?([^\"'\n]*)[\"']?\s*$",
            output,
        )
    ]


def first_field_value(output: str, field: str) -> str:
    values = field_values(output, field)
    return values[0] if values else ""


def case_prompt_text(case: dict) -> str:
    parts = [
        str(case.get("prompt", "")),
        str(case.get("input", "")),
        str(case.get("automation_prompt", "")),
    ]
    return "\n".join(part for part in parts if part)


def has_explicit_skill_invocation(text: str) -> bool:
    return any(
        marker in text
        for marker in [
            "$zhijuan-codex-agency-chief-of-staf",
            "使用本 Skill",
            "使用本Skill",
            "启动幕僚长",
            "按本 Skill 流程",
            "按本Skill流程",
        ]
    )


def is_heartbeat_prompt(text: str) -> bool:
    lowered = text.lower()
    return "heartbeat" in lowered or "heart beat" in lowered or "心跳" in text


def is_plain_one_line_emitter(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            "send exactly one plain text message",
            "send exactly one line",
            "do nothing else",
            "add no extra explanation",
        ]
    ) or any(marker in text for marker in ["只发送一句话", "只发一句话", "其他什么都不要做"])


def is_role_worker_bypass_prompt(text: str) -> bool:
    role_markers = [
        "审查官-REV",
        "执行线程",
        "开发执行-DEV",
        "技能侦察-SKS",
        "Agent侦察-AGS",
        "救援官-RSC",
        "合成官-SYN",
        "Skill维护-SKM",
        "review_worker",
        "implementation_worker",
        "rescue_worker",
        "scout_worker",
    ]
    bypass_markers = [
        "COS_WORKER_BYPASS: true",
        "不要加载或扮演完整幕僚长-COS Skill",
        "不要扮演幕僚长",
        "do not act as Chief-of-Staff",
        "do not re-dispatch",
        "do not redispatch",
    ]
    direct_output_markers = [
        "输出 Review Packet",
        "输出 Result Packet",
        "输出指定 receipt",
        "output the requested packet",
        "output the requested receipt",
        "_RECEIPT",
    ]
    return (
        any(marker in text for marker in role_markers)
        and any(marker in text for marker in bypass_markers)
        and any(marker in text for marker in direct_output_markers)
    )


def expected_worker_receipt_marker(case: dict, prompt: str) -> str:
    explicit = str(case.get("expected_worker_receipt", "")).strip()
    if explicit:
        return explicit
    match = re.search(r"\b([A-Z][A-Z0-9_]{3,}_RECEIPT)\b", prompt)
    return match.group(1) if match else ""


def claims_heartbeat_automation_enabled(output: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(heartbeat|automation)\b[^\n]{0,80}\b(enabled|active|installed|created)\b",
            output,
        )
        or re.search(
            r"(?i)\b(enabled|active|installed|created)\b[^\n]{0,80}\b(heartbeat|automation)\b",
            output,
        )
        or re.search(r"(心跳|自动化)[^\n]{0,40}(已启用|已创建|已安装|已激活|生效)", output)
        or re.search(r"(已启用|已创建|已安装|已激活|生效)[^\n]{0,40}(心跳|自动化)", output)
    )


def has_heartbeat_activation_evidence(output: str) -> bool:
    has_prompt_source = any(
        marker in output
        for marker in [
            "automation_prompt:",
            "automation_prompt_path:",
            "automation.toml",
        ]
    )
    has_prompt_invocation = bool(
        re.search(r"(?m)^\s*prompt_contains_skill_invocation:\s*true\s*$", output)
    )
    has_routing_shim = any(
        marker in output
        for marker in [
            "agents_routing_evidence:",
            "AGENTS routing shim",
            "AGENTS.md routing shim",
        ]
    )
    return (has_prompt_source and has_prompt_invocation) or has_routing_shim


def has_heartbeat_target_evidence(output: str) -> bool:
    has_target_id = any(
        marker in output
        for marker in [
            "target_thread_id:",
            "targetThreadId:",
            "target_thread:",
        ]
    )
    has_target_readback = any(
        marker in output
        for marker in [
            "target_thread_verified: true",
            "target_thread_readback: true",
            "target_thread_title:",
            "target_thread_cwd:",
        ]
    )
    return has_target_id and has_target_readback


def has_heartbeat_run_receipt(output: str) -> bool:
    return "HEARTBEAT_RUN_RECEIPT" in output or "COS_HEARTBEAT_RUN_RECEIPT" in output


def validate_heartbeat_run_receipt(output: str) -> list[str]:
    reasons: list[str] = []
    required_fields = {
        "target_thread_id",
        "current_due_status",
        "dispatch_required",
        "dispatch_outcome",
        "stuck_rescue_decision",
        "next_due_or_next_check",
    }
    for field in sorted(required_fields):
        if not has_nonempty_field(output, field):
            reasons.append(f"heartbeat run receipt missing {field}")
    if not has_heartbeat_target_evidence(output):
        reasons.append("heartbeat run receipt missing target_thread_id/readback evidence")

    dispatch_required = first_field_value(output, "dispatch_required").lower()
    dispatch_outcome = first_field_value(output, "dispatch_outcome").lower()
    if dispatch_required == "true" and not dispatch_outcome:
        reasons.append("heartbeat run receipt missing dispatch_outcome for required dispatch")
    if dispatch_required == "true" and dispatch_outcome in {"tool_blocked", "blocked"}:
        if "TOOL_BLOCKED" not in output:
            reasons.append("heartbeat run receipt dispatch_outcome tool_blocked without TOOL_BLOCKED")
    if dispatch_required == "true" and dispatch_outcome in {
        "dispatched",
        "dispatch_pending",
        "thread_dispatched",
    }:
        if (
            "THREAD_DISPATCH_RECEIPT" not in output
            and not has_nonempty_field(output, "thread_dispatch_receipt")
        ):
            reasons.append("heartbeat run receipt dispatch_outcome lacks thread_dispatch_receipt")
    if dispatch_required == "true" and dispatch_outcome not in {
        "dispatched",
        "dispatch_pending",
        "thread_dispatched",
        "tool_blocked",
        "blocked",
        "thread_not_converged",
        "not_required_user_forbid_threads",
    }:
        reasons.append("heartbeat run receipt dispatch_outcome is not actionable")
    return reasons


def validate_activation_output_case(case: dict) -> tuple[bool, list[str]]:
    output = str(case.get("output", ""))
    prompt = case_prompt_text(case)
    explicit_skill_heartbeat = is_heartbeat_prompt(prompt) and has_explicit_skill_invocation(prompt)
    plain_one_line_heartbeat = (
        is_heartbeat_prompt(prompt)
        and is_plain_one_line_emitter(prompt)
        and not has_explicit_skill_invocation(prompt)
    )
    worker_bypass = bool(case.get("worker_bypass")) or is_role_worker_bypass_prompt(prompt)
    if "requires_cos_boot" in case:
        requires_cos_boot = bool(case.get("requires_cos_boot"))
    else:
        requires_cos_boot = not plain_one_line_heartbeat and not worker_bypass
    reasons: list[str] = []
    if worker_bypass:
        if requires_cos_boot:
            reasons.append("role-specific worker bypass cannot require COS boot")
        if "COS_BOOT_RECEIPT" in output:
            reasons.append("role-specific worker bypass must not emit COS_BOOT_RECEIPT")
        receipt_marker = expected_worker_receipt_marker(case, prompt)
        if receipt_marker and receipt_marker not in output:
            reasons.append(f"role-specific worker bypass missing expected receipt: {receipt_marker}")
        elif not receipt_marker and not any(
            marker in output for marker in ["REVIEW_PACKET", "RESULT_PACKET", "_RECEIPT"]
        ):
            reasons.append("role-specific worker bypass missing packet or receipt output")
    if explicit_skill_heartbeat and not requires_cos_boot:
        reasons.append("heartbeat automation prompt explicitly invokes Skill but fixture marks COS boot optional")
        requires_cos_boot = True
    if not requires_cos_boot and "COS_BOOT_RECEIPT" in output:
        reasons.append("plain heartbeat prompt must not emit COS_BOOT_RECEIPT")
    if requires_cos_boot and "COS_BOOT_RECEIPT" not in output:
        if explicit_skill_heartbeat:
            reasons.append("heartbeat automation prompt explicitly invokes Skill but output lacks COS_BOOT_RECEIPT")
        else:
            reasons.append("missing COS_BOOT_RECEIPT")
    elif "COS_BOOT_RECEIPT" in output:
        required_boot_fields = {
            "skill_loaded",
            "trigger_type",
            "thread_role",
            "title_action",
            "complexity",
            "thread_tools_available",
            "thread_dispatch_decision",
            "worker_receipt_poll_limit",
            "worker_receipt_poll_interval_seconds",
            "worker_startup_grace_seconds",
            "reason",
        }
        for field in sorted(required_boot_fields):
            if not has_nonempty_field(output, field):
                reasons.append(f"COS boot receipt missing {field}")
        dispatch_decision = first_field_value(output, "thread_dispatch_decision")
        complexity = first_field_value(output, "complexity")
        if (
            explicit_skill_heartbeat
            and complexity in {"T4", "T5"}
            and dispatch_decision not in {"dispatch", "tool_blocked"}
        ):
            reasons.append("T4/T5 heartbeat COS must dispatch or TOOL_BLOCKED")
        if explicit_skill_heartbeat and complexity in {"T4", "T5"} and not has_heartbeat_run_receipt(output):
            reasons.append("T4/T5 heartbeat COS output lacks HEARTBEAT_RUN_RECEIPT/COS_HEARTBEAT_RUN_RECEIPT")
        explicit_no_thread_markers = [
            "用户明确禁止创建子线程",
            "user explicitly prohibited threads",
            "user_explicitly_forbid_threads",
        ]
        if (
            dispatch_decision == "no_dispatch"
            and complexity not in {"T0", "T1"}
            and not any(marker in output for marker in explicit_no_thread_markers)
        ):
            reasons.append("T2+ COS task cannot use no_dispatch without explicit user thread prohibition")
    if "thread_dispatch_decision: tool_blocked" in output and "TOOL_BLOCKED" not in output:
        reasons.append("tool_blocked decision without TOOL_BLOCKED marker")
    if has_heartbeat_run_receipt(output):
        reasons.extend(validate_heartbeat_run_receipt(output))
    if (
        "thread_dispatch_decision: dispatch" in output
        and "THREAD_DISPATCH_RECEIPT" not in output
        and "TOOL_BLOCKED" not in output
    ):
        reasons.append("dispatch decision without THREAD_DISPATCH_RECEIPT or TOOL_BLOCKED")
    dispatch_statuses = [value.strip() for value in field_values(output, "status")]
    has_pending_worktree = has_nonempty_field(output, "pending_worktree_id") or has_nonempty_field(
        output, "pendingWorktreeId"
    )
    if ("pendingWorktreeId" in output or "pending_worktree_id" in output) and re.search(
        r"(?m)^\s*status:\s*dispatched\s*$", output
    ):
        reasons.append("pendingWorktreeId cannot have dispatched status")
    if "dispatch_pending" in dispatch_statuses and not has_pending_worktree:
        reasons.append("dispatch_pending status missing pending_worktree_id")
    bad_title_action = re.search(
        r"(?m)^\s*title_action:\s*[\"']?([^\"'\n]+)[\"']?\s*$", output
    )
    allowed_title_actions = {
        "self_set",
        "dispatcher_set",
        "title_preserved_by_user",
        "title_update_blocked",
    }
    if bad_title_action and bad_title_action.group(1).strip() not in allowed_title_actions:
        reasons.append("title_action is not one of the allowed receipt enum values")
    if (
        "THREAD_DISPATCH_RECEIPT" in output
        and re.search(r"仍在等待|still waiting|waiting for", output, re.I)
        and not re.search(r"receipt_status|remaining_polls|thread_not_converged|rescue_worker|bounded_rescue", output)
    ):
        reasons.append("passive waiting after dispatch without receipt polling or rescue state")
    if (
        "thread_not_converged" in output
        and re.search(r"3 次读回|3 次轮询|poll 3/3|poll_round:\s*3", output, re.I)
        and not re.search(
            r"worker_receipt_poll_interval_seconds|worker_startup_grace_seconds|grace_elapsed|timeout_elapsed|elapsed_seconds|next_poll",
            output,
        )
    ):
        reasons.append("thread_not_converged lacks paced polling or startup-grace evidence")
    rescue_fallback_markers = [
        "改为当前 worktree",
        "当前 worktree 做最小修复",
        "current worktree",
        "same-thread implementation",
        "COS worktree",
        "开始改",
        "我现在会在当前",
        "fileChange",
    ]
    if (
        re.search(r"(?m)^\s*thread_role:\s*COS\s*$", output)
        and "thread_not_converged" in output
        and any(marker in output for marker in rescue_fallback_markers)
        and "WORKER_RECEIPT" not in output
        and "RESULT_PACKET" not in output
    ):
        reasons.append("COS cannot fall back to same-thread implementation after rescue non-convergence")
    if re.search(r"same-thread|同线程|simulate|模拟", output, re.I) and "THREAD_DISPATCH_RECEIPT" in output:
        reasons.append("same-thread simulation cannot satisfy THREAD_DISPATCH_RECEIPT")
    if "THREAD_DISPATCH_RECEIPT" in output:
        required_dispatch_fields = {
            "thread_class",
            "read_scope",
            "write_scope",
            "expected_receipt",
            "title_action",
            "cleanup_plan",
            "status",
        }
        for field in sorted(required_dispatch_fields):
            if not has_nonempty_field(output, field):
                reasons.append(f"dispatch receipt missing {field}")
        if not dispatch_statuses:
            reasons.append("dispatch receipt missing status")
        elif not any(status in {"dispatched", "dispatch_pending"} for status in dispatch_statuses):
            reasons.append("dispatch receipt status is not dispatched or dispatch_pending")
        thread_ids = [value.strip() for value in field_values(output, "thread_id") if value.strip()]
        if "dispatched" in dispatch_statuses and not thread_ids:
            reasons.append("dispatch receipt missing thread_id")
        if "dispatch_pending" not in dispatch_statuses and not thread_ids:
            reasons.append("dispatch receipt missing thread_id")
        for thread_id in thread_ids:
            if not looks_like_thread_id(thread_id):
                reasons.append("dispatch receipt thread_id is not a real-looking UUID")
    cos_overexecution_markers = [
        "changed_files:",
        "commands_run:",
        "tests_passed:",
        "diff --git",
        "git diff",
        "我已实现",
        "我已修复",
        "我修改了",
    ]
    worker_result_markers = [
        "WORKER_RECEIPT",
        "RESULT_PACKET",
        "REVIEW_PACKET",
        "worker_receipt",
        "adoption:",
        "rejection:",
    ]
    if (
        re.search(r"(?m)^\s*thread_role:\s*COS\s*$", output)
        and any(marker in output for marker in cos_overexecution_markers)
        and not any(marker in output for marker in worker_result_markers)
    ):
        reasons.append("COS main thread appears to claim direct execution")
    heartbeat_enabled_claim = claims_heartbeat_automation_enabled(output)
    if heartbeat_enabled_claim and not has_heartbeat_activation_evidence(output):
        reasons.append("heartbeat/automation enablement claim lacks automation_prompt+prompt_contains_skill_invocation or explicit AGENTS routing shim evidence")
    if heartbeat_enabled_claim and not has_heartbeat_target_evidence(output):
        reasons.append("heartbeat/automation enablement claim lacks verified target_thread_id/title/cwd readback evidence")
    return not reasons, reasons


def validate_activation_fixture(root: Path) -> dict:
    fixture_path = root / "evals/activation_contract.fixture.json"
    cases = json.loads(read(fixture_path))
    if not isinstance(cases, list) or len(cases) < 4:
        fail("activation contract fixture must contain at least four cases")
    required_ids = {
        "tool-blocked-no-thread-tools",
        "pending-worktree-only-invalid",
        "same-thread-simulation-invalid",
        "uuid-only-dispatch-receipt-invalid",
        "cos-main-overexecution-invalid",
        "dispatch-decision-no-receipt-invalid",
        "passive-wait-no-rescue-invalid",
        "rescue-fallback-to-cos-implementation-invalid",
        "placeholder-thread-id-invalid",
        "dispatcher-set-pending-title-action-invalid",
        "rapid-poll-nonconverged-invalid",
        "complex-quality-audit-no-dispatch-invalid",
        "heartbeat-explicit-skill-valid",
        "heartbeat-explicit-t5-no-dispatch-invalid",
        "plain-one-line-heartbeat-no-cos-valid",
        "automation-enabled-no-evidence-invalid",
        "automation-created-before-keyword-no-evidence-invalid",
        "automation-enabled-bare-agents-md-invalid",
        "automation-enabled-no-target-thread-evidence-invalid",
        "automation-enabled-with-target-thread-valid",
        "heartbeat-active-no-run-receipt-invalid",
        "role-worker-bypass-valid",
        "role-worker-bypass-cos-only-invalid",
        "valid-real-dispatch",
        "valid-pending-worktree-dispatch",
    }
    seen = {str(case.get("id", "")) for case in cases}
    missing = required_ids - seen
    if missing:
        fail(f"activation contract fixture missing cases: {sorted(missing)}")
    results = []
    for case in cases:
        valid, reasons = validate_activation_output_case(case)
        expected = bool(case.get("expected_valid"))
        if valid != expected:
            fail(
                f"activation fixture {case.get('id')} expected valid={expected} "
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


def validate_blackbox_prompt_set(root: Path) -> dict:
    path = root / "evals/blackbox_complex.prompts.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    if len(rows) < 12:
        fail("blackbox complex prompt set must contain at least 12 rows")

    required_columns = {
        "id",
        "category",
        "should_trigger",
        "requires_thread_dispatch_or_tool_blocked",
        "prompt",
    }
    missing_columns = required_columns - set(rows[0])
    if missing_columns:
        fail(f"blackbox prompt set missing columns: {sorted(missing_columns)}")

    giveaway_terms = [
        "$zhijuan",
        "skill",
        "Skill",
        "幕僚长",
        "Codex Agency",
        "完整团队",
        "真实 Codex Threads",
        "Codex Threads",
        "thread",
        "Thread",
        "线程",
        "worker",
        "receipt",
        "cleanup",
        "Plan",
        "Goal",
        "自动调度",
        "反驳审核",
    ]
    triggers = [row for row in rows if row["should_trigger"].lower() == "true"]
    non_triggers = [row for row in rows if row["should_trigger"].lower() == "false"]
    dispatch_cases = [
        row
        for row in rows
        if row["requires_thread_dispatch_or_tool_blocked"].lower() == "true"
    ]
    if len(triggers) < 8 or len(non_triggers) < 3:
        fail("blackbox evals need >=8 trigger and >=3 non-trigger cases")
    if len(dispatch_cases) < 4:
        fail("blackbox evals need >=4 implicit dispatch/tool-blocked cases")
    non_trigger_dispatch = [
        row["id"]
        for row in non_triggers
        if row["requires_thread_dispatch_or_tool_blocked"].lower() == "true"
    ]
    if non_trigger_dispatch:
        fail(f"non-trigger blackbox prompts cannot require dispatch: {non_trigger_dispatch}")

    categories = {row["category"].strip() for row in triggers if row["category"].strip()}
    if len(categories) < 5:
        fail("blackbox trigger prompts must cover at least five task categories")

    for row in rows:
        prompt = row["prompt"]
        leaked = [term for term in giveaway_terms if term in prompt]
        if leaked:
            fail(f"blackbox prompt {row['id']} contains giveaway terms: {leaked}")
        if row["should_trigger"].lower() == "true" and len(prompt) < 24:
            fail(f"blackbox trigger prompt too short to be a complex-task probe: {row['id']}")
        if (
            row["requires_thread_dispatch_or_tool_blocked"].lower() == "true"
            and row["should_trigger"].lower() != "true"
        ):
            fail(f"dispatch blackbox prompt must also be a trigger case: {row['id']}")

    return {
        "total": len(rows),
        "should_trigger": len(triggers),
        "should_not_trigger": len(non_triggers),
        "dispatch_or_tool_blocked": len(dispatch_cases),
        "trigger_categories": sorted(categories),
        "giveaway_terms_blocked": True,
    }


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
    for marker in ("worker_receipt_poll_interval_seconds", "worker_startup_grace_seconds"):
        if marker not in skill:
            fail(f"SKILL.md must define {marker}")
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
    for phrase in ["真实 Codex Threads", "TOOL_BLOCKED", "COS_BOOT_RECEIPT", "COS_WORKER_BYPASS"]:
        if phrase not in routing:
            fail(f"AGENTS routing snippet missing {phrase}")
    role_prompt_files = [
        "assets/AGENT_SCOUT_PROMPT.md",
        "assets/ARCHIVIST_PROMPT.md",
        "assets/EXECUTOR_PROMPT.md",
        "assets/GOAL_STEWARD_PROMPT.md",
        "assets/PLANNER_PROMPT.md",
        "assets/RESCUE_PROMPT.md",
        "assets/REVIEWER_PROMPT.md",
        "assets/SKILL_MAINTAINER_PROMPT.md",
        "assets/SKILL_SCOUT_PROMPT.md",
        "assets/SYNTHESIZER_PROMPT.md",
    ]
    for rel in role_prompt_files:
        if "COS_WORKER_BYPASS: true" not in read(root / rel):
            fail(f"{rel} missing COS_WORKER_BYPASS marker")

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

    fixture_summary = validate_activation_fixture(root)
    blackbox_summary = validate_blackbox_prompt_set(root)

    if args.receipt:
        watched = [
            "SKILL.md",
            "agents/openai.yaml",
            "assets/CHIEF_OF_STAFF_PROMPT.md",
            "assets/COS_BOOT_RECEIPT_TEMPLATE.yaml",
            "assets/THREAD_DISPATCH_RECEIPT_TEMPLATE.yaml",
            "assets/HEARTBEAT_RUN_RECEIPT_TEMPLATE.yaml",
            "references/ACTIVATION_PROTOCOL.md",
            "references/AGENTS_ROUTING_SNIPPET.md",
            "references/DELEGATION_CHAIN.md",
            "assets/HEARTBEAT_PROMPT.md",
            "README.md",
            "evals/activation.prompts.csv",
            "evals/blackbox_complex.prompts.csv",
            "evals/activation_contract.fixture.json",
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
            "blackbox_eval_summary": blackbox_summary,
            "activation_fixture_summary": fixture_summary,
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
