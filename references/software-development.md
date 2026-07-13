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
2. native schema 能按名称选择并读回 profile 时，记录 spawn 返回的非空 id/path；真实 task/thread 还要 readback 状态、cwd/worktree 和产物。
3. native schema 没有 profile 选择字段、拒绝该字段或 state 中没有角色绑定时，read-only profile 立即走下述 CLI 兼容通道；不要等待未来接口，也不要把普通 subagent 的提示词当 profile 证据。
4. 主线程验证 diff、测试和范围后记录采纳、部分采纳或拒绝。
5. 完成、失败或替换的 task/thread 及时归档；native subagent 终态返回后不重复唤醒。

## 永久 CLI 兼容通道

`scripts/run_profile_compat.py` 是 custom-agent 接口长期缺失时的正式执行面，不是临时诊断脚本。它只接受 `codebase-researcher`、`technical-architect`、`reviewer` 和 `test-debugger` 四个 `read-only` profile；`developer` 永远由主线程或隔离 worktree 执行。

最小调用：

```bash
python3 scripts/run_profile_compat.py \
  --profile reviewer \
  --packet /absolute/path/reviewer.packet.txt \
  --cwd /absolute/project \
  --model <explicit-non-Luna-model> \
  --reasoning-effort <effort> \
  --required-read /absolute/project/current-artifact \
  --required-read-marker '<hidden current fact>' \
  --required-final-marker '<same current fact>'
```

Runner 使用参数数组而非 shell 派发，忽略用户 model/provider 配置但保留 execpolicy rules，只向 Codex 进程传最小非敏感环境 allowlist；工具 shell 不继承调用者环境，只注入固定 `/usr/bin:/bin:/usr/sbin:/sbin`，避免 secret 与用户级可执行路径泄漏，同时保证系统 `git` 可调用。Runner 强制 OpenAI、显式非 Luna model、结构化 `read-only` sandbox、禁用 apps/remote plugins/递归 subagent，并设置 1–1800 秒有界超时（默认 300 秒）。无论正常、失败或超时，只要读到 `thread.started` 就先终止进程组并归档。随后从 state DB 和 rollout 读回真实 thread、provider/model/reasoning、直接 artifact read、唯一终态与 archive 状态，并比较全局和 worktree 的 `AGENTS.md` / `AGENTS.override.md` 前后状态。`reviewer` 与 `codebase-researcher` 还必须从项目根以单独命令成功执行 `git diff -- <artifact>`，并把 call/output 绑定进收据；退出码只从绑定 tool wrapper 的唯一结构化顶层数值字段读取，不扫描 stdout 文本。`git` 不可用、diff 未读或结构化退出码非 0 即 fail closed。

成功收据必须写 `execution_mode: cli-profile-compat`、`native_custom_agent_selected: false`、`native_agent_role: null`、`context_mode: standalone-cli-session`，并列出实际注入面、不可变输入哈希和绑定 tool-output 哈希。当前持久化状态不能证明父上下文隔离，必须保留 `cold_context_isolation: unverified`。这证明的是不同 thread 中的独立只读 profile 会话，不得改写成“原生 reviewer 角色已选中”或“cold-context isolation 已验证”。

## 验证边界

- TOML/schema、template parity 和安装测试只证明配置结构。
- 模型、native task smoke 或 `cli-profile-compat` 真实行为 smoke 才证明当前宿主行为；README 单行修改不等于真实开发能力。
- Bug、跨文件/API、架构边界、失败诊断、领域 Skill 和缺陷审核必须分别有当前证据。
- 隔离执行面指令不得改变用户全局、仓库主工作区或项目根位置的 `AGENTS.md`；验证前后哈希或缺失状态，并确认 runtime manifest 不含该文件。
