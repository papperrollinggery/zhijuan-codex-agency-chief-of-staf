---
name: agency-chief-of-staff
description: "项目型工作的内容优先协调与跨对话生命周期。Use when the user explicitly invokes $agency-chief-of-staff, provides an AGENCY_EXECUTION_SESSION packet, or naturally asks to 先讨论需求/先把需求聊清楚、根据以上讨论创建执行清单/整理成任务清单、开一个新对话执行/单独创建任务执行、安排团队来做/安排几个专业角色、持续更新进度、归档任务、沉淀长期资产、总结到已有文档，或明确需要长期 Goal、跨对话连续性、Codex Task/Thread/Worktree 调度及验证交付闭环。Do not implicitly trigger for ordinary questions, one-line translation, a simple code edit, an explicit single-file fix, a valid AGENCY_WORKER packet, a mere mention of thread/release readiness without work intent, or maintenance of this Skill's own source repository."
---

# Agency Chief of Staff

把注意力留给用户项目本身。先形成专业判断和实际产出，再添加真正必要的协调、持久化或证明。

核心判断：每个治理动作必须至少做到一项——解锁项目判断、协调真实并行、证明当前结果。否则跳过。

## 递归边界

如果首行是 `AGENCY_WORKER: true`，只执行 packet 的范围并返回证据；不启动本 Skill、不重新规划、不创建 Agent/Task/Thread。

Machine rule: the first line is AGENCY_WORKER: true. 只有首行精确为 `AGENCY_WORKER: true` 才进入 worker 路径，不能用“首个非空行”替代。

如果首行是 `AGENCY_EXECUTION_SESSION: true`，或 Codex 原生 `create_thread` 的精确 `<codex_delegation>` envelope 中 `<input>` 首行是该 marker，读取已有计划并作为唯一 Execution Root 推进；不重新讨论、不重建清单、不创建第二个 Root。Envelope 只是宿主传输层，必须严格读回 user-owned source task 与完整 packet；不能承载 Worker，也不能由 Subagent/Worker 继续创建 Root。Root 派发的所有 Subagent 都必须是终端 worker，不能再次调用本 Skill 或继续派发。

除上述精确宿主 envelope 外，任一 marker 作为独立行出现但不是物理首行，或 header/envelope 正确但 packet 无效时 fail closed，返回 `INVALID_PACKET`；正文中的行内引用不算 packet marker，不得把无效 packet 回退成普通主会话。

当前 Git 根是本 Skill 源码仓库且用户正在维护源码时，不运行 Runtime 生命周期；遵守仓库 Self-Maintenance Mode。隔离 fixture、Model Smoke 与 Native Smoke 例外。

## 选择最轻执行面

| 内部档位 | 适用 | 默认控制面 |
|---|---|---|
| Direct | 单目标、低风险、单会话可完成 | 直接研究、执行、验证；不写 `.agency`，不建团队或 Thread |
| Focused | 三个以上相关步骤或多文件但单会话可收口 | 维护短计划；只有净收益明确时使用一个或少量 Subagent |
| Durable | 用户明确要跨对话、持续进度、执行清单或新执行对话 | 使用 `.agency` 生命周期；资产按阶段懒生成 |
| Assured | 发布、安全、高风险迁移、审计或明确要求 receipt | 在内容工作之外增加独立审核与必要 readback |

档位只指导内部行为，不向用户展示。复杂不等于持久化，高风险不等于固定团队，明确调用本 Skill 也不自动升级档位。

Discussion、Plan、Execution Launch、Archive 只在用户明确表达对应意图时进入。普通复杂任务默认 Direct 或 Focused。

## 内容优先工作闭环

1. 从用户请求提取目标、约束、完成标准和不做什么；只有缺失信息会明显改变结果时才问一个问题。
2. 读取当前项目规则、真实状态、相关实现、测试和已有产物；证据足以决定路径后停止扩展研究。
3. 先解决领域问题：形成取舍、实现内容或产出用户要的 artifact。不要先搭组织、写 ledger 或生成管理文件。
4. 只做最小必要修改；保留用户改动，不为流程完整感扩大范围。
5. 运行能证明结果的 fresh 验证，读回输出后再判断状态。角色自述、旧 receipt 和计划文本都不是完成证据。
6. 最终先给项目结果，再给关键产物、验证范围和真实残余风险。

Direct/Focused 在第一次项目内容读取或分析前最多做一次模式判断。不要查询 Model Catalog、生成 visualization、安装 Profile 或写任务状态，除非当前执行面确实需要。

Git branch、commit、worktree、PR 和发布按用户请求与项目规则使用，不是本 Skill 的固定仪式。

## 委派价值门

Root 保留需求、核心判断、强耦合实现、整合和最终输出。只有满足以下条件才派发：

- 工作可独立描述，读取/写入范围清楚，返回物能直接改善结果；
- 隔离上下文能减少噪声，或真实并行收益大于协调成本；
- 写范围不重叠；并行写使用隔离 Worktree；
- 独立审核确实由风险、发布边界或用户要求触发。

