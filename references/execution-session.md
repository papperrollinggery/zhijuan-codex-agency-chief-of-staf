# Execution Session

执行会话把已经确认的任务清单交给一个新的 Execution Root。它不会重新讨论需求、重新建清单或再创建另一个 Chief-of-Staff 根任务。

已绑定且状态为 `executing` 的 Packet 是执行入口，不是启动入口：读取一次 packet 指向的 task plan，只有委派或 Reviewer 判断需要时才读 Team Plan，然后直接使用 `task-lifecycle.md` 的 Execution Root 快速路径。不要重查 catalog、Profile、launch 文件，不要读取 `PROGRESS.md` 镜像，也不要枚举 `.agency`。

跨会话恢复不能丢失真实事件：如果 plan 中任一 Work Item 已不是 `pending`、任务/Work Item 处于 blocked，或 Team Plan/风险门要求 Reviewer，就在执行新动作前按精确路径单次读取 canonical `progress.jsonl`，恢复已有 blocker、verification、`review_returned` 与 `team_plan_changed` 证据；本轮后续不重复读取。全新、全部 pending 且无 Reviewer 要求的任务跳过该读取。

## 启动顺序

用户明确请求“创建新对话，使用 gpt-5.6 sol ultra 根据任务执行清单执行并更新进度”时：

1. 找到唯一 active 的 `plan_ready` 任务；有多个时只问用户选哪一个。
2. 校验 task plan、依赖和完成标准。
3. 用 `resolve_team_plan.py` 生成 Team Plan。
4. 从当前 Codex App Server live catalog 按显示名查找 GPT-5.6 Sol 的精确 ID。若 live model item 没有 provider 字段，调用 `prepare_execution_launch.py` 时显式传 `--thread-id "$CODEX_THREAD_ID"`；helper 会从同一 App Server 的 canonical `codexHome/state_5.sqlite` 机械读回这个被选择 Root 的 provider。该 selector 不独立证明“当前前台 Task”，因此最终仍必须由 binder 读回新执行 Task；selector 缺失、状态读回失败或 provider 不匹配时 fail closed，不从模型名猜 provider。
5. 验证该 ID 支持 `ultra`；不支持或不存在时停止并给用户唯一模型选择，不静默降级。
6. 按执行面优先级准备所需 Profile：Native Direct Route → 已读回 Named Custom Agent → 项目 selected-only Profile → Generic Native Subagent + Role Packet → CLI read-only compat → Root 直接执行。
7. `prepare_execution_launch.py` 只生成 Execution Session Packet 和 `execution-session.json`，状态最多到 `native_launch_ready` 或 `manual_launch_ready`；它不会把调用方 JSON 当成创建证明。
8. 宿主优先创建真实 Codex Task/Thread；写任务必须使用隔离 Worktree。
9. `create_thread` 可能把首条提示词放进精确的 `<codex_delegation>` transport envelope。该 envelope 只允许承载 Execution Session；Runtime 严格解出 source task ID 与 `<input>` 中的原始 packet，并从 App Server 与 canonical state 证明 source 是非自引用的 user-owned Root。Worker/Subagent source 和任意畸形/嵌套 envelope 均 fail closed。
10. 宿主创建后运行 `bind_execution_session.py`；该脚本不接收调用方 readback JSON，而是连接当前 App Server 的 `thread/read`、live model catalog 与 `codexHome/state_5.sqlite`，再核对 rollout turn context。
11. 只有 Task ID、Root 身份、完整 packet、transport/source task、provider、model、reasoning、cwd/worktree、未归档状态与 rollout 实际 turn 全部机械一致，才从 `execution_ready` 进入 `executing`，写入 `native_task_id` 并更新进度；整个绑定可回滚。

## Execution Session Packet

