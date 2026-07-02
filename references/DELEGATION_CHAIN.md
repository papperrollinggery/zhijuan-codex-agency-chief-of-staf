# Delegation Chain

子线程可以推动下一步，但必须通过 Delegation Packet。

当用户明确要求 Codex Threads、真实 worker thread、隔离 worktree、thread id、receipt 或 cleanup 时：

```text
必须使用真实 Codex Thread 工具。
不能用 subagent、同线程角色扮演或只读 review thread 代替 execution worker。
派发记录必须包含 thread_id、thread_class、read_scope/write_scope、预期 receipt、cleanup 方式。
worker receipt 必须被幕僚长明确 adoption 或 rejection。
worker 完成、失败或不收敛后必须归档，或记录 cleanup 未完成及原因。
工具不可用时报告 TOOL_BLOCKED，不得静默降级。
```

允许：

```text
Planner → Reviewer → Developer → Reviewer → Synthesizer → Chief of Staff
```

禁止：

```text
子线程无限递归开线程
跳过 Reviewer
跳过 Goal
跳过 Task Card
幕僚长亲自做审核
```
