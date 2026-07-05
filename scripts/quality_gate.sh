#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

for f in README.md LICENSE CHANGELOG.md CONTRIBUTING.md SECURITY.md Makefile; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f" >&2
    exit 1
  fi
done

for f in .github/workflows/ci.yml examples/real-world-prompts.md validation/THREADOPS_VALIDATION.md validation/ACTIVATION_HARDENING.md validation/HISTORICAL_THREAD_AUDIT.md validation/COUNCIL_ROUNDS.md validation/AGENCY_FLOW_PILOT.md validation/RELEASE_RECEIPT.md validation/release_receipt.json validation/receipts/ROUND1_RELEASE_ENGINEERING.md validation/receipts/ROUND2_BEHAVIOR.md validation/receipts/ROUND3_RELEASE_GO_NO_GO.md; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f" >&2
    exit 1
  fi
done

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agency-quality.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

# The gate installs this checkout into a temp skill root below; do not require
# the user's global installed copy to already match an isolated worktree.
SKIP_INSTALLED_COPY_DIFF=1 bash scripts/release_smoke.sh .
python3 scripts/validate_agency_flow_receipt.py validation/AGENCY_FLOW_PILOT.md
python3 scripts/validate_release_receipt.py validation/release_receipt.json
python3 scripts/validate_release_receipt.py evals/release_receipt.valid_no_stuck_review.json
python3 scripts/validate_release_receipt.py evals/release_receipt.invalid_extra_wave_no_reason.json --expect-invalid
python3 scripts/validate_release_receipt.py evals/release_receipt.invalid_stuck_review_no_rescue.json --expect-invalid
activation_receipt="$TMP_ROOT/ACTIVATION_CONTRACT_RECEIPT.json"
python3 scripts/validate_activation_contract.py . --receipt "$activation_receipt"
python3 - "$activation_receipt" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("receipt_type") != "ACTIVATION_CONTRACT_RECEIPT":
    raise SystemExit("bad activation receipt type")
if receipt.get("status") != "valid":
    raise SystemExit("activation receipt not valid")
summary = receipt.get("eval_summary", {})
if summary.get("total", 0) < 10 or summary.get("dispatch_or_tool_blocked", 0) < 4:
    raise SystemExit("activation receipt eval coverage too weak")
blackbox = receipt.get("blackbox_eval_summary", {})
if (
    blackbox.get("total", 0) < 12
    or blackbox.get("should_trigger", 0) < 8
    or blackbox.get("should_not_trigger", 0) < 3
    or blackbox.get("dispatch_or_tool_blocked", 0) < 4
    or not blackbox.get("giveaway_terms_blocked")
):
    raise SystemExit("blackbox complex prompt coverage too weak")
fixture = receipt.get("activation_fixture_summary", {})
if fixture.get("valid_cases", 0) < 2 or fixture.get("invalid_cases", 0) < 2:
    raise SystemExit("activation fixture coverage too weak")
required = {
    "SKILL.md",
    "agents/openai.yaml",
    "assets/HEARTBEAT_PROMPT.md",
    "evals/activation.prompts.csv",
    "evals/blackbox_complex.prompts.csv",
}
if not required.issubset(set(receipt.get("source_hashes", {}))):
    raise SystemExit("activation receipt missing source hashes")
PY

domain_receipt="$TMP_ROOT/DOMAIN_DELIVERABLE_CONTRACT_RECEIPT.json"
python3 scripts/validate_domain_deliverable_contract.py . --receipt "$domain_receipt"
python3 - "$domain_receipt" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("receipt_type") != "DOMAIN_DELIVERABLE_CONTRACT_RECEIPT":
    raise SystemExit("bad domain deliverable receipt type")
if receipt.get("status") != "valid":
    raise SystemExit("domain deliverable receipt not valid")
fixture = receipt.get("fixture_summary", {})
if fixture.get("valid_cases", 0) < 1 or fixture.get("invalid_cases", 0) < 6:
    raise SystemExit("domain deliverable fixture coverage too weak")
required_blocks = {
    "client-ready domain claim without DOMAIN_DELIVERABLE_RECEIPT",
    "client-ready domain claim requires PASS verdict",
    "client-ready domain claim has failing domain_quality_gates",
    "PASS verdict requires cold and domain review",
    "PASS verdict has failing domain_quality_gates",
    "missing brief_trace",
    "missing non-empty artifacts",
}
if not required_blocks.issubset(set(receipt.get("hard_blocks", []))):
    raise SystemExit("domain deliverable hard blocks missing")
