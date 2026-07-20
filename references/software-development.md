# Software Development

在真实代码、架构、测试调试或安全/发布工作中读取。本文件帮助完成软件结果，不要求创建团队或持久化流程。

## 内容路径

1. 读取适用规则和 `git status --short`，保护已有修改。
2. 定位现有实现、调用链、测试和相似模式。
3. 明确行为差距、兼容边界和最小修改面。
4. 先完成强耦合判断与实现，再处理必要文档或控制面。
5. 运行定向测试；根据影响补集成、构建、静态检查或人工验证。
6. 读回 diff 与验证结果后交付。

小 Bug、单文件明确修复、单一研究或单一文档默认由 Root 完成。不要因为任务属于软件开发就自动派 Developer、Writer 或 Reviewer。

## 场景与最低证据

| 场景 | Root 重点 | 最低证据 | 何时增加独立角色 |
|---|---|---|---|
| 小 Bug | 复现、最小修复 | 症状或回归测试、diff | 根因竞争或高风险才加 |
| 跨文件功能 | contract、兼容、集成 | 接口/集成测试、相关回归 | 独立架构判断或并行流有收益 |
| 架构迁移 | 数据流、迁移与回滚 | 当前调用链、迁移测试 | Architect；高风险时 Reviewer |
| 测试/日志失败 | 区分产品、测试、环境 | 复现命令、决定性日志 | 多个竞争根因才用 Test Debugger |
| 安全/发布 | 当前 artifact、fail closed | 完整门禁、残余风险 | 必须独立 Reviewer；必要时领域安全 Skill |

## 专业能力

- `codebase-researcher`：独立读取域、代码地图、复现路径和证据。
- `technical-architect`：跨模块接口、数据流、迁移和最小架构边界。
- `developer`：只有独立写 lane 能安全隔离并缩短总时长时使用。
- `writer`：只有文档是独立交付流且不会增加整合成本时使用。
- `test-debugger`：只用于真实失败或竞争根因。
- `reviewer`：高风险、发布、安全、迁移、用户明确要求，或独立判断明显提高质量时使用。
- `supervisor`：仅长期 Goal、复杂发布或证据闭环；不是固定收口岗位。

领域 Skill 只有在专业知识或工具流程会实质影响结果时绑定。Worker packet 可以点名相关领域 Skill，但不得包含本 Skill 的 canonical/legacy slug，也不得让 Worker 继续派发。

## 派发与项目 Profile

Direct/Focused 使用宿主原生终端 Subagent；只传目标、最小上下文、读写范围、验证和返回物。Root 验证产物后决定采纳，不让 Subagent 更新全局 Task State。

Durable Execution Launch 才运行 Team Planner。项目 Profile 只在已选岗位需要且用户已启动执行时用 `scripts/prepare_team_runtime.py --apply` 准备；Selected-only，不写全局 Agent 配置，不写项目 `AGENTS.md`。

需要精确 Subagent 模型/成本时才读取 [model-routing-and-budget.md](model-routing-and-budget.md)。只有 Assured 模式确需独立身份证明且 Native named profile 无法读回时，才使用 `scripts/run_profile_compat.py` 的 read-only fallback；普通任务不运行 CLI receipt 流程。写入型 Developer/Writer 不走该 fallback。

## Git 与并行

Git 是项目工具，不是固定流程：用户要求提交时再提交；需要隔离写或用户明确要求时才创建 Worktree；未授权不 push、发布或创建 PR。

并行前验证依赖与写范围。写范围重叠、共享状态、高耦合连续实现和探索性调试留给 Root 串行。并行写必须使用隔离 Worktree，并在整合后跑全套相关测试。

## 证明边界

- 测试 PASS 只证明覆盖到的行为，不等于领域质量或发布完成。
- Profile TOML、schema 和安装 parity 不证明实际模型或角色已运行。
- 真实 Task/Thread、模型和 Effort 只在当前 readback 一致时成立。
- Subagent 自述不是完成证据；Root 必须读 diff、artifact 和验证结果。
- 不修改或注入 `AGENTS.md` 来激活本 Skill 或角色。
