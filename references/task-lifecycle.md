# Project Task Lifecycle

只有用户明确需要跨对话连续性、持续进度、独立执行对话或归档时使用四阶段生命周期。普通复杂任务继续使用 Direct/Focused，不创建 `.agency`。

## 意图与停止点

### 需求讨论

用户要求“先讨论需求”“先不要执行”或“先把目标和边界聊清楚”时进入 Discussion Mode：

- 首个状态为“任务已接管｜需求讨论中”。
- 不修改项目文件，不创建 Agent、Task、Thread，不运行实现命令。
- 只读取用户明确要求核对的当前资料。
- 宿主普通 delegation envelope 的 source ID 不是读取授权；不自行检索 source task、历史对话、memory、项目或 Git。
- 一次只问一个会改变结果的问题。
- 在当前对话维护 objective、constraints、accepted decisions、assumptions、open questions、acceptance criteria 和 out of scope。
- 不自行从讨论进入计划或执行。“只讨论不执行”是合法停止点。

### 执行清单

只有用户明确要求把讨论整理成执行清单时，才把计划写入项目 `.agency`。使用 `scripts/agency_task.py create` 创建最小初始状态：

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

清单面向用户，列出完成标准、依赖、状态和验证，不使用虚构日期、用时或百分比。一次 helper 调用在隐藏 staging 中创建并校验八个任务文件，再以目录 rename 原子发布并更新项目 index，避免模型逐文件设计、枚举或补写，也不会让其他进程读到半个正式任务目录。创建使用项目级短锁和恢复 journal；进程中断后下一次 Durable 操作会清理未发布 staging，或把已完整发布的孤儿任务补回 index。创建后状态为 `plan_ready`，不会自动执行、安装 Profile 或创建新对话。`TEAM_PLAN.*` 是未选岗的 `pending` scaffold，`progress.jsonl` 是零事件空日志，`PROGRESS.md` 陈述当前阶段，`EVIDENCE.md` 只是 canonical 证据位置索引而不镜像易过期状态；它们的存在不代表执行已经开始。

创建入口按字段白名单拒绝未知完成声明，并拒绝任何调用方预填的已完成/waived Work Item、evidence、blocker、岗位/Profile、acceptance evidence 或已解析模型 ID；新任务只能从全 pending、模型 `null + pending` 的诚实初态开始。旧 v1.0 任务读取仍会补齐缺失的模型请求字段，schema 不把后来新增字段倒灌成旧文件的必填项。

输入可以只提供每个 Work Item 的 `work_id`、`title`、`outcome` 和 `work_type`；确定性脚本补齐安全默认字段并把完整规范写入 `task-plan.json`。Plan 固定记录 GPT-5.6 Sol / `ultra` 请求为 `pending`，但不解析 Live Model Catalog，也不把显示名称当运行证明；真正启动 Execution Session 时才解析和读回。

首次真实执行事件才向零事件 `progress.jsonl` 追加记录并重绘 `PROGRESS.md`。工作项全部完成且当前验收、验证、Review（如需要）及 Task/Thread 清理证据齐备后，使用 `scripts/complete_task.py`。默认只做 readiness 检查；传入 `--apply` 才从 `executing`/`verifying` 收口到 `completed`，并生成归档可复用的 `closure.json`。

通用 `agency_task.py transition` 和公开进度命令不能写 `completed` / `archived` 或 terminal event；这些终态只能由 `complete_task.py` 与 `archive_task.py` 在证据门禁通过后写入。Task 创建、状态转换、进度事件、归档和知识沉淀的多文件提交都带故障回滚；失败不能留下 plan/index、文档/report 或 active/archive 的半状态。

#### Execution Root 快速路径

Durable 负责保存必要连续性，不应占用项目判断。进入执行后默认只读一次当前 `task-plan.json`；若已有 ready Team Plan，只在确需委派或确认 Reviewer 时读一次当前分工。task ID 与 plan 路径已给出时，不用 `rg` / `find` 枚举 `.agency`，不读作为人类视图的 checklist；全新任务首次进入时不读取零事件 `progress.jsonl`，只有恢复既有事件时才读一次。先确定当前 Work Item，然后按“开始事件 → 项目内容工作 → 当前验证 → 完成事件”推进：