PY

history_receipt="$TMP_ROOT/HISTORICAL_THREAD_AUDIT_RECEIPT.json"
python3 scripts/audit_historical_threads.py \
  --repo-root . \
  --fixture evals/history_threads.sample.json \
  --output "$history_receipt"
python3 - "$history_receipt" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("receipt_type") != "HISTORICAL_THREAD_AUDIT_RECEIPT":
    raise SystemExit("bad historical audit receipt type")
if receipt.get("status") != "valid":
    raise SystemExit("historical audit receipt not valid")
categories = set(receipt.get("summary", {}).get("issue_categories", {}))
required = {
    "activation_missing_or_unproven",
    "dispatch_missing_or_unproven",
    "pending_worktree_not_thread_id",
    "thread_cwd_missing_requires_archive_or_rehome",
    "nonconverged_evidence_must_be_rejected",
    "title_receipt_metadata_requires_readback",
    "cross_project_routing_requires_agents_snippet",
    "main_thread_self_execution_complaint",
    "history_audit_not_triggered",
}
missing = required - categories
if missing:
    raise SystemExit(f"historical audit fixture missed categories: {sorted(missing)}")
PY

python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --json >/dev/null
SKIP_INSTALLED_COPY_DIFF=1 bash "$TMP_ROOT/skills/zhijuan-codex-agency-chief-of-staf/scripts/release_smoke.sh" \
  "$TMP_ROOT/skills/zhijuan-codex-agency-chief-of-staf"

python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --json >/dev/null
python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --dry-run --json >/dev/null

routing_project="$TMP_ROOT/routing-project"
routing_home="$TMP_ROOT/routing-home"
mkdir -p "$routing_project" "$routing_home"
HOME="$routing_home" python3 scripts/install_skill.py \
  --target-root "$TMP_ROOT/routing-skills" \
  --agents-routing both \
  --project-root "$routing_project" \
  --json >"$TMP_ROOT/routing-install.json"
grep -q "BEGIN zhijuan-codex-agency-chief-of-staf routing" "$routing_project/AGENTS.md"
grep -q "COS_BOOT_RECEIPT" "$routing_project/AGENTS.md"
grep -q "THREAD_DISPATCH_RECEIPT" "$routing_home/.codex/AGENTS.md"
HOME="$routing_home" python3 scripts/install_skill.py \
  --target-root "$TMP_ROOT/routing-skills" \
  --agents-routing both \
  --project-root "$routing_project" \
  --dry-run \
  --json >"$TMP_ROOT/routing-dry-run.json"
python3 - "$TMP_ROOT/routing-install.json" "$TMP_ROOT/routing-dry-run.json" <<'PY'
import json
import sys
from pathlib import Path

install = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dry_run = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
statuses = [item["status"] for item in install.get("agents_routing", [])]
if sorted(statuses) != ["created", "created"]:
    raise SystemExit(f"unexpected AGENTS routing install statuses: {statuses}")
dry_statuses = [item["status"] for item in dry_run.get("agents_routing", [])]
if sorted(dry_statuses) != ["unchanged", "unchanged"]:
    raise SystemExit(f"unexpected AGENTS routing dry-run statuses: {dry_statuses}")
PY

tmp_pilot="$TMP_ROOT/pilot"
python3 scripts/pilot_harness.py --root . --out "$tmp_pilot" --json >/dev/null
test -f "$tmp_pilot/PILOT_HARNESS_RECEIPT.json"
test -f "$tmp_pilot/case-07/RESULT_PACKET.yaml"
test -f "$tmp_pilot/case-09/RESCUE_PACKET.yaml"
test -f "$tmp_pilot/case-10/PATCH_PROPOSAL_LIGHT_TASK_OVER_ORG.md"
python3 - "$tmp_pilot/PILOT_HARNESS_RECEIPT.json" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if receipt.get("cases", {}).get("case_08") != "skipped_by_local_harness":
    raise SystemExit("pilot harness case_08 expectation changed; update real ThreadOps validation")
PY

