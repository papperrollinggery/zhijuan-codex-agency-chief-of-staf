# Agency Chief of Staff for Codex

[![CI](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/actions/workflows/ci.yml/badge.svg)](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个内容优先、结果负责的 Codex 协调 Skill。它默认把上下文和工具预算留给项目研究、判断、实现与验证；只有协调真实并行、保持跨对话连续性或证明高风险结果时，才增加团队、`.agency` 状态、Task/Thread、模型 readback 或独立审核。

内部按最轻执行面选择 Direct、Focused、Durable 或 Assured。普通单次任务直接完成；多步骤单会话任务只保留短计划；明确需要跨对话时才进入持久生命周期；发布、安全、高风险迁移或审计才进入强证明路径。安装器和默认运行不会向用户配置、仓库主工作区或项目根 `AGENTS.md` 注入路由。

## 用户看到的交互

聊天是产品前台，技术证据留在后台。项目生命周期显示需求讨论、创建执行清单、启动执行对话、团队执行、验证和归档；进度只在真实事件发生时更新，不发送虚构百分比或固定间隔空状态。内部 Profile、exact model ID、线程 schema、哈希、JSON/YAML、命令回值和调试字段不会作为主要界面出现。

Visualization 只在它比短文本或小表格明显更容易理解时使用，不再按步骤数量自动触发。内建 renderer 仍保留数据校验、安全文件读取、确定性 fallback 和宿主 mount readback；普通任务不会为了展示完整感先运行这套流程。

## 一览

| 项目 | 当前事实（2026-07-21） |
| --- | --- |
| Canonical Skill | `$agency-chief-of-staff` |
| 兼容入口 | `$zhijuan-codex-agency-chief-of-staf`，仅显式调用 |
| 核心模型提供方 | OpenAI / Codex；Claude/Fable 仅为默认关闭的可选 advisor 位 |
| Python | 3.10+ |
| 最新 stable tag | [`v0.1.7`](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases/tag/v0.1.7) |
| 最新 prerelease tag | [`v0.2.0-rc.3`](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases/tag/v0.2.0-rc.3) |
| 当前 checkout | `v0.3.0-rc.4` 本地源码候选；未打 tag、未发布 |

入口：[文档索引](docs/README.md) · [内容优先设计依据](docs/CONTENT_FIRST_DESIGN.md) · [LLM 索引](llms.txt) · [发现性与发布元数据](docs/REPOSITORY_DISCOVERY.md) · [Changelog](CHANGELOG.md) · [示例](examples) · [贡献](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [行为规范](CODE_OF_CONDUCT.md) · [全部 Releases](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases)

本 README 正文描述 `v0.3.0-rc.4` 本地源码候选。它不是当前 GitHub Release，也不代表任一宿主的已安装 Skill 已更新。已发布 tag 保留各自当时的 README 和能力，不会因为主分支文档更新而获得后续功能：

| 版本线 | 能力边界 |
| --- | --- |
| `v0.1.7` stable | 历史稳定线；不包含本文的七角色、live catalog adapter、native routing configurator 或 fragment renderer |
| `v0.2.0-rc.2` prerelease | 包含五角色 RC、旧 visualization/data contract 与 native-task receipt |
| `v0.2.0-rc.3` prerelease | 七角色、current-catalog direct 路由/readback、可恢复 native routing 配置和 fragment/fallback/manifest 流程；named profile 与 host mount 仍按宿主能力 fail closed |
| `v0.3.0-rc.2` 本地源码候选 | 在 rc.1 生命周期上增加内容优先执行面、净执行价值门、懒资产、递归 fail-closed、单命令完成收口和结果/开销评测；尚未发布，真实 Model/Native 行为仍需单独 smoke |
| `v0.3.0-rc.3` 本地源码候选 | 在 rc.2 上补齐 Native `create_thread` transport 解包、user-owned source 证明与 v1.0 raw session 兼容回填；尚未发布，安装态 Model/Native 行为仍需单独 smoke |
| `v0.3.0-rc.4` 本地源码候选 | 用真实生命周期 trace 把持久执行收敛为内容优先快路径，增加失败调用也计数的 tool-event 预算、无歧义完成证据 argv、恢复/归档边界与评测防伪；尚未发布，安装态 Native 行为仍需单独 readback |

## v0.3 迁移

- v0.1 的固定重型团队和 16 角色组织已废弃，不会恢复。
- v0.2 的轻量主线程/Direct Mode 保留，继续服务单次、明确、可在一个闭环完成的任务。
- v0.3 的四阶段生命周期只在项目型意图出现时启用；不要求所有任务创建 `.agency` 或 Thread。
- Canonical 继续允许自然语言隐式调用；Legacy 只兼容旧显式 slug。
- 专业 Profile 按当前 Team Plan 做 Selected-only 项目准备，不默认安装全部七个，也不写全局 Agent 配置。
- Execution Root 模型政策与 Subagent 模型成本档完全分开；Root 可以请求 GPT-5.6 Sol Ultra，Subagent 继续按任务选择 Efficient/Balanced/Judgment。
- 每个治理动作必须解锁项目判断、协调真实并行或证明当前结果；否则跳过。复杂度本身不再自动创建持久状态、团队、可视化或审核。

## 适用场景

- 明确调用 `$agency-chief-of-staff`。
- 要求“幕僚长 / Codex Agency / 完整团队”负责复杂任务闭环。
- 自然要求先把目标和边界聊清楚，再根据讨论创建执行清单。
- 要求开一个独立新对话执行、持续更新进度、归档任务或沉淀长期资产。
- 要求先研究，再规划、执行、验证和审核。
- 长任务需要 Goal、checkpoint 和停止条件。
- 需要并行探索、实现或独立 cold review。
- 需要 release readiness、Skill hardening、安全/高风险迁移或客户交付质量审核。
- 明确要求真实 Codex task/thread、隔离 worktree、thread id、receipt 或 cleanup 证明。

单句翻译、普通问答、简单代码修改、单文件明确修复，以及只出现 `thread` / `release readiness` 字样但没有工作意图的文本，不应隐式触发本 Skill。合法 Worker Packet 和本 Skill 自身源码维护也排除在外。

## 核心工作流

项目型请求使用四阶段生命周期：

```text
需求讨论
  → 持久化任务执行清单
  → 新执行对话中的角色化团队执行、事件进度与验证
  → 任务归档与长期知识沉淀
```

Discussion 可以合法停在讨论；Plan 初始只创建 `task-plan.json`、用户清单和项目 index，不预建 Team、Session、Progress 或 Evidence 占位文件；Execution 优先真实 Codex Task/Thread，Native 创建面不可用时生成可复制的手动启动提示词；准备阶段不认调用方 JSON，只有 `bind_execution_session.py` 从 App Server、canonical state 与 rollout 机械读回后才进入执行；`complete_task.py` 用可回滚事务把当前验收、验证、Review 与 cleanup 一次收口；Archive 再执行归档和可选知识沉淀。普通单次请求不创建 `.agency`，也不要求每次建 Thread。

关键设计：

- Direct Mode 主线程或项目 Execution Root 是 outcome owner，可以直接研究、编辑、测试、整合和交付。
- Team Planner 先判断委派的净执行价值，再根据 Work Item 生成岗位。单一研究、单一文档、普通单文件修改、单一内部架构判断和高耦合连续实现默认由 Root 完成；多个独立研究流仍可保留同 Profile 的多个实例。`solo` / `lean_team` / `project_team` / `program_team` 描述复杂度，不规定最低人数，团队规模是上限而不是目标。
- 按收益使用最少必要的 subagent：提供 `codebase-researcher`、`technical-architect`、`developer`、`writer`、`reviewer`、`test-debugger`、`supervisor` 七个窄职责 Profile，不恢复 v0.1 的固定 16 角色。同一 Profile 可以有多个不同 position instance，但必须对应不同 Work Item、范围与输出。
- 宿主只有在确实暴露按名称选择 custom-agent 且运行身份可读回时，才可按名称运行 profile；当前 resolver 不把自报 loaded 配置变成可执行派发。接口或机械 attestor 缺失时，五个只读 profile 可走 Codex CLI 兼容通道，developer/writer 写入仍由主线程或隔离 worktree 完成。
- 领域 Skill 可以显式绑定给专业 Agent；只禁止两个主控入口递归调用，不再一刀切禁止全部 `$slug`。
- Goal 只用于明确的长期目标，不为短任务生成 Goal Ledger。
- 项目执行阶段只准备 Team Plan 选中的项目级 Profile，不默认安装全部七个，不写用户全局 Agent 配置。
- 真实 task/thread 只在用户要求独立执行面时使用；普通任务不强制 Thread，工具不可用时不拿同线程或 subagent 冒充新对话。
- Execution Root 的默认模型请求独立为 GPT-5.6 Sol + `ultra`；它不进入 Subagent 的 Efficient/Balanced/Judgment 成本档。exact ID 必须来自 live catalog，spawn 后必须读回实际 provider/model/effort，禁止静默降级。
- 只有机器审计确实需要时才输出结构化 receipt。
- Assured 路径默认一次 cold review 加一次修复后的定向复核；普通低风险修改使用 Root 自检和相关测试，避免 review 成为固定执行税或无限 wave。
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

要求 Python 3.10+。需要生成 Git-bound profile、native-task 或 model-smoke 发布证据时，
还要求 Git 2.45+ 的全局 `--no-lazy-fetch`；较旧 Git 会明确失败，避免静默触发
partial-clone 的外部取回 helper。

如需历史 stable，可固定安装 `v0.1.7`：

```bash
git clone --depth 1 --branch v0.1.7 \
  https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf.git
cd zhijuan-codex-agency-chief-of-staf
python3 scripts/install_skill.py
```

如需已发布 prerelease，把 tag 改为 `v0.2.0-rc.3`。`v0.3.0-rc.4` 当前只存在于本地源码候选；仅在已审阅的源码 checkout 中开发或验证新增量时直接运行：

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

从准备交付的源码 checkout 独立读回安装态；只有 `status` 为
`already-installed`，且 canonical/legacy 两个 `states_before` 都为 `current`，
当前 checkout 的 Runtime 能力才可归属于本机已安装 Skill。输出同时包含两套
runtime 的逐文件 SHA-256 manifest，不能只看目录存在或 Skill 名称：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/install_skill.py --dry-run --json
```

Dry Run 不修改安装：缺失时返回 `would-install`，与源码不同且未传 `--force` 时返回 `would-replace`，两套都一致时返回 `already-installed`。先审阅差异，再显式执行
`--force`，随后重复上述 dry-run；已发布 tag 的安装仍以对应 tag 自带的 README
和 manifest 为准。

安装器只复制运行时 allowlist，并把两个 bundle 作为一个可回滚的 pair transaction 更新；不会把 GitHub workflow、历史 validation、README 或仓库管理文件打进运行时 Skill。

专业 Agent 模板随 runtime 分发，但不会默认写入任何项目或用户配置。项目生命周期阶段三默认依据 `TEAM_PLAN.json` 做 Selected-only 准备，并且只有显式 `--apply` 才写当前项目：

```bash
python3 scripts/prepare_team_runtime.py \
  --project /absolute/project \
  --team-plan /absolute/project/.agency/tasks/active/<task-id>/TEAM_PLAN.json \
  --apply
```

以下全量安装命令只保留给维护、兼容或用户明确要求全部 Profile 的场景：

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

当 resolver 已在同一次调用中完成 live catalog/state 比对并输出 direct route JSON 时，可把其中选中的 exact OpenAI model/reasoning 写入对应项目 profile：

```bash
python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents \
  --route-plan /absolute/path/live-route-plan.json
```

源模板始终不固定模型。installer 只接受 `schema_version=2`、`route_mode=direct`、claims 与 dispatch contract 逐字段一致的 OpenAI plan，但序列化 JSON 的 live 来源仍是调用方声明；它只验证结构并绑定文件 hash，不会独立重跑 App Server/state attestation。因此安装回执明确写 `route_plan_attestation: caller-asserted-unverified` 和 `route_state: configured-unverified`；安全路径是同一流程先运行上面的 `--verify-live-catalog` resolver，再立即安装，随后在真实 spawn 后读回 child model/effort。该脚本只管理七个同名 TOML，保留目标目录中的其他文件；冲突时 fail closed，显式 `--force` 才替换。它拒绝外部 provider、claims/contract 不一致、symlink/hardlink plan，以及把 canonical/legacy 主控 Skill 绑定回子 Agent。

## Codex CLI 兼容执行面

如果当前 Codex 的 native subagent schema 不能按 `reviewer` 等名称选择 profile，可使用随 runtime 安装的只读兼容 runner。模型必须先来自当前 Codex catalog，不能凭文档猜 ID：

```bash
python3 scripts/run_profile_compat.py \
  --profile reviewer \
  --packet /absolute/path/reviewer.packet.txt \
  --cwd /absolute/project \
  --model <exact-current-openai-model> \
  --reasoning-effort <effort> \
  --required-read /absolute/project/current-artifact \
  --required-read-marker '<hidden current fact>' \
  --required-final-marker '<same current fact>'
```

Packet 可从 [`examples/cli-profile-review.packet.txt`](examples/cli-profile-review.packet.txt) 复制后按当前 artifact 收窄；不要把预期 verdict 或隐藏 readback marker 写进 packet。

该通道支持 `codebase-researcher`、`technical-architect`、`reviewer`、`test-debugger`、`supervisor` 五个 `read-only` profile。它创建独立持久化 `codex exec` 会话，以参数数组和最小非敏感进程环境执行，显式禁用递归 subagent，设置有界超时，并核验 OpenAI provider/model/reasoning、结构化只读策略、直接 artifact read、严格终态、`AGENTS.md` 不变与 archive。收据固定写 `execution_mode: cli-profile-compat`、`native_custom_agent_selected: false`，不会把普通会话冒充成原生 `agent_role=reviewer`。`developer` 与 `writer` 写任务仍走主线程或隔离 worktree。

## 使用

最短调用：

```text
使用 $agency-chief-of-staff 把这个任务做到可验证完成。
```

需求讨论：

```text
这件事比较复杂，先跟我把目标和边界聊清楚，暂时不要执行。
```

创建执行清单：

```text
根据以上讨论，创建任务执行清单；先不要开始执行。
```

启动独立执行对话：

```text
创建新对话，使用 gpt-5.6 sol ultra 根据任务执行清单执行任务，并持续更新进度。
```

归档与沉淀：

```text
归档这个任务，并把已验证、可复用的信息最小写入已有文档；没有匹配文档时再创建知识文档。
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

Execution Root 与 Subagent 分开路由。Root 读取 `assets/execution-model-policy.json`，默认请求 GPT-5.6 Sol + `ultra`，使用 `scripts/resolve_execution_model.py` 从当前 App Server catalog 解析 exact ID；目录缺少 provider 时，Runtime 显式把宿主提供的 `CODEX_THREAD_ID` 作为 `--thread-id` 传入，helper 再从同一 App Server canonical state 读回这个被选择 Root 的 provider。该 selector 不独立证明“当前前台 Task”，最终以新执行 Task 的 binder readback 为准；selector 缺失或状态读回失败仍 fail closed，不从模型名猜 provider。若 Sol 不存在、Ultra 不受支持或 spawn readback 不一致，就要求用户选择或 FAIL，不静默降级。`prepare_execution_launch.py` 只产生 ready packet；宿主创建后由 `bind_execution_session.py` 内部核对真实 Task ID、Root/packet、provider、model、effort、CWD/worktree、canonical state 和 rollout turn，再事务性进入 `executing`。

七个窄 Subagent Profile 继续使用 `efficient`、`balanced`、`judgment` 能力档和三种预算模式；它们不要求全部使用 Ultra。仓库不维护会过期的模型排行榜或角色硬编码 model slug。

先读取当前 Codex App Server catalog，并从该 App Server 的规范状态库读回调用方指定线程的 root provider；调用方再显式绑定当前可见模型：

```bash
python3 scripts/inspect_codex_models.py \
  --codex-bin /absolute/path/to/codex \
  --state-db ~/.codex/state_5.sqlite \
  --thread-id <root-thread-id> \
  --class-binding efficient=<exact-visible-model-id> \
  --class-binding balanced=<exact-visible-model-id> \
  --class-binding judgment=<exact-visible-model-id> \
  > /absolute/path/current-catalog.json
```

```bash
python3 scripts/resolve_role_route.py \
  --roles codebase-researcher,reviewer \
  --risk medium \
  --budget balanced \
  --route-mode direct \
  --root-provider openai \
  --catalog /absolute/path/current-catalog.json \
  --verify-live-catalog \
  --codex-bin /absolute/path/to/codex \
  --state-db ~/.codex/state_5.sqlite \
  --thread-id <root-thread-id> \
  --cwd "$PWD" \
  --json \
  > /absolute/path/live-route-plan.json
```

只有同一次 resolver 调用用 `--verify-live-catalog` 从 App Server 与规范 state DB 重建并逐字比对 catalog，才会生成 direct dispatch contract；否则只是 `planned-unverified`。该 plan 可通过显式 `install_agent_profiles.py --route-plan ...` 生成项目级 exact-model custom-agent overlay；installer 只对序列化 plan 做 schema/claims/contract/hash 验证，不会独立证明其 live 来源，所以固定回执为 `caller-asserted-unverified` / `configured-unverified`，不是 spawn receipt。规范 state 读取使用 WAL 可见的只读事务，并对数据库及活动 sidecar 的文件身份做前后校验，避免 immutable `/dev/fd` 漏读新状态。`planned` 仍只代表路由计划；工具接受后才是 `accepted`。`verify_role_route_receipt.py --require-native-spawn-call` 可把父 rollout 中唯一的原生调用参数、call/output、started activity 与指定 child edge/state/rollout 绑定；receipt 仍是本机时点一致性证据，还要由宿主可见 readback 把指定 parent 绑定为当前 task，才能对外表达为 `confirmed`。若 App Server 模型项没有 provider 字段，model provider 仅记为 `root-state-inferred`，不是独立目录证明。自报 loaded 的 custom-agent catalog不会生成可执行 contract；named profile selection 或运行身份不能机械读回时，回退到上述 Codex CLI 会话或留在主线程。相对成本单位只比较方案，不等于 token、货币或节省百分比。Claude/Fable 是默认关闭、非核心依赖的可选 advisor 适配位；不存在时不探测、不调用、不阻塞 Codex-only 工作流。

`scripts/configure_native_routing.py` 可检查宿主是否支持 `agents` namespace 的可见 metadata；默认 status/dry-run 不创建 `CODEX_HOME`、不写配置。写入前会用隔离 `CODEX_HOME` 和无凭据环境启动每个客户端，以 CLI override 注入四个探针值，再用 App Server `config/read` 精确核对生效语义；只看进程退出码不算兼容。扫描范围包括目标客户端、PATH 每个可执行 `codex`、已发现的系统级/用户级 macOS Desktop 内嵌 CLI 和所有显式 `--compat-bin`；若空 PATH 段会隐式命中当前目录的可执行 `./codex`，则因客户端身份有歧义而失败。任一共享配置客户端不兼容时默认失败；风险覆盖必须由用户单独明确同意。四个受管字段中任何与目标不同的既有用户值都要求同一显式替换授权，即使文本带有本 Skill 的 marker 也不会在缺失恢复 journal 时推定归属。disable/recover 若由旧客户端发起，会改用已探测兼容客户端读取并恢复同一配置；没有兼容客户端时失败，不做自写 TOML 紧急绕过。只有显式 `--apply` 才在目标 `CODEX_HOME/config.toml` 的 user layer 管理四个路由字段，并在同目录维护私有恢复 journal；若旧配置把 `multi_agent_v2` 写成布尔值，启用期间会暂时迁移为 table，同时精确保留 `enabled`，停用时恢复原 scalar。读写操作在 App Server 初始化前锁定该 `CODEX_HOME` 目录 inode，写后双读回。异常 journal 需先检查 `--recover`，再显式执行 `--recover --apply`。它不选择模型，也不启用外部 provider。

相关官方说明：

- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents)
- [Why subagent workflows help](https://learn.chatgpt.com/docs/agent-configuration/subagents#why-subagent-workflows-help)
- [Long-running work](https://learn.chatgpt.com/docs/long-running-work)
- [Latest model guidance](https://developers.openai.com/api/docs/guides/latest-model)

## 验证层级

验证名称必须诚实区分：

1. `package/contract`：离线检查 frontmatter、四阶段 schema、Team Planner、Execution Session、进度/归档/知识、runtime manifest、七个 Agent TOML、项目/模板 parity、领域 Skill 绑定、行为 case 和安装事务；不声称证明模型行为。
2. `model-smoke`：在无本项目 routing、禁用 plugins/apps、最小环境变量的临时仓库里真实调用当前 Codex 模型，检查真实文件、状态、Agent/Thread event、model readback、progress、archive 和 knowledge patch；子集运行只会得到 `passed_partial`。只有实际执行并保存 receipt 后才可标 PASS，离线 case schema 通过不算模型行为证明。
3. `profile-compat-smoke`：当前 named custom-agent 接口不可用时，从已安装 canonical bundle 发起独立只读 CLI profile 会话，核验 state DB/rollout、直接 artifact read、严格 reviewer schema、AGENTS 不变和 cleanup。
4. `native-task-smoke`：当前接口支持按名称选择并能读回角色时，从已安装 canonical bundle 发起真实 Codex Desktop task，核验 provider/model/effort、reviewer 绑定、安装 manifest 和 cleanup。
5. `threadops-smoke`：只有发布目标明确要求真实 task/thread 证明时，使用 Codex Desktop 工具核验真实 id、readback、worktree 和 cleanup。

运行离线质量门：

```bash
bash scripts/quality_gate.sh .
```

需要生成可移植的无人值守、跨宿主或 stable 发布证据时，先使用专用、低权限的 eval 凭据。被测 Skill 与 case 和 Codex 进程同属当前 OS 用户，临时 `auth.json` 理论上可被恶意被测内容读取；环境变量最小化和输出脱敏不是安全边界。对不可信 PR，必须放进一次性 OS 用户或容器，不能使用主账号凭据。

```bash
export CODEX_EVAL_AUTH_JSON=/path/to/dedicated-eval-auth.json
export CODEX_EVAL_CODEX=/absolute/path/to/codex
export CODEX_EVAL_MODEL='<exact-current-openai-judgment-model>'
export CODEX_EVAL_REASONING_EFFORT='<supported-effort>'
export CODEX_EVAL_CATALOG=/absolute/path/current-catalog.json
export CODEX_EVAL_STATE_DB="$HOME/.codex/state_5.sqlite"
export CODEX_EVAL_THREAD_ID='<requested-root-task-id>'
export CODEX_EVAL_CATALOG_CWD="$PWD"
export CODEX_EVAL_AUTH_CLASS=dedicated
```

运行全量真实模型前测：

```bash
python3 -I -S scripts/run_model_evals.py \
  --root . \
  --out validation/current/model-smoke-$(date +%Y%m%d-%H%M%S) \
  --codex-executable "$CODEX_EVAL_CODEX" \
  --model "$CODEX_EVAL_MODEL" \
  --reasoning-effort "$CODEX_EVAL_REASONING_EFFORT" \
  --catalog "$CODEX_EVAL_CATALOG" \
  --catalog-state-db "$CODEX_EVAL_STATE_DB" \
  --catalog-thread-id "$CODEX_EVAL_THREAD_ID" \
  --catalog-cwd "$CODEX_EVAL_CATALOG_CWD" \
  --auth-json "$CODEX_EVAL_AUTH_JSON" \
  --auth-credential-class "$CODEX_EVAL_AUTH_CLASS" \
  --acknowledge-auth-readable-to-eval-process
```

`make model-smoke` 使用同一组变量，并在缺少任一发布身份输入时先失败；它不再内置特定模型或 reasoning effort。catalog 来自非默认 Codex home 时，再设置 `CODEX_HOME`，Make target 会安全透传 `--catalog-codex-home`。

Runner 必须以 `python3 -I -S` 启动；在导入仓库内模块前，它会把完整 `scripts/` 树的路径、类型、目录和 blob 哈希与干净 `HEAD` 比对，因此 ignored import-shadow、bytecode、扩展模块或额外 package 不能先读取 auth 参数。硬化 Git 读回显式禁用 replacement objects、拒绝任何非 `H` 索引标记，并把所有评测运行时文件逐个绑定到真实、未替换的 `HEAD` blob；replacement refs、`assume-unchanged`、`skip-worktree` 或额外 commit 都不能把越界字节藏在普通 `git status` 后面。Runner 只允许 `read-only` / `workspace-write`，拒绝危险 sandbox、越界 case id/artifact 路径、既有输出目录和 symlink，并给 Codex 进程及其工具 shell 固定系统 `PATH`。每个 case 在独立进程组运行；正常退出、超时或异常后会终止仍留在原进程组的进程，再回收临时 auth。同 OS 用户的子进程若自行建立新 session，就已逃出该进程组边界；不可信评测仍必须放在一次性 OS 用户或容器。全部 case 复用冻结的 runtime snapshot，收据绑定 Skill manifest、case 文件、runner hash、严格 JSONL thread/turn 终态、root session 的 OpenAI provider/model/effort/completion，以及 root 发起的 UUID reviewer spawn/wait 与 child OpenAI completion journal；同时检测运行中源码漂移。每个 fixture 还冻结 HEAD 与排除 `.git` 的真实文件 manifest。非 Git checkout、旧 Git 不支持安全开关、source dirty 或读回失败都不能获得 release eligibility。host-default 的模型名若只能从诊断日志推断，不会被视为稳定的 release model identity；可移植 prerelease evidence 要求 runner 在启动前重新验证 catalog、当前 task 的规范状态读回与显式 OpenAI `judgment` 模型/effort，然后在同一 root session 再匹配身份三元组并使用专用凭据。只做 catalog schema 校验不会获得 release eligibility；stable eligibility 还要求没有未测能力。

`--auth-credential-class primary` 只允许生成诊断收据，永远不具备 portable prerelease/stable eligibility；不得把主账号凭据复制成所谓 dedicated 凭据。

当前 Codex Desktop 真正读回任务与 reviewer 证据时可使用 native-task receipt。它绑定收据生成时的 source HEAD 与干净状态、已安装双 bundle、state DB provider/model/effort、持久化 rollout、唯一完成事件、独立 reviewer 与 cleanup，因此可以支持明确标为“当前 Codex Desktop 用户路径已验证”的 host-scoped RC。它不证明历史零越界写入、历史 `AGENTS.md` 状态、凭据隔离、无人值守、跨宿主或 stable 发布：

```bash
python3 scripts/verify_native_task_receipt.py \
  --state-db ~/.codex/state_5.sqlite \
  --codex-home ~/.codex \
  --source-root . \
  --installed-root ~/.agents/skills \
  --parent-id <thread-id> \
  --reviewer-id <reviewer-thread-id> \
  --model <exact-current-openai-model> \
  --reasoning-effort <supported-effort> \
  --parent-final-marker '<expected parent completion marker>' \
  --reviewer-final-marker 'REVIEW_VERDICT: PASS' \
  --reviewer-read-marker '<exact artifact fact read by reviewer>' \
  --reviewer-artifact '<absolute regular-file path read by reviewer>' \
  --require-archived \
  --require-clean-source
```

host-scoped RC 的 release notes 必须列出未验证边界。宣称无人值守、跨宿主或 stable 公共发布时，仍必须使用专用低权限凭据的隔离 CLI model-smoke。

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
  user-experience.md
  model-routing-and-budget.md
  task-lifecycle.md
  team-orchestration.md
  execution-session.md
  knowledge-archiving.md
assets/
  WORK_RECEIPT_TEMPLATE.yaml
  DELIVERY_EVIDENCE_TEMPLATE.yaml
  agent-routing.json
  role-model-policy.json
  task-state.schema.json
  task-execution-plan.schema.json
  team-plan.schema.json
  progress-event.schema.json
  knowledge-deposit.schema.json
  execution-session.schema.json
  execution-model-policy.json
  lifecycle-intents.json
  visualizations/*
  codex_agents/*.toml
scripts/
  audit_historical_threads.py
  install_agent_profiles.py
  inspect_codex_models.py
  configure_native_routing.py
  resolve_role_route.py
  agency_task.py
  resolve_team_plan.py
  prepare_team_runtime.py
  agency_doctor.py
  prepare_execution_launch.py
  bind_execution_session.py
  resolve_execution_model.py
  update_task_progress.py
  complete_task.py
  archive_task.py
  deposit_knowledge.py
  validate_task_archive.py
  verify_role_route_receipt.py
  run_profile_compat.py
  render_visualization.py
  validate_agent_profiles.py
```

兼容说明：slug 中的 `staf` 保留原包名，避免破坏现有显式调用。
