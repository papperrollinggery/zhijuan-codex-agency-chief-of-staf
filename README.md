# Agency Chief of Staff for Codex

一个结果负责型 Codex 幕僚长 Skill：把复杂任务从目标澄清推进到研究、规划、执行、验证、独立审核和最终交付。

它不靠堆角色或 receipt 证明自己工作，也不向用户全局、仓库主工作区或项目根 `AGENTS.md` 注入路由。主线程对结果负责；原生 subagents、Goal、真实 task/thread/worktree 都按任务需要使用。

## 适用场景

- 明确调用 `$agency-chief-of-staff`。
- 要求“幕僚长 / Codex Agency / 完整团队”负责复杂任务闭环。
- 要求先研究，再规划、执行、验证和审核。
- 长任务需要 Goal、checkpoint 和停止条件。
- 需要并行探索、实现或独立 cold review。
- 需要 release readiness、Skill hardening、多文件可靠性或客户交付质量审核。
- 明确要求真实 Codex task/thread、隔离 worktree、thread id、receipt 或 cleanup 证明。

普通小问题不应触发本 Skill，除非用户显式调用。

## 核心工作流

```text
目标与完成标准
  → 当前事实研究
  → 最小计划
  → 主线程执行 + 按收益委派
  → 真实验证
  → 独立 cold review
  → 修复与复验
  → 简洁交付
```

关键设计：

- 主线程是 outcome owner，可以直接研究、编辑、测试、整合和交付。
- 按收益使用最少必要的 subagent：提供 codebase researcher、technical architect、developer、reviewer 和按需 test-debugger 五个窄职责 profile，不恢复固定 16 角色组织。
- named custom-agent 接口只是可选增强；接口缺失时，四个只读 profile 走永久 CLI 兼容通道，写入仍由主线程或隔离 worktree 完成。
- 领域 Skill 可以显式绑定给专业 Agent；只禁止两个主控入口递归调用，不再一刀切禁止全部 `$slug`。
- Goal 只用于明确的长期目标，不为短任务生成 Goal Ledger。
- 真实 task/thread 只在用户明确要求真实独立执行面时使用。
- 只有机器审计确实需要时才输出结构化 receipt。
- 默认一次 cold review 加一次修复后的定向复核，避免无限 review wave。
- 声称独立审核已完成时，必须能回查非空 reviewer/task id、与该 id 绑定的唯一终态，以及 reviewer 对当前 artifact 的直接读回；空 `wait`、主线程自审、或只声明 `none` / `fork_context:false` 均不算。工具未明确回显上下文隔离时，必须披露 `COLD_CONTEXT_ISOLATION: UNVERIFIED`。

## 不依赖 AGENTS.md

激活路径只有：

1. 显式 `$agency-chief-of-staff`；
2. frontmatter `description` 的隐式匹配；
3. `agents/openai.yaml` 中的 UI metadata 和 default prompt；
4. 仅为旧 prompt 保留的显式兼容入口 `$zhijuan-codex-agency-chief-of-staf`。

旧入口关闭隐式调用；同一请求同时出现两个 slug 时只执行 canonical 入口。

安装器不会读取、创建、追加或修改项目/全局 `AGENTS.md`，也不提供 routing 注入参数。已有 `AGENTS.md` 仍作为项目规则正常生效，但不是本 Skill 的安装或激活机制。隔离 subagent/task 可以通过 worker packet、项目 `.codex/agents/*.toml`、`skills.config` 或临时任务指令获得专业上下文；验证必须证明这些配置没有覆盖主位置规则。

## 安装

要求 Python 3.10+。

```bash
python3 scripts/install_skill.py
```

默认一次安装两个同源 runtime bundle：

```text
~/.agents/skills/agency-chief-of-staff
~/.agents/skills/zhijuan-codex-agency-chief-of-staf
```

前者是 canonical 入口；后者只兼容旧显式调用，不是第二份维护源。

覆盖不同版本：

```bash
python3 scripts/install_skill.py --force
```

安装器只复制运行时 allowlist，并把两个 bundle 作为一个可回滚的 pair transaction 更新；不会把 GitHub workflow、历史 validation、README 或仓库管理文件打进运行时 Skill。

专业 Agent 模板随 runtime 分发，但不会默认写入任何项目或用户配置。只有显式选择目标项目时才安装：

```bash
python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents
```

可把已安装领域 Skill 确定性绑定给一个 profile：

```bash
python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents \
  --skill developer=/absolute/path/to/domain-skill/SKILL.md
```

该脚本只管理五个同名 TOML，保留目标目录中的其他文件；冲突时 fail closed，显式 `--force` 才替换。它拒绝把 canonical/legacy 主控 Skill 绑定回子 Agent。

## 不等待 Custom Agent 接口

如果当前 Codex 的 native subagent schema 不能按 `reviewer` 等名称选择 profile，直接使用随 runtime 安装的永久兼容 runner：

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

该通道只支持 `read-only` profile。它创建独立持久化 `codex exec` 会话，以参数数组和最小非敏感进程环境执行，显式禁用递归 subagent，设置有界超时，并核验 OpenAI provider/model/reasoning、结构化只读策略、直接 artifact read、严格终态、`AGENTS.md` 不变与 archive。收据固定写 `execution_mode: cli-profile-compat`、`native_custom_agent_selected: false`，不会把普通会话冒充成原生 `agent_role=reviewer`。`developer` 写任务仍走主线程或隔离 worktree。

## 使用

最短调用：

```text
使用 $agency-chief-of-staff 把这个任务做到可验证完成。
```

长期目标：

```text
使用 $agency-chief-of-staff。为这个迁移设定 Goal，先研究现状，再规划、执行、验证和独立审核，直到满足停止条件。
```