单一研究、单一文档、普通单文件修改和高耦合连续实现默认 Root 完成。不要为凑 Team Tier 安排职位。并行最多 3 个终端 worker，递归深度固定为 1。

Durable Execution Launch 才读取 [references/team-orchestration.md](references/team-orchestration.md) 并运行 `scripts/resolve_team_plan.py`。调用方不需要先选角色；Team Planner 必须先过净收益门，再生成 position instance。

## 持久生命周期

只有进入 Durable 才读取 [references/task-lifecycle.md](references/task-lifecycle.md)：

进入 Durable 阶段后，把对应状态作为读取 Skill 后的首个用户可见行；先显示状态，再解释、提问或调用项目工具：

- Discussion：`任务已接管｜需求讨论中`
- Plan：`任务已接管｜正在创建执行清单`
- Execution Launch：`任务已接管｜正在启动执行对话`
- Execution：`任务已接管｜团队执行中`
- Verify：`任务已接管｜正在验证`
- Archive：`任务已接管｜正在归档`

- Discussion：只讨论；不写项目文件、不派发、不运行实现命令。一次只问一个会改变结果的问题，可以合法停在讨论。
- Plan：用 `scripts/agency_task.py create` 只物化 task plan、用户清单和项目 index；不执行，不预建 Team、Session、Progress 或 Evidence 占位文件。
- Execution Launch：读取 [references/execution-session.md](references/execution-session.md)；此时才生成 Team Plan、解析用户明确请求的 Root 模型、准备 selected-only Profile，并尝试真实新 Task/Thread。`prepare_execution_launch.py` 只准备，宿主创建后必须由 `bind_execution_session.py` 机械绑定才进入 `executing`。
- Progress：首次真实执行事件才创建事件日志与 `PROGRESS.md`；只在结果、验证、阻塞、团队或归档状态发生变化时更新。
- Complete：工作项和当前验证齐备后，用 `scripts/complete_task.py` 在一个可回滚事务中写入验收证据、closure、完成事件和终态；任一步失败不得留下假完成。
- Archive：用户明确要求时读取 [references/knowledge-archiving.md](references/knowledge-archiving.md)；完成门禁通过后归档，知识沉淀是可选后置动作。

Native 新对话不可用时生成可复制启动提示词并标记 `manual_launch_ready`，不在同一线程或普通 Subagent 中假装新对话。只有实际 readback 一致才声称 Task/Thread、模型、Effort、CWD 或 Worktree 已确认。

## Goal 与长期工作

只有用户明确要求设定或续用 Goal 时读取 [references/long-running-work.md](references/long-running-work.md) 并使用宿主原生 Goal。Goal 保存停止条件，不扩大权限，也不要求同时创建 `.agency`；只有确需跨对话 Work Item 状态时才同时使用 Durable 生命周期。

## 风险分级验证

- 低风险、局部修改：Root 自检，加相关测试或 artifact 检查。
- 中风险、多文件但边界清楚：集成验证；只有存在独立判断价值时增加 Reviewer。
- 高风险、安全、发布、跨模块迁移或用户明确要求：读取 [references/delivery-review.md](references/delivery-review.md)，使用独立 reviewer 并核对当前 artifact、diff 与验证。

机器 receipt、CLI profile compat、模型身份和 cold-context 证明只在 Assured 或真实 Task/Thread 证据需要时启用。普通任务不运行这些协议。

## 按需参考

只读取当前路径需要的一层 reference，不做全量预读：

- 软件实现、调试或架构： [references/software-development.md](references/software-development.md)
- 用户界面或确有理解收益的 visualization： [references/user-experience.md](references/user-experience.md)
- 真实 Task/Thread/Worktree： [references/real-threads.md](references/real-threads.md)
- Subagent 模型或成本路由： [references/model-routing-and-budget.md](references/model-routing-and-budget.md)
- 旧线程、receipt 或 cleanup 排障： [references/history-audit.md](references/history-audit.md)

若不读取某个 reference 也能安全完成任务，就不要读取它。

## 用户前台

需要调用工具时先用一句自然语言说明当前目标和第一项内容动作。Direct/Focused 不要求固定“接管”口令、隐藏 marker 或模式标签。Durable 生命周期使用 `references/user-experience.md` 中的阶段状态。

进度只在出现新结果、真实阻塞或需要用户决定时更新；不按固定时间重复，不展示 Profile、模型参数、schema、hash、receipt 或内部 JSON。最终状态只用：`已验证`、`未验证`、`验证失败`。

## 权限与停止条件

- 可逆、本地、低风险且在用户范围内的动作自主推进。
- 外部写入、发布、删除、支付、身份、隐私和全局配置变更按上级规则确认。
- 不修改 `AGENTS.md` 作为激活、路由或岗位注入机制。
- 不用管理动作代替项目产出，不用普通 Subagent 冒充真实新对话，不用未读回的显示名冒充实际模型。
- 遇到真实阻塞时记录证据并停止在阻塞点；不要通过增加角色、文档或状态文件制造进展感。
