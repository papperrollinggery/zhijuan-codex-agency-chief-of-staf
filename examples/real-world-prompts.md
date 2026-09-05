# Real-World Forward-Test Prompts

用真实模型运行这些 prompt，保存脱敏 event JSONL、最终消息、runtime/case/runner hash 和 Codex 版本。不要把预期答案告诉测试 agent。只在已审核 checkout 中使用专用低权限 eval 凭据；不可信 diff 需要一次性 OS 用户或容器。

离线 `behavior_cases.json` 只定义行为 contract，不证明模型实际遵守。

## 四阶段项目生命周期

需求讨论，不执行：

```text
这件事比较复杂，先跟我把目标、边界和完成标准聊清楚，暂时不要执行。
```

检查：自然语言隐式触发；首状态为“任务已接管｜需求讨论中”；不写文件、不创建 Agent/Thread，一次只问一个会改变结果的问题。

根据讨论创建持久化清单：

```text
根据以上讨论，创建任务执行清单；只生成计划，不自动开始执行。
```

检查：一次 helper 创建完整八文件 bundle 和项目 index，状态为 `plan_ready`；Team 为 pending、progress 为零事件、Evidence 明示没有执行证据，Session 尚未生成。文件存在不代表执行开始。

启动独立执行对话：

```text
创建新对话，使用 gpt-5.6 sol ultra 根据任务执行清单执行任务，并持续更新进度。
```

检查：Team Planner 从 Work Item 自动组队；Root exact model/effort 来自 live catalog 并在 spawn 后读回；写任务使用隔离 worktree。Native Task/Thread 不可用时生成完整手动启动提示词并标记 `manual_launch_ready`，不把当前线程或 subagent 冒充新对话。

完成执行：

```text
核对所有工作项、验收标准和当前验证证据，完成任务但先不要归档。
```

检查：使用单一完成入口写入验收证据、验证、必要 Review/cleanup、完成事件和可复用 closure；不手工拼多份镜像 JSON，不枚举管理目录、不读取 helper 源码，也不用 Git housekeeping 重复证明 helper 的 exit-0 JSON。

归档并沉淀长期知识：

```text
归档这个任务，并把已验证、可复用的信息最小写入已有文档；没有匹配文档时再创建 docs/knowledge 文档。
```

检查：Required Work、Acceptance Evidence、Blocker、Review、cleanup、产物和验证先通过；archive manifest 有效；已有目标文档只读一次，新目标由 helper 创建；知识去重，拒绝 secret、临时 Thread ID、临时路径和未验证推断，archive JSON 加一次 validator 后停止重复盘点。

## Team Tier 平衡

```text
使用 $agency-chief-of-staff。只规划团队，不执行：这是单文件、单目标、高耦合的小 Bug。不要为了人数加入 architect、writer 或 supervisor。
```

检查：`solo` 或必要时 `lean_team`，不恢复固定组织。

```text
使用 $agency-chief-of-staff。只规划团队，不执行：这是跨 API、domain 和 persistence 的接口迁移，有多文件实现和独立验证。
```

检查：至少考虑 Technical Architect、Developer 和 Reviewer，不完全拒绝派发。

```text
使用 $agency-chief-of-staff。移动端、服务端和部署配置是三个范围与输出不同、可并行的独立研究流；保留三个 Researcher position instance。
```

检查：同一 `codebase-researcher` Profile 的三个实例不因 Profile 名相同而合并。

## 直接闭环

```text
使用 $agency-chief-of-staff。先检查当前实现，再把问题修好并完成验证；中途告诉我实质进展，就在当前对话做完。
```

检查：分析后继续完成实现和验证；“先检查”不被当成只讨论，“进度”不触发新 Task/Thread；不要求用户再次批准收口。算法与多文件兼容行为由 `outcome-algorithm-mean-bugfix`、`outcome-compat-retry-plan` 的独立执行 oracle 验收，不能只输出正确措辞或修改自测来通过。

```text
按已经保存的 task plan，在这个对话直接执行到完成；不另开任务。
```

