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

`no_dispatch` is allowed only for T0/T1 work when the user did not ask for real threads, or when the user explicitly forbids child threads. Release/pre-release quality, public sharing, multi-file reliability, and multi-risk audits involving assets, stale files, browser-held evidence, customer-facing language, validation commands, or cleanup are T3+ and must dispatch or report `TOOL_BLOCKED`.

`thread_dispatch_decision: dispatch` is an immediate dispatch commitment, not a plan. After emitting `COS_BOOT_RECEIPT`, the Chief-of-Staff must do one of these before any implementation, review, or summary work:

1. Use real Codex Thread tools and emit `THREAD_DISPATCH_RECEIPT`.
2. If thread tools are not callable after one tool-discovery attempt, emit `TOOL_BLOCKED` and stop same-thread execution.

An output that says `thread_dispatch_decision: dispatch` but never emits `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED` is `thread_not_converged` evidence, not a successful activation.

## Dispatch Visibility Rule

`THREAD_DISPATCH_RECEIPT` is both evidence and user-facing status. Do not show it as a raw English/YAML field dump.

Every visible dispatch must start with a Chinese dispatch card before the machine fields:

````markdown
THREAD_DISPATCH_RECEIPT：已派发真实执行线程

派发摘要
| 项目 | 内容 |
|---|---|
| 工作线程 | `019f...` |
| 职责 | 开发执行 / 审查 / 救援 / 侦察 worker |
| 读取范围 | 中文说明 |
| 写入范围 | 中文说明 |
| 预期回执 | `WORKER_RECEIPT` |
| 身份契约 | 已写入 worker 自己的 thread_id |
| 收尾方式 | 回执后归档 / 保留原因 / cleanup 阻塞 |
| 当前状态 | 已派发 / 等待 worktree 创建 |

机器凭证：
```yaml
THREAD_DISPATCH_RECEIPT:
  thread_id: "019f..."
  ...
```
````

The machine-readable YAML can stay, but only after the Chinese card and under a "机器凭证" label. If the output only shows fields such as `thread_id`, `thread_class`, `read_scope`, `write_scope`, `expected_receipt`, and `status`, it is not human-readable enough even when the receipt is technically valid.

Every dispatched worker must then enter bounded receipt polling:

1. Default `worker_receipt_poll_limit: 3`.
2. Default `worker_receipt_poll_interval_seconds: 60`; complex tasks also get `worker_startup_grace_seconds: 120` before they can be declared stuck.
3. Use `read_thread`, `list_threads`, or equivalent metadata to check whether the worker produced the expected receipt/artifact. Do not burn all three polls back-to-back.
4. If the worker is newly created, actively starting up, or showing fresh tool/search/build activity, record `receipt_status: active_no_receipt_yet` with the next poll time; do not declare `thread_not_converged` yet.
5. If a worker has no expected receipt by the limit and the grace/timeout budget is exhausted, record `thread_not_converged`, archive it or record `cleanup_blocked`, and dispatch a bounded rescue worker.
6. A repeated “still waiting” status without `receipt_status`, remaining polls, next poll time, or rescue action is not convergence evidence.
7. If the bounded rescue worker also reaches the receipt limit, the Chief-of-Staff must not switch to same-thread implementation in the COS worktree. Record `thread_not_converged` plus cleanup status, then either dispatch another explicitly budgeted rescue, emit `NEEDS_HUMAN`, or emit `TOOL_BLOCKED`.
8. If Codex UI, `read_thread`, or `list_threads` shows "当前工作目录缺失", `current working directory missing`, `cwd_missing`, `worktree_missing`, or a `cwd` / associated worktree path that no longer exists, stop using that worker immediately. Record `thread_cwd_missing`, `thread_not_converged`, `adoption_status: rejected_evidence`, and `cleanup_status: archived | cleanup_blocked`. Do not send follow-up prompts to the missing-cwd thread and do not adopt old diffs from it; if work remains, re-dispatch in a live project-bound thread or fresh isolated worktree.
9. A worker must not self-heal a missing Codex worktree. If its own `cwd`/worktree is missing, the only valid output is a `BLOCKED` / `TOOL_BLOCKED` receipt with no file changes. A receipt claiming "isolated worktree was missing, so I created it from main HEAD" is invalid adoption evidence.

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

Do not fabricate placeholder ids. `thread_id: "pending"`, `thread_id: "unknown"`, `thread_id: "TBD"`, `thread_id: "same-thread"`, and empty placeholder ids are invalid dispatch evidence. If a title update has not happened yet, record `title_update_blocked`; do not invent `dispatcher_set_pending` or `title_pending`.

## Project-Bound Execution Rule

