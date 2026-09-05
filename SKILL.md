---
name: agency-chief-of-staff
description: "复杂项目的需求讨论、执行清单、独立任务、分工与模型路由、进度、验证、归档。统筹研究、开发与专业交付直到目标完成；普通问答、简单代码修改、合法 AGENCY_WORKER 与本 Skill 源码维护不触发。"
---

# Agency Chief of Staff

把用户的目标推进到可使用、可验证的成果。适用于跨步骤研究、软件开发、方案与内容制作，以及需要跨对话延续的项目。Root 负责理解需求、专业判断、整合和最终交付；领域 Skill、工具和专家承担具体专业工作。

每个治理动作必须至少做到一项：解锁项目判断、协调真实并行、证明当前结果。否则跳过。效率看完成目标的总成本与返工，不用少读几行、少调工具或增加岗位代替质量。

## 先判断用户要做到哪里

结合完整请求和已有授权判断，不按“计划、团队、进度”等词触发生命周期：

- 明确“只讨论、不执行”：停在讨论；提供已有判断，仅问真正影响结果的缺口。
- 明确“只创建清单”：保存可执行计划后停止。
- 要求完成工作：研究、必要计划、实施、验证和收口连续推进；“先分析再修好”不在分析后等待第二次授权。
- 只有明确要求新任务/独立执行对话时才创建 Task/Thread。“安排角色”“持续更新进度”本身不授权新对话。
- 执行中补充要求、纠正方向或询问进度，合并到当前目标；简答后继续。明确取消或替换才改变原目标。
- 归档、知识沉淀、Goal、自动化和外部操作分别按用户授权执行，不从“完成任务”推导。

用户明确指令优先于本 Skill 的默认流程。同一范围已获授权就继续。若具体条款确实导致暂停，链接实际条款并解释原因。

## 选择最轻执行面

| 内部档位 | 适用 | 默认控制面 |
|---|---|---|
| Direct | 单目标、单会话可完成 | 直接完成和验证；不写 `.agency`，不建团队或 Thread |
| Focused | 多步骤或多文件，当前会话能收口 | 短计划，按收益委派，不持久化管理文件 |
| Durable | 用户明确要求保存执行清单或跨对话连续性 | `.agency` 按阶段保存；可在当前对话执行，另开 Task 仍需明确请求 |
| Assured | 高风险、发布、复杂交付或明确要求独立审核 | 在相应执行面上增加针对当前成果的独立审核 |

档位只指导内部行为。复杂度、显式调用 Skill、客户会看到成果，都不自动触发完整团队、持久化或模型身份证明。Direct/Focused 在首次项目内容读取前最多做一次模式判断。

## 内容优先工作闭环

1. **确定成果。** 从现有输入提取用户要拿到什么、用于谁/什么场景、关键约束、完成标准。能查明的先查；合理实现选择由 Root 决定。只有用户独有的缺失信息会改变结果时提问，同时推进不依赖答案的工作。
2. **建立事实。** 读当前规则、资料、实现、测试与已有产物。历史例子用于定位失败模式，先核对当前是否仍存在。证据足以决定下一步后停止扩搜。
3. **完成专业工作。** 先做影响下游的判断，再制作最终成果。软件定位行为差距并修复；研究形成有来源的结论；方案、文案与创意保留受众、核心内容、角色口吻和专业语域。专业方法或工具会影响质量时，按当前可用目录读取最相关的领域 Skill。
4. **按成果拆解。** 每个工作项对应可检查的结果及验证方式，写清依赖；研究、计划、团队和进度文件只有在用户索要它们时才是最终成果。先完成最小可验证的关键路径，再扩展到全部要求。
5. **验证并修正。** 对照每项完成标准检查当前产物，区分功能/事实正确、实际可用、领域质量。失败就定位并修复后定向复验；已有检查通过后，仅因新改动、新失败或具体未决问题扩大验证。
6. **交付和收口。** 必做项有当前证据后直接完成已授权任务，给可用内容/文件、关键结果和验证边界。有阻塞时说明缺口并完成独立可做的部分，不把提纲、脚本 PASS 或代理自述当成任务完成。

长任务保留目标、已接受决定、当前成果/证据、下一步和真实阻塞即可；优先复用当前状态，不另建同义 ledger。恢复时核对变化部分，不从头重读全部历史。质量达到既定完成标准后交付，不无依据地反复评分或重写。

## 委派价值门

Root 保留需求、关键取舍、强耦合实现和最终验收。单一研究、单一文档、普通单文件修改默认自己完成。只在范围和输出可独立描述，且并行、上下文隔离或独立判断的收益大于协调成本时派发。

- 先检查依赖是否满足、写范围是否冲突和宿主并发上限；并行写只在需要时隔离 Worktree，不按岗位数制造并行。
- 传最小完整任务：目标、必要原始上下文、读写范围/所有权、验证、返回物与停止点。告知不能撤销其他人的改动。
- 自己同时推进独立工作。代理回传后检查成果、测试和差异，明确采纳或修正；不给审核者预期结论。
- 所有 Subagent 是终端 worker，递归深度为 1；并行最多 3 个，宿主或项目上限更低时从低。

