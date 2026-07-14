# Real Codex Tasks and Threads

只在用户明确要求真实 task/thread、独立 sidebar 任务、隔离 worktree、thread id、receipt 或 cleanup 证明时读取本文件。

## 区分执行面

- `native subagent`：当前任务内部的并行专职代理。适合探索、测试、审查和无冲突实现。
- `Codex task/thread`：用户可在产品中独立查看、继续、归档的真实任务。
- `isolated worktree task`：拥有独立 Git checkout 的可写任务。

三者都可能在 UI 中显示 agent 活动，但不能在用户明确要求某一种时用另一种冒充。

## 派发前

1. 确认当前环境提供真实 task/thread 工具。
2. 明确目标项目、读取范围、写入范围、完成标准和收尾方式。
3. 写任务使用隔离 worktree；只读任务可共享目录。
4. 先检查是否已有同目标任务，避免重复派发。

如果工具不可用：

```text
TOOL_BLOCKED：缺少真实 Codex task/thread 或 isolated worktree 能力；未用 subagent 或同线程模拟替代。
```

用户明确要求真实线程而工具不可用时，停止并请求新的执行面。只有用户同时明确授权无真实线程 fallback 时，才可继续普通工作；不得自行把 subagent 当作等价替代。

## 派发与身份

使用工具返回的真实 id。不要填写 `pending`、`unknown`、`same-thread`、主线程 id 或猜测值。

给 worker 的 prompt 必须逐行且仅包含：

```text
AGENCY_WORKER: true
委派目标：<objective>。
读取范围：<read scope>。
写入范围：<write scope>。
期望产物：<实际读回字段与终态 schema>。
验证要求：<checks and evidence>。
停止条件：返回唯一终态；不启动、不派发。
```

工具只返回 pending worktree id 时，状态只能是 `dispatch_pending`。等真实 task/thread id 可读回后再记为 `dispatched`。

## 读回与收敛

1. 用 task/thread readback 检查真实状态、cwd/worktree、最新活动和产物。
2. 根据工具活动判断等待，不使用写死的三次轮询或固定 60 秒间隔。
3. worker 无进展时先发一次定向 follow-up；仍不收敛再 replacement/rescue。
4. receipt 的 id 必须等于工具读回的 worker id；不一致时拒绝该证据。
5. 主线程独立核验 artifact 和验证命令后，记录 `adopted`、`partially_adopted` 或 `rejected`。

若 cwd/worktree 已不存在：停止向该 worker 发消息，标记 `thread_cwd_missing`，拒绝旧自述作为当前完成证据；工作仍需继续时创建新的合法执行面。

## Cleanup

完成、失败或替换后的用户拥有 task/thread，按用户要求和工具能力归档；不可归档时记录 `cleanup_blocked`。不要删除含未采纳改动的 worktree。

只有机器审计需要时才使用 [assets/WORK_RECEIPT_TEMPLATE.yaml](../assets/WORK_RECEIPT_TEMPLATE.yaml)。收据只能证明当前 source、安装包和持久化记录；没有专项前后快照时，历史写入与 AGENTS 状态必须标记为未验证。日常用户更新优先用中文短句。
