# Historical Thread Audit

Date: 2026-07-05

This file records the local cross-project audit requested after v0.1.6. The audit looks for historical uses of `zhijuan-codex-agency-chief-of-staf`, `幕僚长`, `COS_BOOT_RECEIPT`, and `THREAD_DISPATCH_RECEIPT` across Codex thread metadata and rollout logs.

## Command

```bash
python3 scripts/audit_historical_threads.py --repo-root . --scan-rollouts --output /tmp/HISTORICAL_THREAD_AUDIT_RECEIPT_current.json
```

Fixture coverage is wired into `scripts/quality_gate.sh`:

```bash
python3 scripts/audit_historical_threads.py --repo-root . --fixture evals/history_threads.sample.json --output <tmp>/HISTORICAL_THREAD_AUDIT_RECEIPT.json
```

## Local Result

Summary from `/tmp/HISTORICAL_THREAD_AUDIT_RECEIPT_current.json`:

```json
{
  "matching_threads": 83,
  "cross_project_threads": 63,
  "missing_cwd_threads": 25,
  "issue_categories": {
    "activation_missing_or_unproven": 6,
    "cross_project_routing_requires_agents_snippet": 63,
    "history_audit_not_triggered": 3,
    "main_thread_self_execution_complaint": 29,
    "nonconverged_evidence_must_be_rejected": 46,
    "pending_worktree_not_thread_id": 82,
    "thread_cwd_missing_requires_archive_or_rehome": 25,
    "title_receipt_metadata_requires_readback": 82
  }
}
```

Latest local refresh after cross-project Chinese routing sync:

```json
{
  "generated_at": "2026-07-05T08:55:07Z",
  "matching_threads": 91,
  "cross_project_threads": 64,
  "missing_cwd_threads": 28,
  "issue_categories": {
    "activation_missing_or_unproven": 6,
    "cross_project_routing_requires_agents_snippet": 64,
    "history_audit_not_triggered": 3,
    "main_thread_self_execution_complaint": 29,
    "nonconverged_evidence_must_be_rejected": 49,
    "pending_worktree_not_thread_id": 90,
    "thread_cwd_missing_requires_archive_or_rehome": 28,
    "title_receipt_metadata_requires_readback": 90
  },
  "latest_review_thread": {
    "thread_id": "019f317c-5ec1-7c42-b5bc-dfa4438f3bed",
    "archived": true,
    "receipt": "CROSS_PROJECT_ROUTING_REVIEW_RECEIPT",
    "verdict": "PASS"
  }
}
```

Top matched projects:

- `/Users/jinjungao/work/ad-creative-orchestrator`: 23 threads.
- `/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf`: 20 threads.
- `/Users/jinjungao/work/DIR SKILL`: 7 threads.

## Findings

1. Historical evidence cannot be trusted from thread title or worker self-report alone. Several runs contain title changes or title-blocked states, so current release evidence must use thread metadata/readback.
2. `pendingWorktreeId` appears frequently in historical traces. It is not a worker `thread_id`; it only means dispatch is pending until a real thread appears.
3. Many early review/council threads contain `thread_not_converged`. Those runs are rejected evidence unless a later bounded rescue receipt exists.
4. Missing `cwd` / removed worktree now appears as a first-class category. A Codex thread that shows "current working directory missing" must be archived or marked `cleanup_blocked`, rejected as evidence, and replaced in a live project/worktree if work remains.
5. Cross-project usage is common. Installing the Skill globally does not guarantee a project will route through COS automatically; projects that need default routing must include `references/AGENTS_ROUTING_SNIPPET.md` in their `AGENTS.md`.
6. The `ad-creative-orchestrator` history shows the realistic failure shape: the Skill can be used as orchestration guidance while the actual project still needs explicit local gates, worker scope, thread metadata, and adoption/cleanup proof.

## Adopted Fix

- Added `scripts/audit_historical_threads.py` for local historical auditing.
- Added `evals/history_threads.sample.json` and quality-gate fixture checks for the six recurring failure modes.
- Added `evals/activation_contract.fixture.json` so `TOOL_BLOCKED`, `pendingWorktreeId`, and same-thread simulation are checked as output-level contract cases.
- Added historical audit rules to `SKILL.md` and `references/ACTIVATION_PROTOCOL.md`.
- Added README usage so users can reproduce the audit without exposing raw thread text.
- Added `thread_cwd_missing_requires_archive_or_rehome` classification, activation fixtures, and quality-gate checks after the ADCO missing-worktree screenshot exposed that archived temporary worker threads can look like broken projects when reopened.

## Adversarial Review

- History audit thread `019f2dc4-386c-7811-a259-3c04bbd87423`: returned `HISTORY_AUDIT_RECEIPT`; found P0 cross-project implicit startup failures and P0 main-thread self-execution risk in ADCO/DIR-style cases, plus P1 pending worktree, non-converged review, and title/readback risks.
- Gate audit thread `019f2dc4-3ff7-7381-9e06-1ee6a0f1f4be`: returned `GATE_AUDIT_RECEIPT`; verdict `warn`, no blocker. It challenged static grep-heavy gates and recommended output-level fixtures for `TOOL_BLOCKED`, `pendingWorktreeId`, same-thread simulation, and cross-project routing.
- Release audit thread `019f2dc4-46ff-71a0-8357-bdbd242a5006`: returned `RELEASE_AUDIT_RECEIPT`; verdict `GO_WITH_NON_BLOCKING_FIXES`. It recommended clearer activation-path docs and a fixed `TOOL_BLOCKED` example.

Adoption:

- Accepted: local historical audit script, fixture-backed quality gate, output-level activation fixture, README activation-path wording, and `TOOL_BLOCKED`/pending worktree example.
- Rejected for this patch: a live CI smoke that creates real Codex Threads. Public CI does not have Codex Desktop thread tools, so the correct gate is deterministic fixture validation plus local live audit evidence.

## Residual Risk

The local audit reads this machine's Codex history. It should not be used as public proof for other users' machines. Public CI validates the classifier against a fixture; local release readiness should additionally run the live audit command above when historical behavior is in scope.
