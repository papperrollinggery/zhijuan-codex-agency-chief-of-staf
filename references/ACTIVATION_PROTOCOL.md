# Activation Protocol

Use this reference when a run does not clearly start the Chief-of-Staff flow, or when the user asks why the Skill did not dispatch threads.

## Why Activation Can Fail

1. Codex skills are selected through progressive disclosure. Before a skill is selected, Codex normally sees only `name`, `description`, path, and optional metadata.
2. If `agents/openai.yaml` sets `policy.allow_implicit_invocation: false`, natural-language triggers do not activate the Skill. Explicit `$skill` invocation should still work, but local discovery bugs can still affect some Codex surfaces.
3. A process-heavy description can become a shortcut: Codex may follow the summary instead of reading the full Skill body. Keep the description trigger-focused.
4. Anti-bureaucracy rules for T0/T1 can be misread as permission to skip Chief-of-Staff boot. They are only permission to skip heavy artifacts, not permission to skip `COS_BOOT_RECEIPT` after explicit invocation.

Skill 描述只能提高选择概率. It cannot force every future complex task into the Chief-of-Staff path, because the Skill body is not guaranteed to be loaded before selection. If a project requires default routing, put `references/AGENTS_ROUTING_SNIPPET.md` into that project's `AGENTS.md`; then the route exists in the instruction chain before task execution.

## Hard Boot Rule

When the Skill is explicitly invoked, the first visible output must contain `COS_BOOT_RECEIPT`. Do not answer, implement, review, draw, publish, or summarize before this receipt.

Use `assets/COS_BOOT_RECEIPT_TEMPLATE.yaml`.

## Dispatch Rule

If the user explicitly asks for any of these:

- real Codex Threads
- worker thread
- complete team
- another thread / new thread
- isolated worktree
- thread id
- receipt
- cleanup

Then `thread_dispatch_decision` must be `dispatch` or `tool_blocked`. It must not be `no_dispatch`.

`no_dispatch` is allowed only when the user did not ask for real threads, or when the user explicitly forbids child threads.

When thread tools are unavailable, the correct output is explicit blockage, not simulation:

```yaml
COS_BOOT_RECEIPT:
  skill_loaded: true
  trigger_type: explicit
  thread_role: COS
  thread_tools_available: false
  thread_dispatch_decision: tool_blocked
  reason: "User asked for real Codex Threads but thread tools are unavailable."

TOOL_BLOCKED:
  required_tool: "create_thread/read_thread/set_thread_archived"
  fallback_allowed: false
```

If a tool returns only `pendingWorktreeId`, record `status: dispatch_pending` and wait for a real `thread_id`. `pendingWorktreeId` must never appear in a `THREAD_DISPATCH_RECEIPT` with `status: dispatched`.

## AGENTS.md Shim

Skills are on-demand. For users who want the Chief-of-Staff routing to be the default behavior in a project, add the snippet from `references/AGENTS_ROUTING_SNIPPET.md` to the project `AGENTS.md` or global `~/.codex/AGENTS.md`.

This does not override system/developer instructions or missing tools. It only makes the routing rule part of the instruction chain before task work begins.

## Historical Thread Audit

When a user asks whether previous runs used this Skill correctly, inspect history as evidence, not vibes.

Recommended command:

```bash
python3 scripts/audit_historical_threads.py --repo-root . --scan-rollouts --output /tmp/HISTORICAL_THREAD_AUDIT_RECEIPT.json
```

Evidence hierarchy:

1. Codex thread metadata from `state_5.sqlite`, `list_threads`, or `read_thread`.
2. Rollout JSONL entries that show actual tool calls, outputs, and final messages.
3. Worker receipts only after matching `thread_id`, scope, commands, adoption/rejection, and cleanup.
4. Sidebar titles and worker self-report only as hints.

Historical failure categories to look for:

- `activation_missing_or_unproven`: explicit Skill or 幕僚长 trigger without a visible `COS_BOOT_RECEIPT`.
- `dispatch_missing_or_unproven`: real-thread request without `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED`.
- `pending_worktree_not_thread_id`: `pendingWorktreeId` was treated as a ready worker thread.
- `nonconverged_evidence_must_be_rejected`: stuck or interrupted review threads were counted as approval.
- `title_receipt_metadata_requires_readback`: title, receipt, or cleanup claims were not verified through metadata/readback.
- `release_review_budget_missing`: review waves kept expanding without `max_review_waves`, `max_parallel_reviewers_per_deliverable`, or `add_review_wave_reason`.
- `release_receipt_fragmented`: dispatch, adoption/rejection, cleanup, and review verdict were scattered across worker replies instead of a single release receipt.
- `history_audit_not_triggered`: user challenged missing archive, fake execution, or skipped Skill flow, but the run did not enter historical thread audit.
- `cross_project_routing_requires_agents_snippet`: the Skill was referenced from another project without a local routing shim.

For cross-project use, add `references/AGENTS_ROUTING_SNIPPET.md` to the project where the work actually runs. Installing the Skill globally is not enough to guarantee that every future project route starts with the COS boot contract.
