# Software Development Routing

在真实软件开发、架构、测试调试或安全/发布任务中读取本文件。

## 结果所有权

主线程始终是 outcome owner。先读取规则、`git status --short`、现有实现和测试，再决定是否派发。强耦合连续修改、核心架构取舍和最终整合留在主线程；只有隔离、并行或独立判断能带来明确收益时使用专业 Agent。

## 场景矩阵

| 场景 | 主线程默认动作 | 可选专业 Agent | 最小证据 |
|---|---|---|---|
| 小 Bug | 复现、最小修复、回归测试 | `codebase-researcher`、`reviewer` | 失败复现、测试由红到绿、diff |
| 跨文件功能/API | 锁定 contract 与兼容边界后实现 | `technical-architect`、隔离 `developer`、`reviewer` | 接口测试、跨文件集成、兼容检查 |
| 架构重构 | 主线程决定取舍和迁移顺序 | `codebase-researcher`、`technical-architect`、`reviewer` | 当前数据流、迁移/回滚、行为不变测试 |
| 测试/日志失败 | 先分类产品缺陷、测试缺陷、环境问题 | `test-debugger`，需要修复时再用 `developer` | 复现命令、决定性日志、定向复验 |
| 领域开发 | 选择一个已安装且直接相关的领域 Skill | 对应 architect/developer/reviewer | Skill 选择理由、实际调用、领域门禁 |
| 安全/发布 | 当前 artifact 与 fail-closed 证据 | 独立 `reviewer`，必要时领域安全 Skill | 当前 HEAD、完整门禁、安装 parity、残余风险 |

## 专业 Agent

- `codebase-researcher`：只读代码地图、复现路径、依赖和证据。
- `technical-architect`：只读接口、数据流、约束、迁移和最小架构边界。
- `developer`：`workspace-write` 的隔离写 lane；只改 packet 明确范围并运行测试。
- `reviewer`：只读独立审查；不能修复或接受主线程预判。
- `test-debugger`：只读失败诊断；只有测试或日志分析有独立收益时启用。

默认最多启用满足任务所需的最少角色。多个 writer 必须使用不重叠文件或隔离 worktree。

## 领域 Skill 路由

Worker packet 可以包含经过选择的领域 `$skill-slug`，但不得包含 `$agency-chief-of-staff` 或 `$zhijuan-codex-agency-chief-of-staf`。选择规则：

1. 先从当前可用 Skills 中确认候选真实存在且与任务直接相关。
2. 只有专业知识或工具流程会实质影响结果时才绑定；普通语言/框架任务不为“完整感”绑定 Skill。
3. 在 packet 的委派目标或验证要求中写明准确领域 slug、用途和失败回退；worker 必须按 Skill 指令读取并使用，无法读取时报告 `SKILL_UNAVAILABLE`。
4. 若需要确定性 Agent 配置，在显式 opt-in 安装时使用 `--skill ROLE=/absolute/path/to/SKILL.md` 生成 `[[skills.config]]`。
5. Agent 配置不固定模型；除非用户明确指定，由宿主选择当前合适的非 Luna 模型和 reasoning。

不得因为允许领域 Skill 而放开递归主控。合法 worker 收到完整 packet 后只执行范围，不启动主控、不继续派发。

## 安装专业 Agent

Skill 双入口安装不会默认写入任何 Agent 配置。只有用户或项目明确选择时，运行：

```bash
python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents
```

绑定一个领域 Skill：

```bash
python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents \
  --skill developer=/absolute/path/to/domain-skill/SKILL.md
```

安装器只管理五个同名 TOML 文件，保留目标目录中的其他文件；冲突时 fail closed，只有显式 `--force` 才替换托管文件。它不读取或写入 `AGENTS.md`，并拒绝把本 Skill 的两个入口绑定回子 Agent。

## 派发与回收

1. 使用主 `SKILL.md` 的完整 worker packet；在委派目标中点名 profile 和必要领域 Skill。
2. 记录 spawn 返回的非空 id/path；真实 task/thread 还要用相应工具 readback 状态、cwd/worktree 和产物。
3. 主线程验证 diff、测试和范围后记录采纳、部分采纳或拒绝。
4. 完成、失败或替换的 task/thread 及时归档；native subagent 终态返回后不重复唤醒。

## 验证边界

- TOML/schema、template parity 和安装测试只证明配置结构。
- 模型或原生 task smoke 才证明当前宿主行为；README 单行修改不等于真实开发能力。
- Bug、跨文件/API、架构边界、失败诊断、领域 Skill 和缺陷审核必须分别有当前证据。
- 隔离执行面指令不得改变用户全局、仓库主工作区或项目根位置的 `AGENTS.md`；验证前后哈希或缺失状态，并确认 runtime manifest 不含该文件。