```text
AGENCY_EXECUTION_SESSION: true
任务 ID：<task-id>
编排深度：0
项目根目录：<absolute-project-root>
任务清单：<project-relative-task-plan>
团队计划：<project-relative-team-plan>
进度文件：<project-relative-progress>
执行模型请求：GPT-5.6 Sol
推理强度请求：ultra
执行职责：作为本任务 Execution Root，按清单执行、调度、验证并更新进度。
停止条件：全部完成标准有当前证据，或记录真实阻塞；不得创建新的 Chief-of-Staff 根任务。
```

`protocol_contract.py` 对它使用独立 parser。它不是 `AGENCY_WORKER: true`：

- Canonical Skill 识别后直接进入 Execution Mode。
- 不重新讨论，不重新规划，不创建另一个 Root。
- Root 可以按 Team Plan 派发 Subagent；Subagent 不得递归调用 Chief of Staff。
- 只有 Root 更新全局 Task State、验证证据和归档。
- `编排深度` 必须为 `0`；worker 固定为终端深度 `1`，不存在深度 `2`。
- 首行是保留 marker 但 packet 无效时返回 `INVALID_PACKET`，不得按普通主会话重新激活。
- Raw Packet 仍要求物理首行 marker；唯一例外是 Codex `create_thread` 的精确 transport envelope。Envelope 不改变 packet 语义，也不能用来承载 Worker 或增加编排深度。

## Root 模型政策

Root 使用独立的 `execution-model-policy.json`，不属于 Efficient/Balanced/Judgment 子代理成本档。显示名、精确 ID、reasoning 与实际运行是四层不同证据：

- 只从 live App Server catalog 解析精确 ID，不从字符串或文档猜测。
- 从 `--catalog` 读取的序列化 JSON 一律是 `caller-asserted-unverified`，即使自称 `live_readback_verified` 也不能启动；只有同一调用机械连接 App Server 得到的目录才可解析为 launchable。
- catalog 中存在 Sol 但没有 `ultra` 时，用户选择当前 Sol 最高 Effort、替代模型或暂不启动。
- Sol 不存在时不猜 ID。
- Native spawn 后必须读回实际 provider/model/effort；不一致为 FAIL，不能进入 executing。
- 单独传给准备 helper 的 `native_readback` 只返回 `fields_consistent_unverified` 诊断；不会写入 session，也不能产生证明。没有机械绑定时，`new_conversation_created` 必须保持 `false`。
- `session_status=executing` 的 schema 只负责结构约束，不能把固定字符串变成宿主证明。唯一公共写入路径是 `bind_execution_session.py`：它内部读取 App Server、canonical state 与 rollout，校验顶层/嵌套 Task、模型、Effort、CWD 和 packet 语义一致后写入 `app-server-canonical-state-mechanically-bound`。调用方不能上传一个 JSON 来替代该读取。
- 早期 v1.0 raw session 可继续读取；下次 binder 机械重验 raw prompt 后才会原子回填 transport 字段。部分字段、envelope 伪装或无当前 readback 均不迁移。
- canonical state 没有稳定的“当前正在采样”字段，绑定状态精确写为 `active-unarchived`，不把未归档误报为正在运行。任务完成或清理仍需后续 readback 证据。
- Subagent 仍按原有能力档路由，不要求全部使用 Ultra。

## Native 不可用时

默认 `prefer_native → manual_launch_prompt`。无法调用真实 Task/Thread 时保留完整 `EXECUTION_LAUNCH_PROMPT.md`，session 状态为 `manual_launch_ready`；只说明提示词已准备，不声称已创建对话，也不在同一线程或普通 Subagent 中模拟。

只有用户明确要求“必须自动创建真实新对话，不接受手动启动”时返回 `TOOL_BLOCKED`。

## Selected-only Profile

`prepare_team_runtime.py` 只读取当前 `TEAM_PLAN.json` 中选中的 Profile；Execution Root 不生成 Profile，同 Profile 多实例只安装一份能力模板。默认 dry run，只有明确阶段三请求并追加 `--apply` 才写项目 `.codex/agents`。脚本不删除未选 Profile，不写用户全局 Agent 配置，也不读写项目 `AGENTS.md`。