The Chief-of-Staff thread is a coordinator, not an execution surface. Except for T0/T1 lightweight status replies, or a read-only task where the user explicitly forbids workers, the main COS must not run tests, gates, process cleanup, file edits, implementation work, or operational cleanup directly.

Cross-project work must execute in the target project context. The source COS may dispatch, read back, adopt, reject, and archive, but it must not run target project gates or modify target project files from the source thread. Dispatch to the target project's main COS when that project already has one; otherwise dispatch a target project-bound worker with explicit read/write scope.

Self-improvement of this Skill is also project-bound execution. Changes to `SKILL.md`, `assets/`, `references/`, `scripts/`, validation, tests, or release gates must be done by a Skill维护-SKM / DEV worker. The main COS can record the issue and adoption decision, but cannot self-patch.

If the main COS has already produced direct execution evidence such as `commands_run`, `changed_files`, `git diff --check`, `quality_gate.sh`, `release_smoke.sh`, `validate_project.py`, `ps`, or `kill`, treat it as `cos_main_overexecution`. That evidence may guide a rescue worker, but it is not completion evidence unless a project-bound worker receipt and adoption/rejection record confirms it.

## Role-Specific Worker Bypass

Chief-of-Staff routing must not consume the workers it creates.

If the current prompt is explicitly addressed to a role-specific worker such as 审查官-REV, 执行线程/开发执行-DEV, 技能侦察-SKS, Agent侦察-AGS, 救援官-RSC, 合成官-SYN, or Skill维护-SKM, and it contains `COS_WORKER_BYPASS: true` or equivalent instructions like "do not act as Chief-of-Staff", "do not re-dispatch", and "output the requested packet/receipt directly", then this is not a Chief-of-Staff activation.

Required worker behavior:

1. Do not output `COS_BOOT_RECEIPT`.
2. Do not re-classify the task.
3. Do not create more threads unless the worker role explicitly requires a Delegation Packet.
4. Run the requested read/write/check work within its scope.
5. Output the requested Result Packet, Review Packet, or named `*_RECEIPT`.

If a role-specific worker only emits `COS_BOOT_RECEIPT` or stops at `thread_dispatch_decision: no_dispatch` without the requested worker receipt, the coordinator must record:

```yaml
thread_not_converged:
  reason: role_specific_worker_booted_cos_instead_of_executing
adoption_status: rejected_evidence
cleanup_status: archived | cleanup_blocked
```

Then dispatch a bounded rescue worker with the same bypass marker, or report `TOOL_BLOCKED` / `NEEDS_HUMAN` if rescue also fails.

If a role-specific worker emits the requested receipt but the receipt `thread_id` is not the worker's own Codex thread id read back from metadata, record `receipt_status: invalid_worker_thread_id` and `adoption_status: rejected_evidence`. A common invalid case is copying `source_thread_id` or the Chief-of-Staff/main thread id into the worker receipt. The content may be used as an untrusted clue only after independent verification; it is not completion evidence.

Dispatch prompts must reduce this failure mode before it happens. After a worker thread is created or read back, the dispatcher must include the worker's actual id in the worker prompt:

```text
COS_WORKER_BYPASS: true
你的真实 thread_id 是 <worker_thread_id>。
receipt.thread_id 必须等于 <worker_thread_id>。
不要填写 source_thread_id、主线程 ID 或历史线程 ID。
```

The matching `THREAD_DISPATCH_RECEIPT` should record `worker_prompt_identity_contract: included`. If the worker id is not known yet because only a `pendingWorktreeId` exists, use `worker_prompt_identity_contract: pending_until_thread_id_known` and do not count the dispatch as converged.

Heartbeat note: Codex automations execute the automation prompt. They do not automatically load this Skill just because the Skill contains Heartbeat rules. To make a heartbeat run the Chief-of-Staff flow, include `使用 $zhijuan-codex-agency-chief-of-staf` in the automation prompt or install the AGENTS routing shim in the heartbeat target project/thread context. A prompt that says "do nothing else" must not be rewritten by the Skill into a COS run.

Heartbeat/Automation contract:

