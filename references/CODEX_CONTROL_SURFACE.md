# Codex Control Surface

可调度能力：

- /plan：前期计划
- /goal：长期目标
- /review：代码审查
- /skills：Skill 选择
- /mcp：工具连接
- /mention：指定文件/文件夹
- /agent：查看或切换线程/agent 上下文
- /fork：分支探索
- /side：临时旁路问题
- /compact：压缩上下文
- /diff：查看变更
- /ps：查看后台命令
- /stop：停止后台命令
- /model：选择模型
- /fast：低风险快速任务
- /status：检查上下文和配置
- worktree：并行隔离
- automation：定时巡检
- AGENTS.md：项目长期规则
- Memories：偏好和经验
- Skills：可复用能力
- COS boot receipt：显式调用 Skill 后首个用户可见输出必须包含 `COS_BOOT_RECEIPT`
- Codex Threads：真实 worker thread、隔离 worktree、receipt、cleanup
- Codex thread title tools：`set_thread_title` 或等价能力；COS 启动时用于当前线程自命名，调度层创建或复用 thread 后必须用它兜底落实派发标题，并通过 `read_thread` / `list_threads` 元数据核验
- Subagents：仅在用户未要求真实 Codex Threads、且任务不需要 thread id/receipt/cleanup 证明时作为轻量专职代理
- MCP/Plugins：外部工具

## 显式线程请求门

当用户明确要求 Codex Threads、真实 worker thread、完整团队、另一个线程、新线程、isolated worktree、thread id、receipt 或 cleanup：

```text
合法结果只有：
1. 使用真实 Codex Threads 工具派发，并输出 THREAD_DISPATCH_RECEIPT。
2. 工具或 isolated worktree 能力不可用时，输出 TOOL_BLOCKED 并停止。
```

禁止把 subagent、同线程角色扮演、read-only review thread、普通多代理工具或主线程直接实现当作真实 Codex Threads。