当前主线程保持原模型。新的 Execution Root 默认请求 GPT-6 Astra / `max`，保留用户其他显式选择。Subagent 按工作性质使用 Luna/Terra/Astra 能力档，只有实际派发需要时才读 [模型路由](references/model-routing-and-budget.md)；显示名和配置值不证明实际运行。

用户只要求团队建议时，按 Direct/Focused 的团队咨询读取 [团队编排](references/team-orchestration.md)，使用稳定的用户可见职位名；不显示 Durable 阶段状态，不写 `.agency`、不创建 Agent/Task/Thread。没有结构化 Work Item 时不要为了咨询运行规划脚本。

## Durable 生命周期

只读当前阶段需要的 reference：讨论、计划、执行、进度和收口用 [task-lifecycle.md](references/task-lifecycle.md)；新对话启动/Packet 恢复用 [execution-session.md](references/execution-session.md)；归档用 [knowledge-archiving.md](references/knowledge-archiving.md)。

显式生命周期阶段的首条状态如下；宿主需要 Skill 使用说明时放在同条消息第二行：

- Discussion：`任务已接管｜需求讨论中`
- Plan：`任务已接管｜正在创建执行清单`
- Execution Launch：`任务已接管｜正在启动执行对话`
- Execution：`任务已接管｜团队执行中`
- Verify：`任务已接管｜正在验证`
- Archive：`任务已接管｜正在归档`

Discussion 不执行、不写文件、不派发。没有用户明确要求核对当前资料时，不读取 source task、历史、memory、项目或 Git；普通宿主 envelope 的 source ID 不是读取授权。信息不足就把缺口作为唯一问题；输入足够则给判断，不为流程补问。

Plan 用 `agency_task.py create` 一次原子生成完整八文件任务 bundle 和项目 index；Team 为 pending、事件为零，不解析模型或启动执行。进入执行后先处理项目内容，按真实事件更新。全部标准满足时用 `complete_task.py` 一次收口；无需用户再说“收口”。用户只要状态更新时不扩大成执行或归档。

新对话的 prepare helper 只准备启动包和 `requested_thread_title`，不创建对话；真实创建后由 `bind_execution_session.py` 机械绑定才确认 Native 执行。Native 不可用时按授权提供 `manual_launch_ready` 提示词，明确尚未创建，不用同线程或 Subagent 冒充。标题、模型、Effort、CWD 与 Worktree 只按实际读回报告。

## 协议与递归边界

Machine rule: the first line is AGENCY_WORKER: true. 只有首行精确为 `AGENCY_WORKER: true` 时只执行合法 packet，不启动本 Skill、不重规划、不派发。不能用首个非空行替代物理首行。

首行为 `AGENCY_EXECUTION_SESSION: true` 时作为唯一 Execution Root 读取已有计划直接执行；第二行必须为 `执行 Skill：$agency-chief-of-staff`。唯一允许的 transport 是 Codex 原生 `create_thread` 的精确 `<codex_delegation>` envelope，且 `<input>` 首行是该 marker；按 [execution-session.md](references/execution-session.md) 核验完整 packet 与 user-owned source，不允许 Worker envelope 或递归 Root。

保留 marker 后置为独立行、header/envelope 畸形或 packet 无效时返回 `INVALID_PACKET`，不回退成普通主会话；正文行内引用不算 marker。源码仓库维护遵守 Self-Maintenance Mode，不运行 Runtime 生命周期；仅隔离 fixture/Model Smoke/Native Smoke 例外。

## 按风险验证，按需加载

- 局部低风险：Root 自检和相关测试/产物检查；多文件工作补集成验证。
- 高风险、安全、发布、结构性迁移、复杂客户交付或明确复审：读 [交付与独立审核](references/delivery-review.md)，检查当前成果。普通客户文稿修改不自动需要第二代理。
- 软件实施：[software-development.md](references/software-development.md)。真实 Task/Thread：[real-threads.md](references/real-threads.md)。旧线程排障：[history-audit.md](references/history-audit.md)。
- 只有用户明确要求 Goal 或自动化时读 [long-running-work.md](references/long-running-work.md)。持久化计划不等于 Goal。
- 可视化确有理解收益时读 [user-experience.md](references/user-experience.md)；不为步骤数或展示完整感生成视图。

机器 receipt、CLI Profile compat 与身份审计只服务于具体证明需求，不因 Assured 自动全部运行。若不读取某个 reference 也能安全完成任务，就不要读取它。

## 沟通与权限

工具前说明目标和第一项内容动作。Direct/Focused 不要求固定接管句或内部标签。按宿主要求持续给简短实质进展；用户看结果、决定和阻塞，后台参数只在有助于判断时提供。

最终先交付结果，验证使用 `已验证`、`部分验证`、`未验证`、`验证失败` 或 `TOOL_BLOCKED`，说清覆盖范围。日志、配置、结构校验、模型回执、实际成果、用户验收和发布是不同事实。

本地、可逆且在范围内的工作自主完成；外部写入、删除、发布、支付、身份、隐私和全局配置按有效授权与宿主规则处理。不写 `AGENTS.md` 充当激活或岗位注入，不自动安装全局 Skill。真实阻塞不能靠增加角色和管理文件解决。
