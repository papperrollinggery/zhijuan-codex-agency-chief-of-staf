# Task Archive and Knowledge Deposit

归档是完成验证后的收口动作，不是把 active 文件夹换个位置。长期知识沉淀是归档后的独立筛选动作，不复制整个执行清单。

## 归档前置条件

正常 completed 归档必须同时满足：

- 所有 Required Work Item 为 completed，或带明确 waiver reason 的 waived。
- 每项 Acceptance Criterion 都有当前 evidence refs。
- 没有未处理 Work Item blocker。
- Team Plan 选了 Reviewer 时，Review 已处理并有证据。
- 真实 Task/Thread 已关闭；无法关闭时记录具体 `cleanup_blocked`，不能伪造 cleanup。
- 交付产物路径仍存在、留在项目内且不是 symlink。
- 至少一项当前 validation result 为 passed；失败结果不能当完成证据。

不满足时不得归档为 completed。用户明确决定取消或由新任务替代时，可以在记录 `status_reason` 后按 cancelled 或 superseded 处置；它们不会被改写成 completed，真实未解决 blocker 会原样保留在 task plan、报告和 manifest，而不是为了归档被清空。

正常完成优先复用 `scripts/complete_task.py --apply` 生成的当前 `closure.json`；只有兼容旧任务时才由调用方另行提供 closure。它集中记录 review、cleanup、validation 和 artifact 证据，避免手工维护重复状态。

`archive_task.py` 默认只预检，明确 `--apply` 才移动目录：

```text
.agency/tasks/archive/YYYY/MM/<task-id>/
├── ARCHIVE_REPORT.md
├── archive-manifest.json
└── knowledge-candidates.json
```

归档先在同一项目内的隔离 staging 副本生成终态、事件、报告与 manifest，并完成目录校验；只有 staging 有效时才交换 active 目录并更新 `.agency/task-index.json`，任一提交失败会恢复原 active 状态。superseded 旧任务不再出现在 active 列表。Manifest 完整列出归档目录内除自身外的文件并绑定 hash、验证、Review、cleanup 与产物路径；validator 还会交叉核对 disposition、source/final status、reason、blocker、验收证据和 closure。遗漏、重复、额外文件、内部矛盾或 symlink 都不能通过校验。计划文本或历史自述不算证据。

## 长期知识候选

候选只描述未来可复用的稳定事实、决策、流程或测试方法。每条都必须有 Source Task 和 Evidence，且满足：

- `confidence=verified` 才允许真正写入；limited 保留为候选。
- 不依赖临时会话上下文。
- 不含 secret、凭据、临时 Thread ID、active task 路径、临时 worktree 或本机绝对路径。
- 写入前对全项目知识文档查重，并检查相同 Knowledge ID 的冲突。
- restricted/internal 内容不得写入公开 README。
- `source_task_id` 必须等于当前归档任务；每个 Evidence ref 必须存在于该任务的 Work Item、验收、Validation、Review、Cleanup 或 Artifact 闭环证据中。

## 文档映射

优先采用候选的安全 `recommended_target`；未指定时按下列顺序：

| 类别 | 目标 |
|---|---|
| 架构决策 | 相关 ADR；有 `docs/adr` 时创建下一编号 ADR |
| 稳定操作流程 | `docs/runbooks` 或 `docs/workflows` |
| 测试方法 | `docs/testing` |
| 调试根因 | 相关故障文档；无匹配则知识文档 |
| 项目稳定事实 | `CONTEXT.md` 或相关领域文档 |
| 稳定偏好 | 现有项目偏好文档或 `CONTEXT.md` |

没有匹配文档或目录时写入 `docs/knowledge/<topic-slug>.md`。自动匹配同时使用英文词与中文文件名/标题 n-gram；命中已有文档时只做最小追加，不新建重复文档、不改写原文、不复制完整任务计划。

`deposit_knowledge.py` 默认输出计划；只有明确 `--apply` 才写文档。多文档补丁与 deposit report 属于同一回滚边界；任一写入失败都恢复本次目标，避免文档已改而报告伪阴性。Archive 命令只有同时显式 `--deposit-knowledge` 时才在归档后执行写入；若归档移动后沉淀仍发生 I/O 失败，归档保留并返回 `archived_with_blocker`、写入 blocker report、CLI 退出非零，不宣称知识沉淀成功。
