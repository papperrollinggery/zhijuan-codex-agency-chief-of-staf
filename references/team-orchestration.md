# Team Orchestration

团队计划由 Work Item 确定性生成，不要求调用方先写角色清单。旧 `resolve_role_route.py` 继续负责已选 Profile 的 Subagent 模型档路由；`resolve_team_plan.py` 先决定是否需要岗位、需要哪些岗位和几个实例。

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

等级描述任务复杂度，不是最低人数。活跃职位最多 5、同时并行最多 3、同时可写最多 2；团队规模始终是上限，不是目标。

## 硬规则

- 单文件、单目标、低风险、高耦合任务默认由 Root 单独完成。
- 非平凡代码或多文件交付至少安排一个独立 Reviewer。
- 跨模块接口或迁移考虑 Technical Architect。
- 独立研究流可创建多个 Researcher Instance。
- 写范围重叠不并行；并行写必须使用隔离 Worktree。
- 高耦合连续实现由 Root 执行，不拆成冲突写线程。
- Test Debugger 只在有真实失败或竞争根因信号时加入。
- Supervisor 只用于长期 Goal、发布、复杂归档或证据闭环。
- 不为满足人数或 Team Tier 安排岗位。

## 波次

```text
Wave 0：Execution Root 读取计划和项目状态
Wave 1：独立研究与架构判断
Wave 2：实现与文档工作
Wave 3：测试诊断，仅在需要时
Wave 4：独立 Review
Wave 5：Supervisor 收口，仅在需要时
```

Root 负责整合、验证和全局状态。Subagent 只返回范围内证据，不能改变 Task 生命周期或归档。

