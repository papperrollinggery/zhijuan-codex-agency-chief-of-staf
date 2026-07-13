# agency-chief-of-staff vNext 设计决策

## 目标

把当前轻量 outcome-owner 主干补成可用于真实软件开发的 Skill：主线程继续负责研究、实现、验证和收敛；只有并行、隔离或独立判断有实际收益时，才使用少量专业 Agent。

## 当前事实

- 当前 `SKILL.md` 为 199 行，已具备 Goal、研究、执行、验证、cold review、真实 task/thread 和发布边界。
- 当前 runtime allowlist 有 9 个文件，安装器能原子安装 canonical/legacy 双入口，但不分发专业 Agent 模板。
- 当前仓库没有 `.codex/agents/*.toml`；旧基线有 16 个角色，但指令窄化、sandbox 和领域 Skill 绑定不足。
- 当前 17 个行为 contract 与真实 model-smoke 主要覆盖激活、README 单行写入、worker bypass 和 reviewer 读回，不能充分证明真实开发。
- `quality_gate.sh` 的 native receipt 单测依赖源工作树 clean，导致合法未提交变更期间无法运行完整门禁。

## 官方依据

- [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)：项目级 custom agent 位于 `.codex/agents/*.toml`，必填 `name`、`description`、`developer_instructions`，可设置 `sandbox_mode` 与 `skills.config`。
- [Why subagent workflows help](https://learn.chatgpt.com/docs/agent-configuration/subagents#why-subagent-workflows-help)：优先把读多写少的探索、测试和日志分析并行化；并行写入需要更谨慎。
- [Build skills](https://learn.chatgpt.com/docs/build-skills)：Skill 应采用 progressive disclosure，主 `SKILL.md` 保持聚焦，详细流程放 references，确定性逻辑放 scripts。

## 决策

1. 保留轻量主干，不恢复 16 人常驻组织。
2. 新增五个窄职责配置：`codebase-researcher`、`technical-architect`、`developer`、`reviewer`、按需 `test-debugger`。
3. 项目 `.codex/agents/` 用于本仓库真实开发；同源模板进入 runtime bundle。Agent 配置不固定模型，research/architecture/review/debug 为 `read-only`，developer 为 `workspace-write`。
4. 默认安装仍只安装双 Skill bundle；专业 Agent 通过单独脚本显式安装到用户指定的 `.codex/agents`。脚本允许把已安装领域 Skill 绑定为 `skills.config`，但拒绝绑定 canonical/legacy 自身。
5. Worker packet 只禁止递归调用本 Skill 的两个 slug，不再禁止全部 `$slug`；经过选择的领域 Skill 可以在 packet 中显式调用。
6. 新增软件开发场景矩阵与可复现 fixture，覆盖 Bug 回归、跨文件/API、架构边界、失败测试诊断、领域 Skill、缺陷审核。离线 contract、真实 model/native-task 行为和独立审核分别给证据。
7. 修复测试对当前 worktree clean 的隐式依赖；真实发布 receipt 仍保持 clean-source fail-closed。

## 指令隔离边界

- 禁止创建、修改或注入用户全局、仓库主工作区及项目根位置的 `AGENTS.md`。
- 允许在隔离 subagent、Codex task/s-thread 中使用任务 prompt、worker packet、`.codex/agents/*.toml`、`skills.config` 或仅属于该执行面的临时指令。
- 验证必须对比主位置 `AGENTS.md` 的前后哈希/缺失状态，并确认安装 manifest 不包含 `AGENTS.md`。

## 最小修改面

- 主流程：`SKILL.md`、`references/software-development.md`。
- Agent：`.codex/agents/*.toml`、`assets/codex_agents/*.toml`、`assets/agent-routing.json`。
- 安装/验证：`scripts/install_agent_profiles.py`、`scripts/validate_agent_profiles.py`、现有 installer/package validator、相关单测和门禁。
- 行为证据：开发 fixture/contract、真实 native task smoke、独立 cold review。

## 停止条件

结构、安装、Agent 解析、场景 contract、真实开发行为、双入口 parity、隔离边界、独立审核和合并后门禁均有当前证据；无 P0/P1；`main` 已推送；本任务创建的执行面已归档或有明确 cleanup blocker。