下列命令是参数结构示例，不是可做字符串替换的 shell 模板。所有动态值都按单个 argv 传入，包括 skill root、project、task/work ID、summary、完成标准、证据和路径；能传 argv 数组时不拼 shell 字符串，只能使用 shell 时必须对每个动态值做 POSIX shell escaping。不得把尖括号占位符原样交给 shell，不得使用 `eval`，也不得把任务文本直接插入引号。`<skill-root>` 表示本轮已完整读取的 Canonical `SKILL.md` 所在目录。

```bash
python3 <skill-root>/scripts/update_task_progress.py \
  --project . --task-id <task-id> --event-type work_started \
  --work-id <work-id> --summary '<真实开始动作>' --json

# 在这里完成项目研究、判断、实现或写作，并运行当前验证。

python3 <skill-root>/scripts/update_task_progress.py \
  --project . --task-id <task-id> --event-type work_completed \
  --work-id <work-id> --summary '<实际结果>' \
  --artifact '<项目相对产物>' --verification '<当前验证证据>' --json
```

`work_completed` 已同时接收 artifact 与 verification；它的 exit 0 JSON 就是本次状态读回。没有独立的新事实时，不再追加 `artifact_generated`、重读 progress/checklist，或为管理文件运行 `git status` / `git diff`。只要求进度更新时到此停止；不要再运行 task validator。全部工作项完成且用户要求收口时才运行一次 completion。每一条完成标准都必须用其在 plan 中的精确文本重复传一个 `--criterion-evidence-item '<完成标准>' '<证据引用>'`；该双 argv 形式允许文本本身含 `::`，不要在新调用中使用有歧义的旧 `CRITERION::EVIDENCE` 形式。当前验证用可重复的 `--validation-item '<验证摘要>' '<证据引用>'`，产物也可重复传入。

以下任一条件成立就必须追加至少一个 `--review-evidence`：Team Plan 选择了 Reviewer、任何 Work Item 为 high/critical risk，或 work type 为 review/release。收口前只确认这一布尔要求，不为此读取无关 Team Plan 内容。

```bash
python3 <skill-root>/scripts/complete_task.py \
  --project . --task-id <task-id> \
  --criterion-evidence-item '<完成标准>' '<证据引用>' \
  --validation-item '<验证摘要>' '<证据引用>' \
  --artifact '<项目相对产物>' --cleanup-status not_applicable \
  --apply --json
```

上例的 `not_applicable` 只适用于没有 Native Task/Thread 的任务。存在 Native Task/Thread 时必须把这一段替换为以下二者之一：已关闭时传 `--cleanup-status closed` 并至少重复一个 `--cleanup-evidence '<关闭读回证据>'`；确有清理阻塞时传 `--cleanup-status cleanup_blocked --cleanup-blocker '<真实阻塞>'`。不得为通过门禁虚构关闭证据或阻塞。

Execution Root 无法在自己的最终返回前证明自身已关闭时，可以先用真实 `cleanup_blocked` 完成内容收口。来源 Root 随后关闭并读回该 Task/Thread，再以完全相同的验收、验证、Review 和产物参数重跑 `complete_task.py --apply`，只把 cleanup 改为 `closed` 并附关闭证据。Runtime 仅允许这一个 `cleanup_blocked → closed` 单向修正；验收或 closure 其他字段漂移、反向修改及无读回证据都会失败，且不会重复生成完成事件。

completion exit 0 后只做一次全项目状态校验：`python3 <skill-root>/scripts/validate_task_state.py --project . --json`。该 CLI 没有 `--task-id`；不要先试探参数。completion JSON 已给出 closure 与 terminal event，不再枚举目录或重读这些文件。

以上 CLI 是稳定 Runtime 契约。helper 没有报错时，不运行 `--help`、不枚举全部脚本、不读取 helper 源码，也不反复读回整个 `.agency`；只读与当前完成标准有关的项目产物和最终状态。只有 helper 返回的具体错误无法从输入修正时，才检查对应实现。

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