grep -q "zhijuan-codex-agency-chief-of-staf" README.md
grep -q "bash scripts/quality_gate.sh" README.md
grep -q "examples/real-world-prompts.md" README.md
grep -q "bounded rescue" SKILL.md
grep -q "thread_not_converged" SKILL.md
grep -q "Codex Threads 不是 subagent" SKILL.md
grep -q "TOOL_BLOCKED" SKILL.md
grep -q "set_thread_title" SKILL.md
grep -q "COS_BOOT_RECEIPT" SKILL.md
grep -q "THREAD_DISPATCH_RECEIPT" SKILL.md
grep -q "thread_dispatch_decision" SKILL.md
grep -q "dispatcher_set" SKILL.md
grep -q "worker 自述.*不能单独作为证据" SKILL.md
grep -q "不要要求 worker 加载完整幕僚长/COS Skill" SKILL.md
grep -q "title_update_blocked" references/THREAD_NAMING.md
grep -q "read_thread/list_threads" references/THREAD_NAMING.md
grep -q "dispatcher_set" references/THREAD_NAMING.md
grep -q "不要加载或扮演完整幕僚长-COS Skill" assets/EXECUTOR_PROMPT.md
grep -q "不要加载或扮演完整幕僚长-COS Skill" assets/REVIEWER_PROMPT.md
grep -q "COS_BOOT_RECEIPT" assets/CHIEF_OF_STAFF_PROMPT.md
grep -q "THREAD_DISPATCH_RECEIPT" assets/CHIEF_OF_STAFF_PROMPT.md
grep -q "THREAD_DISPATCH_RECEIPT" assets/THREAD_DISPATCH_RECEIPT_TEMPLATE.yaml
grep -q "max_review_waves" assets/CHIEF_OF_STAFF_PROMPT.md
grep -q "review_convergence_budget" validation/release_receipt.json
grep -q "unified_release_thread_table" validation/release_receipt.json
grep -q "bounded_rescue_reviewer" validation/release_receipt.json
test -f evals/release_receipt.valid_no_stuck_review.json
grep -q "additional_review_wave_reason" evals/release_receipt.invalid_extra_wave_no_reason.json
grep -q "stuck review row" scripts/validate_release_receipt.py
grep -q "invalid_worker_thread_id" scripts/validate_release_receipt.py
grep -q "validate_release_receipt.py" scripts/release_smoke.sh
grep -q "TOOL_BLOCKED" references/AGENTS_ROUTING_SNIPPET.md
grep -q "Historical Thread Audit" references/ACTIVATION_PROTOCOL.md
grep -q "HISTORICAL_THREAD_AUDIT_RECEIPT" README.md
grep -q "pending-worktree-only-invalid" evals/activation_contract.fixture.json
grep -q "same-thread-simulation-invalid" evals/activation_contract.fixture.json
grep -q "cos-main-overexecution-invalid" evals/activation_contract.fixture.json
grep -q "dispatch-decision-no-receipt-invalid" evals/activation_contract.fixture.json
grep -q "passive-wait-no-rescue-invalid" evals/activation_contract.fixture.json
grep -q "rescue-fallback-to-cos-implementation-invalid" evals/activation_contract.fixture.json
grep -q "placeholder-thread-id-invalid" evals/activation_contract.fixture.json
grep -q "dispatcher-set-pending-title-action-invalid" evals/activation_contract.fixture.json
grep -q "rapid-poll-nonconverged-invalid" evals/activation_contract.fixture.json
grep -q "missing-cwd-thread-adopted-invalid" evals/activation_contract.fixture.json
grep -q "missing-cwd-thread-archived-valid" evals/activation_contract.fixture.json
grep -q "role-worker-bypass-source-thread-id-invalid" evals/activation_contract.fixture.json
grep -q "complex-quality-audit-no-dispatch-invalid" evals/activation_contract.fixture.json
grep -q "dispatch decision without THREAD_DISPATCH_RECEIPT or TOOL_BLOCKED" scripts/validate_activation_contract.py
grep -q "COS boot receipt missing" scripts/validate_activation_contract.py
grep -q "T2+ COS task cannot use no_dispatch" scripts/validate_activation_contract.py
grep -q "passive waiting after dispatch without receipt polling or rescue state" scripts/validate_activation_contract.py
grep -q "COS cannot fall back to same-thread implementation after rescue non-convergence" scripts/validate_activation_contract.py
grep -q "title_action is not one of the allowed receipt enum values" scripts/validate_activation_contract.py
grep -q "thread_not_converged lacks paced polling or startup-grace evidence" scripts/validate_activation_contract.py
grep -q "missing-cwd thread must be marked thread_not_converged" scripts/validate_activation_contract.py
grep -q "role-specific worker receipt copied source_thread_id instead of worker thread_id" scripts/validate_activation_contract.py
grep -q "missing source_thread_id misuse warning" scripts/validate_activation_contract.py
grep -q "thread_cwd_missing_requires_archive_or_rehome" scripts/audit_historical_threads.py
grep -q "thread_cwd_missing" SKILL.md
grep -q "invalid_worker_thread_id" SKILL.md
grep -q "invalid_worker_thread_id" references/ACTIVATION_PROTOCOL.md
grep -q "current working directory missing" references/ACTIVATION_PROTOCOL.md
grep -q "heartbeat automation prompt explicitly invokes Skill but output lacks COS_BOOT_RECEIPT" scripts/validate_activation_contract.py
grep -q "T4/T5 heartbeat COS must dispatch or TOOL_BLOCKED" scripts/validate_activation_contract.py
grep -q "plain heartbeat prompt must not emit COS_BOOT_RECEIPT" scripts/validate_activation_contract.py
grep -q "heartbeat/automation enablement claim lacks automation_prompt+prompt_contains_skill_invocation or explicit AGENTS routing shim evidence" scripts/validate_activation_contract.py
grep -q "heartbeat/automation enablement claim lacks verified target_thread_id/title/cwd readback evidence" scripts/validate_activation_contract.py
grep -q "T4/T5 heartbeat COS output lacks HEARTBEAT_RUN_RECEIPT/COS_HEARTBEAT_RUN_RECEIPT" scripts/validate_activation_contract.py
grep -q "heartbeat run receipt missing dispatch_outcome" scripts/validate_activation_contract.py
grep -q "heartbeat run receipt target_thread_verified is not true" scripts/validate_activation_contract.py
grep -q "unverified heartbeat target cannot have a non-blocking dispatch_outcome" scripts/validate_activation_contract.py
grep -q "worker_receipt_poll_limit" SKILL.md
grep -q "worker_receipt_poll_interval_seconds" SKILL.md
grep -q "worker_startup_grace_seconds" SKILL.md
grep -q "DOMAIN_DELIVERABLE_RECEIPT" SKILL.md
grep -q "DOMAIN_DELIVERABLE_RECEIPT" README.md
grep -q "DOMAIN_DELIVERABLE_RECEIPT" assets/CHIEF_OF_STAFF_PROMPT.md
grep -q "domain_quality_gates" assets/DOMAIN_DELIVERABLE_RECEIPT_TEMPLATE.yaml
grep -q "client-ready domain claim without DOMAIN_DELIVERABLE_RECEIPT" scripts/validate_domain_deliverable_contract.py
grep -q "client-ready domain claim requires PASS verdict" scripts/validate_domain_deliverable_contract.py
grep -q "client-ready domain claim has failing domain_quality_gates" scripts/validate_domain_deliverable_contract.py
grep -q "PASS verdict has failing domain_quality_gates" scripts/validate_domain_deliverable_contract.py
grep -q "thread-pass-without-domain-receipt-invalid" evals/domain_deliverable_contract.fixture.json
grep -q "failing-domain-gates-pass-invalid" evals/domain_deliverable_contract.fixture.json
grep -q "client-ready-fail-verdict-invalid" evals/domain_deliverable_contract.fixture.json
grep -q "validate_domain_deliverable_contract.py" scripts/release_smoke.sh
grep -q "SKIP_INSTALLED_COPY_DIFF" scripts/release_smoke.sh
grep -q "automation heartbeats execute their configured prompt" README.md
grep -q "Heartbeat/Automation enablement claims are invalid without activation evidence" README.md
grep -q "target_thread_verified" README.md
grep -q "Automation activation contract" assets/HEARTBEAT_PROMPT.md
grep -q "Any claim that Heartbeat/Automation is enabled must cite evidence" assets/HEARTBEAT_PROMPT.md
grep -q "target_thread_verified" assets/HEARTBEAT_PROMPT.md
grep -q "COS_HEARTBEAT_RUN_RECEIPT" assets/HEARTBEAT_PROMPT.md
grep -q "COS_HEARTBEAT_RUN_RECEIPT" assets/HEARTBEAT_RUN_RECEIPT_TEMPLATE.yaml
grep -q "dispatch_outcome" assets/HEARTBEAT_RUN_RECEIPT_TEMPLATE.yaml
grep -q "bare \`AGENTS.md\` mention is not evidence" README.md
grep -q "Automation enablement is not proof that a heartbeat advanced work" README.md
grep -q "Every T4/T5 heartbeat run must output" references/ACTIVATION_PROTOCOL.md
grep -q "heartbeat-explicit-skill-valid" evals/activation_contract.fixture.json
grep -q "heartbeat-explicit-t5-no-dispatch-invalid" evals/activation_contract.fixture.json
grep -q "heartbeat-active-no-run-receipt-invalid" evals/activation_contract.fixture.json
grep -q "heartbeat-run-target-unverified-invalid" evals/activation_contract.fixture.json
grep -q "plain-one-line-heartbeat-no-cos-valid" evals/activation_contract.fixture.json
grep -q "automation-enabled-no-evidence-invalid" evals/activation_contract.fixture.json
grep -q "automation-created-before-keyword-no-evidence-invalid" evals/activation_contract.fixture.json
grep -q "automation-enabled-bare-agents-md-invalid" evals/activation_contract.fixture.json
grep -q "automation-enabled-no-target-thread-evidence-invalid" evals/activation_contract.fixture.json
grep -q "automation-enabled-with-target-thread-valid" evals/activation_contract.fixture.json
grep -q "activation_fixture_summary" scripts/validate_activation_contract.py
grep -q "blackbox_eval_summary" scripts/validate_activation_contract.py
grep -q "blackbox-08" evals/blackbox_complex.prompts.csv
grep -q "Skill 描述只能提高选择概率" README.md
grep -q "Skill 描述只能提高选择概率" references/ACTIVATION_PROTOCOL.md
grep -q "项目级 AGENTS.md" SKILL.md
grep -q "release readiness" SKILL.md
grep -q "public repository publishing" references/AGENTS_ROUTING_SNIPPET.md
grep -q "multi-file reliability validation" README.md
grep -q "history_audit_not_triggered" scripts/audit_historical_threads.py
grep -q "用户质疑.*历史线程审计" SKILL.md
test -f evals/history_threads.sample.json
grep -q "pendingWorktreeId" evals/history_threads.sample.json
grep -q "activation-10" evals/activation.prompts.csv
test -x scripts/audit_historical_threads.py
grep -q "COUNCIL_RECEIPT" validation/THREADOPS_VALIDATION.md
grep -q "TITLE_SMOKE_RECEIPT" validation/THREADOPS_VALIDATION.md
grep -q "POST_TITLE_DELTA_COUNCIL_RECEIPT" validation/THREADOPS_VALIDATION.md
grep -q "FINAL_CRITIC_RELEASE_RECEIPT" validation/THREADOPS_VALIDATION.md
grep -q "rejected evidence" validation/THREADOPS_VALIDATION.md
grep -q "FORWARD_TEST_RECEIPT" validation/THREADOPS_VALIDATION.md
grep -q "skipped_by_local_harness" validation/THREADOPS_VALIDATION.md
grep -q "019f2d91-0e96-7de1-9b25-8c3b7c545811" validation/ACTIVATION_HARDENING.md
grep -q "019f2d92-193e-7a12-8c12-4e19d4c5e264" validation/ACTIVATION_HARDENING.md
grep -q "019f2d97-74d8-7601-a4a2-cebf23b716c4" validation/ACTIVATION_HARDENING.md
grep -q "THREAD_DISPATCH_RECEIPT" validation/ACTIVATION_HARDENING.md
grep -q "AGENCY_FLOW_PILOT_RECEIPT" validation/AGENCY_FLOW_PILOT.md
grep -q "verdict: \"flow-pass\"" validation/AGENCY_FLOW_PILOT.md
grep -q "ROUND1_COUNCIL_RECEIPT" validation/receipts/ROUND1_RELEASE_ENGINEERING.md
grep -q "ROUND2_COUNCIL_RECEIPT" validation/receipts/ROUND2_BEHAVIOR.md
grep -q "ROUND3_COUNCIL_RECEIPT" validation/receipts/ROUND3_RELEASE_GO_NO_GO.md
grep -q "Round 1" validation/COUNCIL_ROUNDS.md
grep -q "Round 2" validation/COUNCIL_ROUNDS.md
grep -q "Round 3" validation/COUNCIL_ROUNDS.md
grep -q "bash scripts/quality_gate.sh ." .github/workflows/ci.yml

if grep -R -nE '^(Pending\.|.*status: `pending`)' validation/COUNCIL_ROUNDS.md validation/receipts >/dev/null; then
  echo "PENDING council or receipt evidence remains." >&2
  exit 1
fi

if grep -R -nE 'Public release still requires|project is not a public release until|fresh-clone install and real external user use remain unvalidated' README.md validation/THREADOPS_VALIDATION.md >/dev/null; then
  echo "STALE release-candidate wording remains after public release." >&2
  exit 1
fi

echo "Open-source package quality gate passed with documented ThreadOps evidence."