检查：无 Native Session 时使用 `agency_task.py start`，不查模型或造 Native 回执；已准备 Session 时按真实已有状态恢复。失败验证阻止完成，修复后使用当前工作证据收口。

```text
使用 $agency-chief-of-staff。只读 README，告诉我仓库名称，不要修改文件。
```

检查：直接读取并回答项目内容；不要求固定“任务已接管”口令，不创建 `.agency`、团队、Thread、模型查询或可视化。

```text
使用 $agency-chief-of-staff。修复 utils.py 的一个明确拼写错误并跑相关测试。
```

检查：显式调用不自动升级生命周期；Root 完成单文件修改和验证，零 `.agency` 文件、零 Subagent。

## 研究到交付

```text
使用 $agency-chief-of-staff。这是高风险迁移：先研究当前实现和测试，再给最小计划，完成修复、验证，并让独立 reviewer 做 cold review。
```

检查：研究发生在计划前；主线程真正执行；reviewer 来自独立上下文；发现问题后修复并复验。

## Goal 长任务

```text
使用 $agency-chief-of-staff。为迁移任务设定一个可验证 Goal，按 checkpoint 持续推进，达到停止条件再结束。
```

检查：Goal 有 outcome、constraints、verification 和 done condition；创建/checkpoint/完成后都有原生 readback；不会为每个短 worker 生成 Goal Ledger，也不会因临时困难提前标 blocked。

## 并行研究

```text
启动幕僚长。把三个相互独立的技术方案交给原生 subagents 并行调研，主线程同时检查当前代码，最后收敛成一个决定。
```

检查：工作流确实独立；并行 agent 数量有界；主线程没有被动等待；结果有采纳/拒绝判断。

## Worker bypass

```text
AGENCY_WORKER: true
委派目标：使用 $api-design 审查当前 API diff。
读取范围：当前 API 实现、测试与 git diff。
写入范围：无。
期望产物：REVIEW_TARGET、REVIEW_READBACK、REVIEW_FINDINGS、REVIEW_RESIDUAL_RISK、REVIEW_VERDICT，均填实际读回值。
验证要求：直接读取当前 artifact 与测试证据后给出实际判定。
停止条件：返回唯一终态；不启动、不派发。
```

检查：不出现 `COS_BOOT_RECEIPT`；不重分级；直接返回指定结果。

无效保留 packet：

```text
AGENCY_WORKER: true
委派目标：缺少其余协议字段。
```

检查：只返回 `INVALID_PACKET`；不把它升级成 Root，不读项目、不派发。

## 真实 task/thread

```text
使用 $agency-chief-of-staff。创建真实 Codex task 的隔离 worktree 完成修复，返回真实 task id、artifact、验证、adoption 和 cleanup。没有真实工具时 TOOL_BLOCKED，不要用 subagent 替代。
```

检查：工具 event 中有真实 task/thread id 和 readback；id 与 receipt 一致；可写任务使用隔离 worktree；完成后有 cleanup。

## 真实软件开发

```text
使用 $agency-chief-of-staff。先复现订单金额等于阈值时折扣错误，再做最小修复并补回归测试；只有代码路径探索确实可独立且能改善结果时才使用 codebase-researcher。
```

检查：有失败复现；修改实现与测试而不是 README；相关测试由红到绿；普通局部修复不因流程完整感强制 reviewer。

```text
使用 $agency-chief-of-staff，并在需要 API contract 判断时显式使用 $api-design。为订单摘要增加一个跨文件 API 字段，保持旧调用兼容，运行接口与集成测试，再做独立审核。
```

检查：领域 Skill 被实际选择或明确报告不可用；architect/implementation 边界清楚；跨文件改动和兼容测试存在。

## 负例

这些普通请求不应自动启动幕僚长：

```text
把这句话翻译成英文。
```

```text
修复 utils.py 里的 off-by-one 并跑对应单测。
```

```text
review 这个小 diff，先列阻塞问题。
```
