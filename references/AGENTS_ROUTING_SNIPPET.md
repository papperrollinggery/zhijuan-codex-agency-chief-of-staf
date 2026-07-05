# AGENTS.md Routing Snippet

Copy this into a project `AGENTS.md` or global `~/.codex/AGENTS.md` when the Chief-of-Staff workflow should be the default routing layer.

```markdown
## Codex Agency Chief of Staff Routing

When the user asks for 幕僚长, Codex Agency, 完整团队, 真实 Codex Threads, worker thread, another thread, thread id, receipt, cleanup, Plan/Goal orchestration, 自动调度, 反驳审核, 线程卡住, release readiness, public repository publishing, reusable Skill hardening, multi-file reliability validation, or a complex task that should be managed rather than directly executed, use `$zhijuan-codex-agency-chief-of-staf`.

Exception: if the current prompt is a role-specific worker assignment for 审查官-REV, 执行线程/开发执行-DEV, 技能侦察-SKS, Agent侦察-AGS, 救援官-RSC, 合成官-SYN, or Skill维护-SKM and it contains `COS_WORKER_BYPASS: true` or explicitly says not to act as Chief-of-Staff / not to re-dispatch / to output the requested packet or receipt directly, do not use the Chief-of-Staff Skill. Execute that worker role directly and return the requested packet or receipt. A worker that only emits `COS_BOOT_RECEIPT` without the requested worker receipt is not converged.

If `$zhijuan-codex-agency-chief-of-staf` is used or clearly implied, the first visible output must include `COS_BOOT_RECEIPT` before any task execution.

用户可见输出必须中文优先、简洁、先给结论。保留 `COS_BOOT_RECEIPT` 机器标记；小型直接答复、状态说明、用户只是问“为什么/什么情况/是否受阻/怎么显示”时，必须使用中文紧凑行，例如：`COS_BOOT_RECEIPT：已启动；复杂度 T0；不派发；原因：状态说明。` 不要展开 `skill_loaded`、`trigger_type`、`thread_role` 这类英文键值表。

For release/pre-release quality, public sharing, multi-file reliability, or multi-risk project audits involving assets, stale files, browser-held evidence, customer-facing language, validation commands, or cleanup, classify the task as T3+ and set `thread_dispatch_decision: dispatch` unless the user explicitly forbids worker threads. 这些高风险场景不要只用中文紧凑行；必须先用中文说明结论，再包含 Skill 模板里的完整机器字段。

If the user explicitly requests real Codex Threads, worker threads, a complete team, thread id, receipt, or cleanup, create real Codex Threads with thread tools and output `THREAD_DISPATCH_RECEIPT`. If those tools are unavailable, report `TOOL_BLOCKED`. Do not substitute subagents, role-play, or same-thread simulation.

`THREAD_DISPATCH_RECEIPT` 用户可见时必须先输出中文“派发摘要”卡片，至少包含工作线程、职责、读取范围、写入范围、预期回执、身份契约、收尾方式、当前状态；机器 YAML 只能放在摘要之后并标注“机器凭证”。不要只展示英文键值表。

For tiny direct-answer tasks, keep the result light. If the Skill was explicitly invoked, still output a compact `COS_BOOT_RECEIPT` and record `thread_dispatch_decision: no_dispatch`.
```
