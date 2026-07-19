# Project Task Lifecycle

项目型请求使用四个用户阶段：需求讨论、执行清单、独立执行对话、归档与知识沉淀。单次小任务继续使用 Direct Mode，不创建 `.agency`。

## 意图与停止点

### 需求讨论

用户要求“先讨论需求”“先不要执行”或“先把目标和边界聊清楚”时进入 Discussion Mode：

- 首个状态为“任务已接管｜需求讨论中”。
- 不修改项目文件，不创建 Agent、Task、Thread，不运行实现命令。
- 只读取用户明确要求核对的当前资料。
- 一次只问一个会改变结果的问题。
- 在当前对话维护 objective、constraints、accepted decisions、assumptions、open questions、acceptance criteria 和 out of scope。
- 不自行从讨论进入计划或执行。“只讨论不执行”是合法停止点。

### 执行清单

只有用户明确要求把讨论整理成执行清单时，才把计划写入项目 `.agency`。使用 `scripts/agency_task.py create` 创建：

```text
.agency/
├── task-index.json
└── tasks/
    ├── active/<task-id>/
    │   ├── task-plan.json
    │   ├── TASK_EXECUTION_CHECKLIST.md
    │   ├── TEAM_PLAN.json
    │   ├── TEAM_PLAN.md
    │   ├── EXECUTION_LAUNCH_PROMPT.md
    │   ├── PROGRESS.md
    │   ├── progress.jsonl
    │   └── EVIDENCE.md
    └── archive/
```

清单面向用户，列出完成标准、依赖、状态和验证，不使用虚构日期、用时或百分比。创建后状态为 `plan_ready`，不会自动执行、安装 Profile 或创建新对话。

### 独立执行对话

用户明确请求启动时才生成 Team Plan、解析 Root 模型、准备 selected-only Profile，并创建真实 Task/Thread 或给出手动启动提示词。详细协议见 [execution-session.md](execution-session.md)。

### 归档与知识沉淀

只有完成证据通过归档校验，或用户明确把任务以 cancelled/superseded 方式收口时才归档。长期知识必须逐条验证、去重、排除敏感或临时信息。详细协议见 [knowledge-archiving.md](knowledge-archiving.md)。

## 状态机

唯一合法主路径：

```text
discussion → plan_ready → execution_ready → executing → verifying → completed → archived
```

合法旁路：

```text
discussion → cancelled
plan_ready → superseded
execution_ready → superseded
executing → blocked
blocked → executing
```

禁止跳过验证、把未完成任务归档为 completed，或让 superseded 任务继续出现在 active 列表。`scripts/validate_task_state.py` 是离线状态与依赖校验入口。

## 权限边界

- Execution Root 是唯一能改变全局 Task State、确认工作项证据和发起归档的角色。
- Subagent 只返回自己范围内的产物与证据，不直接写全局状态。
- 外部写入、发布、删除、支付、身份和隐私动作仍需原有授权。
- 当前 Git 根是本 Skill 源码仓库时遵守仓库 `AGENTS.md` 的 Self-Maintenance Mode，不把源码维护本身变成 Agency Task。
