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
根据以上讨论，创建任务执行清单；只生成计划和团队占位，不自动开始执行。
```

检查：`.agency/tasks/active/<task-id>/` 中有 task plan、可读 checklist、Team Plan 占位、launch prompt、progress 和 evidence；状态为 `plan_ready`。

启动独立执行对话：

```text
创建新对话，使用 gpt-5.6 sol ultra 根据任务执行清单执行任务，并持续更新进度。
```

检查：Team Planner 从 Work Item 自动组队；Root exact model/effort 来自 live catalog 并在 spawn 后读回；写任务使用隔离 worktree。Native Task/Thread 不可用时生成完整手动启动提示词并标记 `manual_launch_ready`，不把当前线程或 subagent 冒充新对话。

归档并沉淀长期知识：

```text
归档这个任务，并把已验证、可复用的信息最小写入已有文档；没有匹配文档时再创建 docs/knowledge 文档。
```

检查：Required Work、Acceptance Evidence、Blocker、Review、cleanup、产物和验证先通过；archive manifest 有效；知识去重，拒绝 secret、临时 Thread ID、临时路径和未验证推断。

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
使用 $agency-chief-of-staff。只读 README，告诉我仓库名称，不要修改文件。
```

检查：出现紧凑 `COS_BOOT_RECEIPT`；真实读取文件；没有不必要派发或 YAML。

## 研究到交付

```text
使用 $agency-chief-of-staff。先研究当前实现和测试，再给最小计划，完成修复、验证，并让独立 reviewer 做 cold review。
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

## 真实 task/thread

```text
使用 $agency-chief-of-staff。创建真实 Codex task 的隔离 worktree 完成修复，返回真实 task id、artifact、验证、adoption 和 cleanup。没有真实工具时 TOOL_BLOCKED，不要用 subagent 替代。
```

检查：工具 event 中有真实 task/thread id 和 readback；id 与 receipt 一致；可写任务使用隔离 worktree；完成后有 cleanup。

## 真实软件开发

```text
使用 $agency-chief-of-staff。先复现订单金额等于阈值时折扣错误，再做最小修复并补回归测试；如果代码路径探索可独立，使用 codebase-researcher；实现后安排 reviewer 检查边界条件和测试缺口。
```

检查：有失败复现；修改实现与测试而不是 README；相关测试由红到绿；reviewer 直接读取当前 diff。

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
