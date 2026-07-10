# Historical Task and Thread Audit

在用户询问旧 task/thread 是否真实执行、是否卡住、cwd/worktree 缺失、receipt 身份或 cleanup 时读取本文件。

## 当前事实优先

按以下证据顺序核验：

1. 当前可用的 `read_thread`、`list_threads` 或 task 元数据。
2. 当前系统的 thread/task 数据库和 rollout/event 日志。
3. artifact、git 状态、命令输出和文件 hash。
4. worker receipt，经 id 和 scope 交叉验证后使用。
5. sidebar 状态、标题和自述只作线索。

不要因为 sidebar 显示 active/idle/spinning 就判断真实执行状态。

## 常见失效

- 只有 pending worktree id，没有真实 thread id。
- receipt 填了主线程、source thread 或历史 id。
- worker 的 cwd/worktree 已删除。
- worker 只有计划或启动标记，没有 artifact。
- 旧验证来自不同 commit 或不同安装 bundle。
- cleanup 自述没有工具 readback。

## 处置

1. 完成且证据有效：采纳结果，并按授权归档。
2. 完成但 id/scope 不一致：把内容当线索，重新核验后再决定采纳。
3. 仍有活动：根据实际 tool/build/search 活动继续等待，不按固定间隔误判。
4. 无进展：一次定向 follow-up；仍无结果则 replacement/rescue。
5. cwd/worktree 缺失：停止向旧 thread 发送消息，拒绝其旧自述作为当前证据；需要继续时创建新执行面。

仓库中的 `scripts/audit_historical_threads.py` 可以生成本地诊断 receipt，但它的输出仍需与当前 task/thread readback 交叉验证，不能单独作为完成证明。