真实线程：

```text
使用 $agency-chief-of-staff。创建真实隔离 worktree task 完成实现，返回真实 id、产物、验证、adoption 和 cleanup；工具不可用时明确 TOOL_BLOCKED。
```

## 当前模型能力的使用方式

本次架构按当前 Codex/前沿模型指导设计：更强的意图理解、原生 Goal、原生 subagent 并行、动态模型选择和更高效的短提示。Skill 不固定模型 slug；宿主默认选择当前合适模型，必要时才为轻量扫描和高难审核分别选择效率或深度配置。具体“已验证模型”只以当次 model-smoke 或 native-task receipt 为准；model-agnostic design 不等于已在官方最新模型上验证。

相关官方说明：

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)
- [Why subagent workflows help](https://learn.chatgpt.com/docs/agent-configuration/subagents#why-subagent-workflows-help)
- [Long-running work](https://learn.chatgpt.com/docs/long-running-work)
- [Latest model guidance](https://developers.openai.com/api/docs/guides/latest-model)

## 验证层级

验证名称必须诚实区分：

1. `package/contract`：离线检查 frontmatter、runtime manifest、五个 Agent TOML、项目/模板 parity、领域 Skill 绑定、场景 schema 和安装行为；不声称证明模型行为。
2. `model-smoke`：在无本项目 routing、禁用 plugins/apps、最小环境变量的临时仓库里真实调用当前 Codex 模型，保存 event JSONL 和最终输出；子集运行只会得到 `passed_partial`。
3. `profile-compat-smoke`：当前 named custom-agent 接口不可用时，从已安装 canonical bundle 发起独立只读 CLI profile 会话，核验 state DB/rollout、直接 artifact read、严格 reviewer schema、AGENTS 不变和 cleanup。
4. `native-task-smoke`：当前接口支持按名称选择并能读回角色时，从已安装 canonical bundle 发起真实 Codex Desktop task，核验 provider/model/effort、reviewer 绑定、安装 manifest 和 cleanup。
5. `threadops-smoke`：只有发布目标明确要求真实 task/thread 证明时，使用 Codex Desktop 工具核验真实 id、readback、worktree 和 cleanup。

运行离线质量门：

```bash
bash scripts/quality_gate.sh .
```

运行真实模型前测前，先使用专用、低权限的 eval 凭据。被测 Skill 与 case 和 Codex 进程同属当前 OS 用户，临时 `auth.json` 理论上可被恶意被测内容读取；环境变量最小化和输出脱敏不是安全边界。对不可信 PR，必须放进一次性 OS 用户或容器，不能使用主账号凭据。

```bash
export CODEX_EVAL_AUTH_JSON=/path/to/dedicated-eval-auth.json
export CODEX_EVAL_CODEX=/absolute/path/to/codex
```

运行全量真实模型前测：

```bash
python3 scripts/run_model_evals.py \
  --root . \
  --out validation/current/model-smoke-$(date +%Y%m%d-%H%M%S) \
  --codex-executable "$CODEX_EVAL_CODEX" \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class dedicated \
  --acknowledge-auth-readable-to-eval-process
```

Runner 只允许 `read-only` / `workspace-write`，拒绝危险 sandbox、越界 case id/artifact 路径、既有输出目录和 symlink；全部 case 复用冻结的 runtime snapshot，收据绑定 Skill manifest、case 文件和 runner hash，并检测运行中源码漂移。host-default 的模型名若只能从诊断日志推断，不会被视为稳定的 release model identity；本 RC 的 prerelease eligibility 要求显式 `gpt-5.6-sol`、`max`、同一 session 内的身份三元组和专用凭据，stable eligibility 还要求没有未测能力。

`--auth-credential-class primary` 只允许生成诊断收据，永远不具备 prerelease/stable eligibility；公开发布证据必须使用 `dedicated`。

当前 Codex Desktop 真正读回 named reviewer 绑定时可使用 native-task receipt；该路径是可选增强，不是兼容发布前提，也不声称凭据隔离或跨平台稳定发布：

```bash
python3 scripts/verify_native_task_receipt.py \
  --state-db ~/.codex/state_5.sqlite \
  --source-root . \
  --installed-root ~/.agents/skills \
  --parent-id <thread-id> \
  --reviewer-id <reviewer-thread-id> \
  --model gpt-5.6-sol \
  --reasoning-effort max \
  --parent-final-marker '<expected parent completion marker>' \
  --reviewer-final-marker 'REVIEW_VERDICT: PASS' \
  --reviewer-read-marker '<exact artifact fact read by reviewer>' \
  --reviewer-artifact '<absolute regular-file path read by reviewer>' \
  --require-archived \
  --require-clean-source
```

宣称无人值守、跨宿主或 stable 公共发布时，仍必须使用专用低权限凭据的隔离 CLI model-smoke。

发布前轻量安装复核：

```bash
bash scripts/release_smoke.sh .
```

v0.1.x 的旧 validation receipts 保留在 Git 历史和对应 tag 中，不进入当前 checkout 的 release gate，也不代表当前 HEAD 已验证。

## 运行时结构

```text
SKILL.md
agents/openai.yaml
references/
  real-threads.md
  delivery-review.md
  long-running-work.md
  history-audit.md
  software-development.md
assets/
  WORK_RECEIPT_TEMPLATE.yaml
  DELIVERY_EVIDENCE_TEMPLATE.yaml
  agent-routing.json
  codex_agents/*.toml
scripts/
  audit_historical_threads.py
  install_agent_profiles.py
  run_profile_compat.py
  validate_agent_profiles.py
```

兼容说明：slug 中的 `staf` 保留原包名，避免破坏现有显式调用。
