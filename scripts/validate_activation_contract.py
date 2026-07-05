#!/usr/bin/env python3
"""Validate activation and dispatch hardening for the COS skill."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
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


def is_cos_coordinator_output(output: str) -> bool:
    return "COS_BOOT_RECEIPT" in output or bool(re.search(r"(?m)^\s*thread_role:\s*COS\s*$", output))


def has_worker_completion_or_adoption_evidence(output: str) -> bool:
    worker_markers = [
        "WORKER_RECEIPT",
        "RESULT_PACKET",
        "REVIEW_PACKET",
        "worker_receipt",
        "worker thread_id",
    ]
    adoption_markers = [
        "adoption_status: adopted",
        "adoption_status: adopted_after_fix",
        "adoption_status: rejected",
        "adoption_status: rejected_after_fix",
        "adoption_status: rejected_evidence",
        "adoption:",
        "rejection:",
    ]
    negative_receipt_markers = [
        "worker_receipt: missing",
        "worker_receipt: not_applicable",
        "worker_receipt: none",
        "worker_receipt: no",
        "active_no_receipt_yet",
    ]
    has_thread_id = bool(
        re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", output)
    )
    has_positive_worker_marker = any(marker in output for marker in worker_markers) and not any(
        marker in output for marker in negative_receipt_markers
    )
    return has_thread_id and (
        has_positive_worker_marker or any(marker in output for marker in adoption_markers)
    )


def has_compact_chinese_boot(output: str) -> bool:
    """Allow terse user-facing boot receipts for T0/T1/status responses."""
    for line in output.splitlines():
        if "COS_BOOT_RECEIPT" not in line:
            continue
        if "已启动" not in line:
            continue
        if "复杂度 T0" not in line and "复杂度 T1" not in line:
            continue
        if not any(marker in line for marker in ["不派发", "无需派发", "no_dispatch"]):
            continue
        if "原因" not in line:
            continue
        return True
    return False


def compact_boot_requires_full_receipt(prompt: str, output: str) -> bool:
    """Compact visible boot is only for lightweight non-thread/non-release status replies."""
    context = "\n".join([prompt, output.replace("COS_BOOT_RECEIPT", "")]).lower()
    markers = [
        "heartbeat",
        "heart beat",
        "心跳",
        "release readiness",
        "release receipt",
        "release",
        "公开仓库",
        "发布",
        "放行",
        "多文件",
        "质量审计",
        "真实 codex threads",
        "真实线程",
        "真实派发",
        "worker",
        "thread id",
        "cleanup",
        "归档",
        "审查",
        "receipt",
        "回执",
        "复杂度 t2",
        "复杂度 t3",
        "复杂度 t4",
        "复杂度 t5",
    ]
    return any(marker in context for marker in markers)


def full_machine_boot_allowed(prompt: str, output: str) -> bool:
    """Full boot fields are reserved for evidence-heavy contexts or explicit requests."""
    prompt_context = prompt.lower()
    output_context = output.lower()
    explicit_user_markers = [
        "机器字段",
        "完整字段",
        "完整 receipt",
        "完整回执",
        "yaml",
        "machine field",
        "machine-readable",
    ]
    evidence_markers = [
        "tool_blocked",
        "thread_dispatch_receipt",
        "cos_heartbeat_run_receipt",
        "heartbeat_run_receipt",
        "release_convergence_receipt",
        "thread_not_converged",
        "invalid_worker_thread_id",
        "cleanup_blocked",
    ]
    if any(marker in prompt_context for marker in explicit_user_markers):
        return True
    if any(marker in output_context for marker in evidence_markers):
        return True
    return compact_boot_requires_full_receipt(prompt, "")


def has_human_dispatch_summary(output: str) -> bool:
    """Dispatch receipts must be readable for humans before the machine fields."""
    marker_index = output.find("THREAD_DISPATCH_RECEIPT")
    if marker_index < 0:
        return True
    window = output[max(0, marker_index - 200) : marker_index + 1400]
    if not re.search(r"THREAD_DISPATCH_RECEIPT：|派发摘要|派发卡片", window):
        return False
    required_labels = ["工作线程", "职责", "读取范围", "写入范围", "预期回执", "身份契约", "收尾方式", "当前状态"]
    return all(label in window for label in required_labels)


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
    target_id = first_field_value(output, "target_thread_id") or first_field_value(
        output, "targetThreadId"
    ) or first_field_value(output, "target_thread")
    target_verified = first_field_value(output, "target_thread_verified").lower()
    target_readback = first_field_value(output, "target_thread_readback").lower()
    if not target_id or not looks_like_thread_id(target_id):
        return False
    if target_verified and target_verified != "true":
        return False
    if target_readback and target_readback != "true":
        return False
    has_verified_flag = target_verified == "true" or target_readback == "true"
    has_metadata_readback = has_nonempty_field(output, "target_thread_title") or has_nonempty_field(
        output, "target_thread_cwd"
    )
    return has_verified_flag and has_metadata_readback


def has_heartbeat_run_receipt(output: str) -> bool:
    return "HEARTBEAT_RUN_RECEIPT" in output or "COS_HEARTBEAT_RUN_RECEIPT" in output


def validate_heartbeat_run_receipt(output: str) -> list[str]:
    reasons: list[str] = []
    required_fields = {
        "target_thread_id",
        "current_due_status",
        "dispatch_required",
        "dispatch_outcome",
        "self_improvement_status",
        "self_improvement_path",
        "self_recycle_status",
        "stuck_rescue_decision",
        "next_due_or_next_check",
    }
    for field in sorted(required_fields):
        if not has_nonempty_field(output, field):
            reasons.append(f"heartbeat run receipt missing {field}")
    target_id = first_field_value(output, "target_thread_id")
    if target_id and not looks_like_thread_id(target_id):
        reasons.append("heartbeat run receipt target_thread_id is not a real-looking UUID")
    target_verified = first_field_value(output, "target_thread_verified").lower()
    if target_verified != "true":
        reasons.append("heartbeat run receipt target_thread_verified is not true")
    if not has_heartbeat_target_evidence(output):
        reasons.append("heartbeat run receipt missing target_thread_id/readback evidence")

    dispatch_required = first_field_value(output, "dispatch_required").lower()
    dispatch_outcome = first_field_value(output, "dispatch_outcome").lower()
    due_status = first_field_value(output, "current_due_status").lower()
    self_improvement_status = first_field_value(output, "self_improvement_status").lower()
    self_improvement_path = first_field_value(output, "self_improvement_path")
    self_recycle_status = first_field_value(output, "self_recycle_status").lower()
    if target_verified and target_verified != "true" and dispatch_outcome in {
        "dispatched",
        "dispatch_pending",
        "not_required_user_forbid_threads",
    }:
        reasons.append("unverified heartbeat target cannot have a non-blocking dispatch_outcome")
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
    if due_status in {"due_now", "overdue"} and dispatch_outcome not in {
        "dispatched",
        "dispatch_pending",
        "thread_dispatched",
        "tool_blocked",
        "blocked",
        "thread_not_converged",
    }:
        reasons.append("due heartbeat must dispatch or TOOL_BLOCKED/thread_not_converged")
    if due_status in {"due_now", "overdue"} and dispatch_required != "true":
        reasons.append("due heartbeat cannot mark dispatch_required false")
    failure_mode_markers = [
        "failure_mode_detected: true",
        "failure_mode:",
        "运行中修复",
        "in-flight fix",
        "running fix",
        "self-improvement required",
    ]
    if any(marker in output for marker in failure_mode_markers):
        if self_improvement_status not in {"needed", "patch_proposed", "patched", "blocked"}:
            reasons.append("heartbeat failure-mode fix lacks self_improvement_status")
        if self_improvement_path in {"", "not_applicable"}:
            reasons.append("heartbeat failure-mode fix lacks bounded self-improvement path")
    if self_improvement_status in {"needed", "patch_proposed", "patched"}:
        if self_improvement_path in {"", "not_applicable"}:
            reasons.append("self_improvement_status requires bounded self-improvement path")
        if not has_nonempty_field(output, "self_improvement_evidence"):
            reasons.append("self_improvement_status requires self_improvement_evidence")
    complete_markers = [
        "automation_goal_status: complete",
        "automation_complete: true",
        "automation lifecycle complete",
        "自动化目标完成",
        "自动化已完成",
    ]
    if any(marker in output for marker in complete_markers):
        if self_recycle_status not in {"deleted", "paused"}:
            reasons.append("automation complete requires self_recycle_status deleted or paused")
        if not has_nonempty_field(output, "self_recycle_evidence"):
            reasons.append("automation complete requires self_recycle_evidence")
    return reasons


def parse_iso_datetime(value: str) -> datetime | None:
    text = value.strip().strip('"').replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def validate_natural_heartbeat_acceptance_receipt(output: str) -> list[str]:
    reasons: list[str] = []
    if "COS_NATURAL_HEARTBEAT_ACCEPTANCE_REVIEW_RECEIPT" not in output:
        return reasons
    verdict = first_field_value(output, "verdict")
    current_time_text = first_field_value(output, "current_time")
    next_due_text = first_field_value(output, "next_natural_due_at_local") or first_field_value(
        output, "next_due_at"
    )
    if not verdict:
        reasons.append("natural heartbeat acceptance receipt missing verdict")
    if not current_time_text:
        reasons.append("natural heartbeat acceptance receipt missing current_time")
    if not next_due_text:
        reasons.append("natural heartbeat acceptance receipt missing next_natural_due_at_local")
    current_time = parse_iso_datetime(current_time_text) if current_time_text else None
    next_due = parse_iso_datetime(next_due_text) if next_due_text else None
    if current_time_text and current_time is None:
        reasons.append("natural heartbeat acceptance current_time must be ISO-8601")
    if next_due_text and next_due is None:
        reasons.append("natural heartbeat acceptance next_due must be ISO-8601")
    if current_time is not None and next_due is not None:
        if current_time < next_due and verdict != "NOT_DUE":
            reasons.append("natural heartbeat before next_due must use verdict NOT_DUE, not PASS/FAIL")
        if current_time >= next_due and verdict == "NOT_DUE":
            reasons.append("natural heartbeat at/after next_due cannot use verdict NOT_DUE")
    return reasons


def validate_missing_cwd_thread_handling(output: str) -> list[str]:
    reasons: list[str] = []
    missing_cwd_markers = [
        "当前工作目录缺失",
        "工作目录缺失",
        "current working directory missing",
        "cwd_missing",
        "worktree_missing",
        "isolated worktree was missing",
        "thread_cwd_missing",
        "cwd no longer exists",
        "worktree no longer exists",
    ]
    if not any(marker.lower() in output.lower() for marker in missing_cwd_markers):
        return reasons
    if "thread_not_converged" not in output:
        reasons.append("missing-cwd thread must be marked thread_not_converged")
    if not re.search(r"(?m)^\s*adoption_status:\s*(rejected_evidence|rejected)\s*$", output):
        reasons.append("missing-cwd thread must be rejected evidence")
    if not re.search(
        r"(?m)^\s*cleanup_status:\s*(archived|cleanup_blocked)\s*$", output
    ) and "set_thread_archived" not in output:
        reasons.append("missing-cwd thread must record archived or cleanup_blocked")
    if re.search(r"(?m)^\s*adoption_status:\s*adopted", output):
        reasons.append("missing-cwd thread cannot be adopted")
    if re.search(r"继续(等待|发送|推进)|continue (waiting|sending|using)", output, re.I):
        reasons.append("missing-cwd thread cannot be continued in place")
    if re.search(
        r"(?i)(created it from main HEAD|created .*worktree.*from main|recreated .*worktree|self-created .*worktree)"
        r"|自行(创建|重建).*worktree|重建.*worktree",
        output,
    ):
        reasons.append("missing-cwd worker cannot recreate its own worktree")
    return reasons


def validate_worker_receipt_thread_identity(case: dict, output: str) -> list[str]:
    reasons: list[str] = []
    expected_thread_id = str(case.get("expected_self_thread_id", "")).strip()
    source_thread_id = str(case.get("source_thread_id", "")).strip()
    worker_thread_ids = [value.strip() for value in field_values(output, "thread_id") if value.strip()]

    if not worker_thread_ids:
        reasons.append("role-specific worker receipt missing worker thread_id")
        return reasons
    if not any(looks_like_thread_id(thread_id) for thread_id in worker_thread_ids):
        reasons.append("role-specific worker receipt thread_id is not a real-looking UUID")
    if expected_thread_id:
        if not looks_like_thread_id(expected_thread_id):
            reasons.append("fixture expected_self_thread_id is not a real-looking UUID")
        if expected_thread_id not in worker_thread_ids:
            reasons.append("role-specific worker receipt thread_id does not match worker metadata")
    if source_thread_id and source_thread_id in worker_thread_ids and source_thread_id != expected_thread_id:
        reasons.append("role-specific worker receipt copied source_thread_id instead of worker thread_id")
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
        reasons.extend(validate_worker_receipt_thread_identity(case, output))
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
        compact_chinese_boot = has_compact_chinese_boot(output)
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
        if not compact_chinese_boot:
            for field in sorted(required_boot_fields):
                if not has_nonempty_field(output, field):
                    reasons.append(f"COS boot receipt missing {field}")
        dispatch_decision = first_field_value(output, "thread_dispatch_decision")
        complexity = first_field_value(output, "complexity")
        if (
            not compact_chinese_boot
            and complexity in {"T0", "T1"}
            and dispatch_decision == "no_dispatch"
            and not full_machine_boot_allowed(prompt, output)
        ):
            reasons.append("lightweight/status COS boot must use the compact Chinese line, not full English YAML fields")
        if compact_chinese_boot:
            if compact_boot_requires_full_receipt(prompt, output):
                reasons.append("compact Chinese boot cannot replace full receipt for heartbeat/thread/release work")
            dispatch_decision = "no_dispatch"
            complexity = "T0" if "复杂度 T0" in output else "T1"
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
    reasons.extend(validate_natural_heartbeat_acceptance_receipt(output))
    reasons.extend(validate_missing_cwd_thread_handling(output))
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
        if not has_human_dispatch_summary(output):
            reasons.append("dispatch receipt must include Chinese human-readable dispatch summary before machine fields")
        required_dispatch_fields = {
            "thread_class",
            "read_scope",
            "write_scope",
            "expected_receipt",
            "worker_prompt_identity_contract",
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
        identity_contracts = [
            value.strip()
            for value in field_values(output, "worker_prompt_identity_contract")
            if value.strip()
        ]
        if "dispatched" in dispatch_statuses and "included" not in identity_contracts:
            reasons.append("dispatched worker receipt missing worker_prompt_identity_contract: included")
        for contract in identity_contracts:
            if contract not in {"included", "pending_until_thread_id_known"}:
                reasons.append("worker_prompt_identity_contract has invalid value")
    cos_overexecution_markers = [
        "changed_files:",
        "commands_run:",
        "tests_passed:",
        "diff --git",
        "git diff",
        "git diff --check",
        "python3 scripts/",
        "bash scripts/",
        "validate_project.py",
        "quality_gate.sh",
        "release_smoke.sh",
        "check_gate_fixtures.py",
        "check_distribution.py",
        "run_checks.py",
        "install_skill.py",
        "ps -",
        "ps ",
        "pgrep",
        "kill ",
        "pkill",
        "我已实现",
        "我已修复",
        "我修改了",
        "我跑了",
        "我清理了",
    ]
    cross_project_markers = [
        "/Users/jinjungao/work/DIR SKILL",
        "/Users/jinjungao/work/ad-creative-orchestrator",
        "DIR SKILL",
        "ad-creative-orchestrator",
        "三项目",
        "跨项目",
    ]
    cross_project_gate_markers = [
        "validate_project.py",
        "quality_gate.sh",
        "release_smoke.sh",
        "check_gate_fixtures.py",
        "check_distribution.py",
        "run_checks.py",
        "git diff --check",
        "ps -",
        "kill ",
        "pkill",
    ]
    if (
        is_cos_coordinator_output(output)
        and any(marker in output for marker in cos_overexecution_markers)
        and not has_worker_completion_or_adoption_evidence(output)
    ):
        reasons.append("COS main thread cannot use direct execution evidence as completion evidence")
    if (
        is_cos_coordinator_output(output)
        and any(marker in "\n".join([prompt, output]) for marker in cross_project_markers)
        and any(marker in output for marker in cross_project_gate_markers)
        and not has_worker_completion_or_adoption_evidence(output)
    ):
        reasons.append(
            "source COS cannot directly run target project gates; dispatch target project main COS or project-bound worker"
        )
    heartbeat_enabled_claim = claims_heartbeat_automation_enabled(output)
    if heartbeat_enabled_claim and not has_heartbeat_activation_evidence(output):
        reasons.append("heartbeat/automation enablement claim lacks automation_prompt+prompt_contains_skill_invocation or explicit AGENTS routing shim evidence")
    if heartbeat_enabled_claim and not has_heartbeat_target_evidence(output):
        reasons.append("heartbeat/automation enablement claim lacks verified target_thread_id/title/cwd readback evidence")
    return not reasons, reasons


def validate_activation_fixture(root: Path, fixture_path: Path | None = None) -> dict:
    fixture_path = fixture_path or root / "evals/activation_contract.fixture.json"
    cases = json.loads(read(fixture_path))
    if not isinstance(cases, list) or len(cases) < 4:
        fail("activation contract fixture must contain at least four cases")
    required_ids = {
        "compact-chinese-t0-boot-valid",
        "full-english-t0-status-boot-invalid",
        "compact-chinese-heartbeat-missing-receipt-invalid",
        "compact-chinese-complex-audit-no-dispatch-invalid",
        "tool-blocked-no-thread-tools",
        "pending-worktree-only-invalid",
        "same-thread-simulation-invalid",
        "uuid-only-dispatch-receipt-invalid",
        "cos-main-overexecution-invalid",
        "cos-main-direct-three-project-gates-cleanup-invalid",
        "source-cos-direct-skill-target-edit-no-worker-invalid",
        "dispatch-decision-no-receipt-invalid",
        "passive-wait-no-rescue-invalid",
        "rescue-fallback-to-cos-implementation-invalid",
        "placeholder-thread-id-invalid",
        "dispatcher-set-pending-title-action-invalid",
        "rapid-poll-nonconverged-invalid",
        "missing-cwd-thread-adopted-invalid",
        "missing-cwd-worker-self-recreated-invalid",
        "missing-cwd-thread-archived-valid",
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
        "heartbeat-run-target-unverified-invalid",
        "heartbeat-due-no-dispatch-invalid",
        "heartbeat-running-fix-no-self-improvement-invalid",
        "automation-complete-no-self-recycle-invalid",
        "automation-lifecycle-complete-valid",
        "role-worker-bypass-valid",
        "role-worker-bypass-source-thread-id-invalid",
        "natural-heartbeat-before-due-fail-invalid",
        "role-worker-bypass-cos-only-invalid",
        "valid-real-dispatch",
        "dispatch-worker-prompt-identity-contract-missing-invalid",
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

    input_path = Path(args.root)
    activation_fixture_path = None
    if input_path.is_file():
        activation_fixture_path = input_path
        if input_path.name != "activation_contract.fixture.json":
            fail(f"unsupported activation fixture path: {input_path}")
        root = input_path.parent.parent
    else:
        root = input_path
    skill = read(root / "SKILL.md")
    fm = frontmatter(skill)
    desc = frontmatter_value(fm, "description")
    if not desc.startswith("Use when "):
        fail("description must start with trigger-focused 'Use when '")
    if len(desc) > 700:
        fail(f"description too long for reliable trigger scanning: {len(desc)} chars")
    if "COS_BOOT_RECEIPT" not in skill:
        fail("SKILL.md must define COS_BOOT_RECEIPT")
    if "用户可见输出规范" not in skill or "中文紧凑版" not in skill:
        fail("SKILL.md must define Chinese-first visible output rules")
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
    if "中文紧凑版" not in read(root / "assets/CHIEF_OF_STAFF_PROMPT.md"):
        fail("chief prompt must define compact Chinese boot output")
    chief_prompt = read(root / "assets/CHIEF_OF_STAFF_PROMPT.md")
    if "worker_prompt_identity_contract" not in chief_prompt or "你的真实 thread_id 是" not in chief_prompt:
        fail("chief prompt must require worker prompt identity contract")
    dispatch_template = read(root / "assets/THREAD_DISPATCH_RECEIPT_TEMPLATE.yaml")
    if "THREAD_DISPATCH_RECEIPT" not in dispatch_template:
        fail("thread dispatch receipt template missing marker")
    if "worker_prompt_identity_contract" not in dispatch_template:
        fail("thread dispatch receipt template missing worker prompt identity contract")
    if "派发摘要" not in dispatch_template:
        fail("thread dispatch receipt template must include Chinese human-readable dispatch summary guidance")
    for rel in ["SKILL.md", "assets/CHIEF_OF_STAFF_PROMPT.md", "references/ACTIVATION_PROTOCOL.md", "README.md"]:
        if "派发摘要" not in read(root / rel):
            fail(f"{rel} must require Chinese human-readable dispatch summaries")

    routing = read(root / "references/AGENTS_ROUTING_SNIPPET.md")
    for phrase in [
        "真实 Codex Threads",
        "TOOL_BLOCKED",
        "COS_BOOT_RECEIPT",
        "COS_WORKER_BYPASS",
        "用户可见输出必须中文优先",
        "中文紧凑行",
    ]:
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
        prompt_text = read(root / rel)
        if "COS_WORKER_BYPASS: true" not in prompt_text:
            fail(f"{rel} missing COS_WORKER_BYPASS marker")
        if "thread_id" not in prompt_text:
            fail(f"{rel} missing worker thread_id output field")
        if "source_thread_id" not in prompt_text:
            fail(f"{rel} missing source_thread_id misuse warning")

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

    fixture_summary = validate_activation_fixture(root, activation_fixture_path)
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
