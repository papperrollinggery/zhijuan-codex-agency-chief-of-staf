# Historical Thread Audit

Date: 2026-07-04

This file records the local cross-project audit requested after v0.1.6. The audit looks for historical uses of `zhijuan-codex-agency-chief-of-staf`, `幕僚长`, `COS_BOOT_RECEIPT`, and `THREAD_DISPATCH_RECEIPT` across Codex thread metadata and rollout logs.

## Command

```bash
python3 scripts/audit_historical_threads.py --repo-root . --scan-rollouts --max-rollout-bytes 1200000 --output /tmp/live_history_receipt.json
```

Fixture coverage is wired into `scripts/quality_gate.sh`:

```bash
python3 scripts/audit_historical_threads.py --repo-root . --fixture evals/history_threads.sample.json --output <tmp>/HISTORICAL_THREAD_AUDIT_RECEIPT.json
```

## Local Result

Summary from `/tmp/live_history_receipt.json`:

```json
{
  "matching_threads": 75,
  "cross_project_threads": 45,
  "issue_categories": {
    "activation_missing_or_unproven": 48,
    "cross_project_routing_requires_agents_snippet": 45,
    "main_thread_self_execution_complaint": 1,
    "nonconverged_evidence_must_be_rejected": 49,
    "pending_worktree_not_thread_id": 74,
    "title_receipt_metadata_requires_readback": 74
  }
}
```

Top matched projects:

- `/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf`: 30 threads.
- `/Users/jinjungao/work/ad-creative-orchestrator`: 7 threads.
- `/Users/jinjungao/Documents/策划文案/Duffy Month_ 10yrs & BTS `: 5 threads.

## Findings

1. Historical evidence cannot be trusted from thread title or worker self-report alone. Several runs contain title changes or title-blocked states, so current release evidence must use thread metadata/readback.
2. `pendingWorktreeId` appears frequently in historical traces. It is not a worker `thread_id`; it only means dispatch is pending until a real thread appears.
3. Many early review/council threads contain `thread_not_converged`. Those runs are rejected evidence unless a later bounded rescue receipt exists.
4. Cross-project usage is common. Installing the Skill globally does not guarantee a project will route through COS automatically; projects that need default routing must include `references/AGENTS_ROUTING_SNIPPET.md` in their `AGENTS.md`.
5. The `ad-creative-orchestrator` history shows the realistic failure shape: the Skill can be used as orchestration guidance while the actual project still needs explicit local gates, worker scope, thread metadata, and adoption/cleanup proof.

## Adopted Fix

- Added `scripts/audit_historical_threads.py` for local historical auditing.
- Added `evals/history_threads.sample.json` and quality-gate fixture checks for the six recurring failure modes.
- Added `evals/activation_contract.fixture.json` so `TOOL_BLOCKED`, `pendingWorktreeId`, and same-thread simulation are checked as output-level contract cases.
- Added historical audit rules to `SKILL.md` and `references/ACTIVATION_PROTOCOL.md`.
- Added README usage so users can reproduce the audit without exposing raw thread text.

## Adversarial Review

- History audit thread `019f2dc4-386c-7811-a259-3c04bbd87423`: returned `HISTORY_AUDIT_RECEIPT`; found P0 cross-project implicit startup failures and P0 main-thread self-execution risk in ADCO/DIR-style cases, plus P1 pending worktree, non-converged review, and title/readback risks.
- Gate audit thread `019f2dc4-3ff7-7381-9e06-1ee6a0f1f4be`: returned `GATE_AUDIT_RECEIPT`; verdict `warn`, no blocker. It challenged static grep-heavy gates and recommended output-level fixtures for `TOOL_BLOCKED`, `pendingWorktreeId`, same-thread simulation, and cross-project routing.
- Release audit thread `019f2dc4-46ff-71a0-8357-bdbd242a5006`: returned `RELEASE_AUDIT_RECEIPT`; verdict `GO_WITH_NON_BLOCKING_FIXES`. It recommended clearer activation-path docs and a fixed `TOOL_BLOCKED` example.

Adoption:

- Accepted: local historical audit script, fixture-backed quality gate, output-level activation fixture, README activation-path wording, and `TOOL_BLOCKED`/pending worktree example.
- Rejected for this patch: a live CI smoke that creates real Codex Threads. Public CI does not have Codex Desktop thread tools, so the correct gate is deterministic fixture validation plus local live audit evidence.

## Residual Risk

The local audit reads this machine's Codex history. It should not be used as public proof for other users' machines. Public CI validates the classifier against a fixture; local release readiness should additionally run the live audit command above when historical behavior is in scope.
