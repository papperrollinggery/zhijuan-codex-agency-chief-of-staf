# AGENTS.md Routing Snippet

Copy this into a project `AGENTS.md` or global `~/.codex/AGENTS.md` when the Chief-of-Staff workflow should be the default routing layer.

```markdown
## Codex Agency Chief of Staff Routing

When the user asks for 幕僚长, Codex Agency, 完整团队, 真实 Codex Threads, worker thread, another thread, thread id, receipt, cleanup, Plan/Goal orchestration, 自动调度, 反驳审核, 线程卡住, or a complex task that should be managed rather than directly executed, use `$zhijuan-codex-agency-chief-of-staf`.

If `$zhijuan-codex-agency-chief-of-staf` is used or clearly implied, the first visible output must include `COS_BOOT_RECEIPT` before any task execution.

If the user explicitly requests real Codex Threads, worker threads, a complete team, thread id, receipt, or cleanup, create real Codex Threads with thread tools and output `THREAD_DISPATCH_RECEIPT`. If those tools are unavailable, report `TOOL_BLOCKED`. Do not substitute subagents, role-play, or same-thread simulation.

For tiny direct-answer tasks, keep the result light. If the Skill was explicitly invoked, still output a compact `COS_BOOT_RECEIPT` and record `thread_dispatch_decision: no_dispatch`.
```
