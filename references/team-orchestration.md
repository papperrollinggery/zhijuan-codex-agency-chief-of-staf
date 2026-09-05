# Team Orchestration

团队计划由 Work Item 确定性生成，不要求调用方先写角色清单。旧 `resolve_role_route.py` 继续负责已选 Profile 的 Subagent 模型档路由；`resolve_team_plan.py` 先过净执行价值门，再决定是否需要岗位、需要哪些岗位和几个实例。Root 是默认执行者。

## 两层结构

- `position_instance` 是本任务中的具体责任位，包含工作项、读写范围、输出和波次。
- `profile` 是可复用执行能力，如 `codebase-researcher` 或 `reviewer`。

同一 Profile 可以有多个实例，但每个实例必须有不同 Work Item、不同读取范围和不同输出，并能真实并行。不得复制同一岗位凑人数，也不得用 Profile 名去重整个团队。

职位映射：

| Profile | 用户可见职位 |
|---|---|
| Execution Root | 项目总负责人 |
| codebase-researcher | 研究负责人 |
| technical-architect | 技术架构负责人 |
| developer | 实施负责人 |
| writer | 文档与交付负责人 |
| test-debugger | 测试诊断负责人 |
| reviewer | 独立质量负责人 |
| supervisor | 收口审计负责人 |

## 团队等级与评分

评分维度固定为 workstream count、dependency depth、uncertainty、risk、write conflict、specialist need、parallel gain、independent review need 和 duration scope。

```text
0–3   solo
4–6   lean_team
7–10  project_team
11+   program_team
```

分数与 Team Tier 描述任务复杂度，不是最低人数，也不能绕过净执行价值门。活跃职位最多 5、同时并行最多 3、同时可写最多 2；团队规模始终是上限，不是目标。

## 硬规则

- 单一研究、单一文档、普通单文件修改和高耦合连续实现默认由 Root 完成。
- 一个 Developer 可以负责边界清楚、委派净收益为正的实现流；多个 Developer 只用于可隔离、无写冲突、输出不同的实现流。跨模块接口迁移默认由 Technical Architect、Developer 与 Reviewer 分担判断、实施和独立验证；只有项目证据明确表明实现不可分割且高度耦合时，才由 Root 直接实施。普通单流多文件工作仍可由 Root 完成。
- Reviewer 只在显式审核、独立审核需求、高/关键风险、发布、安全、迁移或结构性跨模块变更时加入。
- 跨模块接口、迁移或高不确定架构判断考虑 Technical Architect。
- 独立研究流可创建多个 Researcher Instance。
- 写范围重叠不并行；并行写必须使用隔离 Worktree。
- 高耦合连续实现由 Root 执行，不拆成冲突写线程。
- Test Debugger 只在有真实失败或竞争根因信号时加入。
- Supervisor 只用于长期 Goal、发布、复杂归档或证据闭环。
- 不为满足人数或 Team Tier 安排岗位。
- 必需的 Architect 或 Reviewer 优先于可选 Researcher，不能被数量截断挤出。

## 波次

以下是初始职责顺序，不是无条件执行日历。Planner 按工作依赖调整 position 的实际 wave；共同前置完成后的独立流可以并行，互相依赖的流按顺序推进。同一 Profile 的工作被其它工作穿插时拆成分阶段实例，避免把合法 Work DAG 压成岗位循环。

```text
Wave 0：Execution Root 读取计划和项目状态
Wave 1：独立研究与架构判断
Wave 2：实现与文档工作
Wave 3：测试诊断，仅在需要时
Wave 4：独立 Review
Wave 5：Supervisor 收口，仅在需要时
```

Root 负责整合、验证和全局状态；发布动作仍由获授权的 Root 负责，read-only Supervisor 只审计证据。Subagent 只返回范围内证据，不能改变 Task 生命周期或归档。依赖 Root 的未完成工作列入 pending，派发前再次确认完成状态。波次计划必须真实满足同时并行不超过 3、同时可写不超过 2，并服从宿主或项目更低上限。
