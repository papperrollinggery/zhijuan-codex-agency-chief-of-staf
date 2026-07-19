# Execution Session

执行会话把已经确认的任务清单交给一个新的 Execution Root。它不会重新讨论需求、重新建清单或再创建另一个 Chief-of-Staff 根任务。

## 启动顺序

用户明确请求“创建新对话，使用 gpt-5.6 sol ultra 根据任务执行清单执行并更新进度”时：

1. 找到唯一 active 的 `plan_ready` 任务；有多个时只问用户选哪一个。
2. 校验 task plan、依赖和完成标准。
3. 用 `resolve_team_plan.py` 生成 Team Plan。
4. 从当前 Codex App Server live catalog 按显示名查找 GPT-5.6 Sol 的精确 ID。
5. 验证该 ID 支持 `ultra`；不支持或不存在时停止并给用户唯一模型选择，不静默降级。
6. 按执行面优先级准备所需 Profile：Native Direct Route → 已读回 Named Custom Agent → 项目 selected-only Profile → Generic Native Subagent + Role Packet → CLI read-only compat → Root 直接执行。
7. 生成 Execution Session Packet 和 `execution-session.json`。
8. 优先创建真实 Codex Task/Thread；写任务必须使用隔离 Worktree。
9. 读回真实 Task ID、provider、model、reasoning、cwd/worktree 和状态。
10. 只有读回一致才从 `execution_ready` 进入 `executing`，并更新进度。

## Execution Session Packet

```text
AGENCY_EXECUTION_SESSION: true
任务 ID：<task-id>
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

## Root 模型政策

Root 使用独立的 `execution-model-policy.json`，不属于 Efficient/Balanced/Judgment 子代理成本档。显示名、精确 ID、reasoning 与实际运行是四层不同证据：

- 只从 live App Server catalog 解析精确 ID，不从字符串或文档猜测。
- catalog 中存在 Sol 但没有 `ultra` 时，用户选择当前 Sol 最高 Effort、替代模型或暂不启动。
- Sol 不存在时不猜 ID。
- Native spawn 后必须读回实际 provider/model/effort；不一致为 FAIL，不能进入 executing。
- Subagent 仍按原有能力档路由，不要求全部使用 Ultra。

## Native 不可用时

默认 `prefer_native → manual_launch_prompt`。无法调用真实 Task/Thread 时保留完整 `EXECUTION_LAUNCH_PROMPT.md`，session 状态为 `manual_launch_ready`；只说明提示词已准备，不声称已创建对话，也不在同一线程或普通 Subagent 中模拟。

只有用户明确要求“必须自动创建真实新对话，不接受手动启动”时返回 `TOOL_BLOCKED`。

## Selected-only Profile

`prepare_team_runtime.py` 只读取当前 `TEAM_PLAN.json` 中选中的 Profile；Execution Root 不生成 Profile，同 Profile 多实例只安装一份能力模板。默认 dry run，只有明确阶段三请求并追加 `--apply` 才写项目 `.codex/agents`。脚本不删除未选 Profile，不写用户全局 Agent 配置，也不读写项目 `AGENTS.md`。
