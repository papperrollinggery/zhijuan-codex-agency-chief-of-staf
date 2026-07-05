<!-- BEGIN zhijuan-codex-agency-chief-of-staf routing -->
## Codex Agency Chief of Staff Routing

When the user asks for 幕僚长, Codex Agency, 完整团队, 真实 Codex Threads, worker thread, another thread, thread id, receipt, cleanup, Plan/Goal orchestration, 自动调度, 反驳审核, 线程卡住, release readiness, public repository publishing, reusable Skill hardening, multi-file reliability validation, or a complex task that should be managed rather than directly executed, use `$zhijuan-codex-agency-chief-of-staf`.

Exception: if the current prompt is a role-specific worker assignment for 审查官-REV, 执行线程/开发执行-DEV, 技能侦察-SKS, Agent侦察-AGS, 救援官-RSC, 合成官-SYN, or Skill维护-SKM and it contains `COS_WORKER_BYPASS: true` or explicitly says not to act as Chief-of-Staff / not to re-dispatch / to output the requested packet or receipt directly, do not use the Chief-of-Staff Skill. Execute that worker role directly and return the requested packet or receipt. A worker that only emits `COS_BOOT_RECEIPT` without the requested worker receipt is not converged.

If `$zhijuan-codex-agency-chief-of-staf` is used or clearly implied, the first visible output must include `COS_BOOT_RECEIPT` before any task execution.

For release/pre-release quality, public sharing, multi-file reliability, or multi-risk project audits involving assets, stale files, browser-held evidence, customer-facing language, validation commands, or cleanup, classify the task as T3+ and set `thread_dispatch_decision: dispatch` unless the user explicitly forbids worker threads. Do not compress `COS_BOOT_RECEIPT`; include the full fields from the Skill template.

If the user explicitly requests real Codex Threads, worker threads, a complete team, thread id, receipt, or cleanup, create real Codex Threads with thread tools and output `THREAD_DISPATCH_RECEIPT`. If those tools are unavailable, report `TOOL_BLOCKED`. Do not substitute subagents, role-play, or same-thread simulation.

For tiny direct-answer tasks, keep the result light. If the Skill was explicitly invoked, still output a compact `COS_BOOT_RECEIPT` and record `thread_dispatch_decision: no_dispatch`.
<!-- END zhijuan-codex-agency-chief-of-staf routing -->
