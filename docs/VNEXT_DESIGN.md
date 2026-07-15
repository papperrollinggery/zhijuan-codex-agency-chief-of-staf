# agency-chief-of-staff vNext 设计决策

> Status: Accepted design record; implementation state superseded by the `v0.2.0-rc.3` source tree
>
> As of: 2026-07-15
>
> Superseded by: the [`v0.2.0-rc.3` source contract](../CHANGELOG.md#v020-rc3---2026-07-15); `v0.2.0-rc.2` remains a historical prerelease baseline
>
> Evidence boundary: 本文记录设计时的宿主与接口快照，不证明当前 Codex 版本兼容性、模型行为、native task/thread 行为或 stable release eligibility。

## 目标

把当前轻量 outcome-owner 主干补成可用于真实软件开发的 Skill：主线程继续负责研究、实现、验证和收敛；只有并行、隔离或独立判断有实际收益时，才使用少量专业 Agent。

## 当时事实（2026-07-15 快照）

- 五个窄职责 profile 已有项目配置与 runtime 同源模板；离线 TOML/schema 通过不代表当前宿主真的能按名称选择它们。
- 当时读回的 Codex CLI `0.144.3` native subagent schema 只有通用 `task_name`，没有 `agent_type` / `name` 选择字段；当时观察到的 child state 中 `agent_role` 为空。该快照不是当前版本兼容性声明。
- 官方 custom-agent 文档描述了按 profile 名称选择的目标能力，但当时可调用接口与文档尚未收敛。把发布等待在该接口上会形成外部阻塞。
- 主线程本来就是合法 outcome owner；真正不可替代的缺口是带真实权限边界、独立上下文和可审计 readback 的只读专业审查。

## 官方依据

- [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)：项目级 custom agent 位于 `.codex/agents/*.toml`，必填 `name`、`description`、`developer_instructions`，可设置 `sandbox_mode` 与 `skills.config`。
- [Why subagent workflows help](https://learn.chatgpt.com/docs/agent-configuration/subagents#why-subagent-workflows-help)：优先把读多写少的探索、测试和日志分析并行化；并行写入需要更谨慎。
- [Build skills](https://learn.chatgpt.com/docs/build-skills)：Skill 应采用 progressive disclosure，主 `SKILL.md` 保持聚焦，详细流程放 references，确定性逻辑放 scripts。

## 决策

1. 保留轻量主干，不恢复 16 人常驻组织。
2. 新增五个窄职责配置：`codebase-researcher`、`technical-architect`、`developer`、`reviewer`、按需 `test-debugger`。
3. 项目 `.codex/agents/` 保留为未来 native 命名派发的可选增强；同源模板进入 runtime bundle。Agent 配置不固定模型，research/architecture/review/debug 为 `read-only`，developer 为 `workspace-write`。
4. 默认安装仍只安装双 Skill bundle；专业 Agent 通过单独脚本显式安装到用户指定的 `.codex/agents`。脚本允许把已安装领域 Skill 绑定为 `skills.config`，但拒绝绑定 canonical/legacy 自身。
5. Worker packet 只禁止递归调用本 Skill 的两个 slug，不再禁止全部 `$slug`；经过选择的领域 Skill 可以在 packet 中显式调用。
6. 新增随包提供的 `cli-profile-compat` 通道：只读 profile 由独立 `codex exec` 执行，强制结构化只读策略、禁用递归 subagent、固定系统工具 `PATH`、冻结执行输入、绑定实际 tool output，并从 state DB/rollout 校验身份、模型、直接 artifact read、唯一终态、AGENTS 不变和归档；reviewer/researcher 额外要求 exit-0 的独立 `git diff` 读回；兼容收据不声称 cold-context isolation 已验证。
7. `developer` 不使用 CLI 兼容通道；写任务留在主 outcome-owner 或隔离 worktree，避免用提示词伪造写权限隔离。
8. native named-profile 接口存在且可读回时优先使用；缺失时立即走兼容通道。发布不再依赖未来接口。
9. 新增软件开发场景矩阵与可复现 fixture，覆盖 Bug 回归、跨文件/API、架构边界、失败测试诊断、领域 Skill、缺陷审核。离线 contract、真实 model/native-task/compat 行为和独立审核分别给证据。
10. 修复测试对当前 worktree clean 的隐式依赖；真实发布 receipt 仍保持 clean-source fail-closed。

## 指令隔离边界

- 禁止创建、修改或注入用户全局、仓库主工作区及项目根位置的 `AGENTS.md`。
- 允许在隔离 subagent、Codex task/thread 或 `cli-profile-compat` 独立会话中使用任务 prompt、worker packet、`.codex/agents/*.toml`、`skills.config` 或仅属于该执行面的 profile 指令。
- 验证必须对比主位置 `AGENTS.md` 的前后哈希/缺失状态，并确认安装 manifest 不包含 `AGENTS.md`。

## 最小修改面

- 主流程：`SKILL.md`、`references/software-development.md`。
- Agent：`.codex/agents/*.toml`、`assets/codex_agents/*.toml`、`assets/agent-routing.json`。
- 安装/验证：`scripts/install_agent_profiles.py`、`scripts/run_profile_compat.py`、`scripts/validate_agent_profiles.py`、现有 installer/package validator、相关单测和门禁。
- 行为证据：开发 fixture/contract、真实 native task 或 compat smoke、独立 cold review。

## 当时的任务停止条件（非当前 release gate）

以下条件属于这次设计任务的历史完成标准。当前发布状态必须以当前源文件、当前验证和 Releases 页面为准。

结构、安装、Agent 解析、场景 contract、真实开发行为、双入口 parity、兼容通道、隔离边界、独立审核和合并后门禁均有当前证据；无 P0/P1；`main` 已推送；本任务创建的执行面已归档或有明确 cleanup blocker。native custom-agent 接口是否到达不属于停止条件。