1. A heartbeat automation prompt that explicitly invokes this Skill must produce `COS_BOOT_RECEIPT` before any heartbeat analysis.
2. If that heartbeat is T4/T5, `thread_dispatch_decision` must be `dispatch` or `tool_blocked`; `no_dispatch` is invalid unless the user explicitly forbids child threads.
3. A plain emitter heartbeat such as "Send exactly one plain text message ... Do nothing else" is not a COS activation and should not emit `COS_BOOT_RECEIPT`.
4. A claim that Heartbeat/Automation is enabled must include evidence: `automation_prompt` text/path plus `prompt_contains_skill_invocation: true`, or explicit `agents_routing_evidence` / `AGENTS routing shim`. A bare `AGENTS.md` mention, or "未检查 AGENTS.md / 没有 prompt evidence", is invalid.
5. A claim that Heartbeat/Automation is enabled must also verify the target context: include `target_thread_id`, `target_thread_verified: true`, and at least one readback field such as `target_thread_title` or `target_thread_cwd`. If the target points at an unrelated historical thread, the heartbeat is misconfigured even when the prompt itself invokes this Skill.
6. Automation enablement is not run evidence. Every T4/T5 heartbeat run must output `HEARTBEAT_RUN_RECEIPT` or `COS_HEARTBEAT_RUN_RECEIPT` with target thread id/readback, `current_due_status`, `dispatch_required`, `dispatch_outcome`, `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED`, stuck/rescue decision, and `next_due_or_next_check`.
7. If `dispatch_required: true` but the heartbeat cannot dispatch a worker, the run receipt must say `dispatch_outcome: tool_blocked` with `TOOL_BLOCKED`, or `dispatch_outcome: thread_not_converged` with `thread_not_converged`. "Heartbeat active" without run receipt and dispatch outcome is invalid.
8. `target_thread_verified: false`, `unknown`, blank values, or "未验证" text are invalid run evidence. If the heartbeat cannot verify the target thread, record `current_due_status: unknown | misconfigured` and a blocking outcome instead of filling `target_thread_id` with a `source_thread_id`, historical main thread id, or guess.
9. Natural heartbeat acceptance must respect the due window. If `current_time` is before the configured `next_natural_due_at_local`, the acceptance verdict is `NOT_DUE`; do not classify a user-triggered or in-progress target-thread turn as heartbeat `FAIL`. Only after the due window may missing `COS_HEARTBEAT_RUN_RECEIPT` become `FAIL` / `thread_not_converged`.
10. Automation lifecycle is part of the run contract. A due heartbeat must dispatch, dispatch pending, report `TOOL_BLOCKED`, or record `thread_not_converged`; a due heartbeat with no dispatch is invalid. If the run finds a repeated failure mode or claims an in-flight fix, it must record a bounded self-improvement/SKM patch path. If the automation goal is complete, it must delete or pause the automation and record self-recycle evidence.

Machine-readable heartbeat run receipt:

```yaml
COS_HEARTBEAT_RUN_RECEIPT:
  target_thread_id: ""
  target_thread_verified: true
  target_thread_title: ""
  target_thread_cwd: ""
  current_due_status: due_now | not_due | overdue | misconfigured | unknown
  dispatch_required: true | false
  dispatch_outcome: dispatched | dispatch_pending | tool_blocked | thread_not_converged | not_required_not_due | not_required_goal_complete | not_required_user_forbid_threads
  thread_dispatch_receipt: THREAD_DISPATCH_RECEIPT | not_applicable | not_available_due_to_TOOL_BLOCKED
  stuck_rescue_decision: none | monitor_next_check | dispatch_rescue | rescue_blocked | not_started_due_to_tool_blocked
  self_improvement_status: not_needed | needed | patch_proposed | patched | blocked
  self_improvement_path: not_applicable | assets/SELF_IMPROVEMENT_TEMPLATE.md | assets/PATCH_PROPOSAL_TEMPLATE.md | Skill维护-SKM | TOOL_BLOCKED
  self_improvement_evidence: ""
  self_recycle_status: not_complete | deleted | paused | blocked
  self_recycle_evidence: ""
  next_due_or_next_check: ""
```

## AGENTS.md Shim

Skills are on-demand. For users who want the Chief-of-Staff routing to be the default behavior in a project, add the snippet from `references/AGENTS_ROUTING_SNIPPET.md` to the project `AGENTS.md` or global `~/.codex/AGENTS.md`.

The installer does not modify `AGENTS.md` by default. Use `python3 scripts/install_skill.py --agents-routing project --project-root /path/to/project`, `--agents-routing global`, or `--agents-routing both` when the user explicitly wants the routing shim installed.

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
- `source_cos_direct_target_execution`: source COS ran target project gates or edits instead of dispatching to target project main COS / project-bound worker.
- `cos_main_overexecution`: main COS produced `commands_run`, `changed_files`, process cleanup, or gate evidence and tried to count it as completion.
- `thread_cwd_missing_requires_archive_or_rehome`: a thread's recorded cwd/worktree is gone or Codex reports "current working directory missing"; it must be archived or marked cleanup_blocked and replaced in a live project/worktree before work continues.

For cross-project use, add `references/AGENTS_ROUTING_SNIPPET.md` to the project where the work actually runs, or install it with `scripts/install_skill.py --agents-routing project --project-root /path/to/project`. Installing the Skill bundle alone is not enough to guarantee that every future project route starts with the COS boot contract.
