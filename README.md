# Agency Chief of Staff for Codex

[![CI](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/actions/workflows/ci.yml/badge.svg)](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个结果负责型 Codex 多 Agent 编排 Skill：把复杂任务从目标澄清推进到研究、规划、执行、验证、独立审核和最终交付。它面向 Codex Desktop、Codex CLI、原生 subagents、Goal、隔离 worktree、动态角色模型路由和可验证发布流程。

它不靠堆角色或 receipt 证明自己工作；安装器和默认运行不会向用户配置、仓库主工作区或项目根 `AGENTS.md` 注入路由。主线程对结果负责；原生 subagents、Goal、真实 task/thread/worktree 都按任务需要使用。

## 用户看到的交互

聊天是产品前台，技术证据留在后台。Skill 默认用四种状态与用户沟通：任务接管、阶段进展、单一选择、最终交付。内部模式、角色、线程、哈希、JSON/YAML、命令回值和调试字段不会作为主要界面出现。

当文字不足以快速解释三个以上步骤、分支、依赖或对比项时，Skill 选择最小的 OpenAI visualization：阶段路径、方案对比、影响关系、验证清单、当前图片/页面审阅，或基于真实数值的趋势图。每个内建视图先经过数据门；文本按字段限制长度，NUL、C1 和非展示空白的 C0 控制字符 fail closed，展示字段中的换行与制表符压成单个空格。曲线必须含有限数值、单位、维度、来源、文字结论和缺失值说明；图片还要通过 64 MiB 上限、no-follow、单硬链接、路径身份、签名和 SHA-256 核验，renderer 再读回后把精确字节事务化复制为 verified image，fallback 不引用可变原路径。renderer 为六种内建 surface 全部生成确定性的同源 fallback 与 hash manifest，`task-stage` 与 `decision` 另生成宿主主题感知的纯 fragment；标题、goal 与 summary 留在 directive 外，fragment 只承载必要视觉和交互。输入通过 no-follow 文件描述符读取并拒绝 hardlink，输出目录以 dev/inode 固定并在 prepare、commit、返回前持续核对路径。输出先在同目录安全临时文件完成 flush/fsync，再以目录项替换提交，覆盖不会跟随已有 symlink/hardlink，异常会尽力恢复旧输出集；成功返回前还会从固定 dirfd 复核 no-follow identity/hash。decision 回传同时发送稳定 `choice_id` 与所选展示值；固定 prompt 把后者封装为不可信且不可执行的 JSON 数据，并将 `<`、`>`、U+2028、U+2029 转成 Unicode 转义，使下一轮能还原选择但展示值不能闭合数据分隔符或变成指令。动态解释、模拟、可调输入、地图、空间运动和复杂图表在宿主提供 `@visualize` 时遵循其当前安装版规范，本仓库 registry 不限制插件能力；否则使用 renderer 生成的可验证文字、表格、Mermaid 或图片审阅降级。只有宿主自己返回并绑定当前 thread、匹配 manifest 的 surface/file/hash、非空 mount id 且 `rendered=true`，才会说用户已看到视图。

## 一览

| 项目 | 当前事实（2026-07-15） |
| --- | --- |
| Canonical Skill | `$agency-chief-of-staff` |
| 兼容入口 | `$zhijuan-codex-agency-chief-of-staf`，仅显式调用 |
| 核心模型提供方 | OpenAI / Codex；Claude/Fable 仅为默认关闭的可选 advisor 位 |
| Python | 3.10+ |
| 最新 stable tag | [`v0.1.7`](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases/tag/v0.1.7) |
| 最新 prerelease tag | [`v0.2.0-rc.3`](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases/tag/v0.2.0-rc.3) |
| 当前 checkout | `v0.2.0-rc.3` release source |

入口：[文档索引](docs/README.md) · [LLM 索引](llms.txt) · [发现性与发布元数据](docs/REPOSITORY_DISCOVERY.md) · [Changelog](CHANGELOG.md) · [示例](examples) · [贡献](CONTRIBUTING.md) · [安全策略](SECURITY.md) · [行为规范](CODE_OF_CONDUCT.md) · [全部 Releases](https://github.com/papperrollinggery/zhijuan-codex-agency-chief-of-staf/releases)

本 README 正文描述 `v0.2.0-rc.3` release source。已发布 tag 保留各自当时的 README 和能力，不会因为主分支文档更新而获得后续功能：

| 版本线 | 能力边界 |
| --- | --- |
| `v0.1.7` stable | 历史稳定线；不包含本文的七角色、live catalog adapter、native routing configurator 或 fragment renderer |
| `v0.2.0-rc.2` prerelease | 包含五角色 RC、旧 visualization/data contract 与 native-task receipt |
| `v0.2.0-rc.3` prerelease | 七角色、current-catalog direct 路由/readback、可恢复 native routing 配置和 fragment/fallback/manifest 流程；named profile 与 host mount 仍按宿主能力 fail closed |

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
- 按收益使用最少必要的 subagent：提供 `codebase-researcher`、`technical-architect`、`developer`、`writer`、`reviewer`、`test-debugger`、`supervisor` 七个窄职责 profile，不恢复固定组织。
- 宿主只有在确实暴露按名称选择 custom-agent 且运行身份可读回时，才可按名称运行 profile；当前 resolver 不把自报 loaded 配置变成可执行派发。接口或机械 attestor 缺失时，五个只读 profile 可走 Codex CLI 兼容通道，developer/writer 写入仍由主线程或隔离 worktree 完成。
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

如需已发布 prerelease，把 tag 改为 `v0.2.0-rc.3`。仅在已审阅的源码 checkout 中开发或验证新增量时直接运行：

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
当前 README 的 `v0.2.0-rc.3` 能力才可归属于本机已安装 Skill。输出同时包含两套
runtime 的逐文件 SHA-256 manifest，不能只看目录存在或 Skill 名称：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/install_skill.py --dry-run --json
```

若结果是 `different`、`missing` 或其他状态，先审阅差异，再显式执行
`--force`，随后重复上述 dry-run；已发布 tag 的安装仍以对应 tag 自带的 README
和 manifest 为准。

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

长期目标：

```text
使用 $agency-chief-of-staff。为这个迁移设定 Goal，先研究现状，再规划、执行、验证和独立审核，直到满足停止条件。
```

真实线程：

```text
使用 $agency-chief-of-staff。创建真实隔离 worktree task 完成实现，返回真实 id、产物、验证、adoption 和 cleanup；工具不可用时明确 TOOL_BLOCKED。
```

## 当前模型能力的使用方式

Skill 为七个窄角色配置 `efficient`、`balanced`、`judgment` 能力档和三种预算模式，并在运行时从当前宿主 catalog 解析 exact model；仓库不维护会过期的模型排行榜或角色硬编码 model slug。

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

1. `package/contract`：离线检查 frontmatter、runtime manifest、七个 Agent TOML、项目/模板 parity、领域 Skill 绑定、场景 schema 和安装行为；不声称证明模型行为。
2. `model-smoke`：在无本项目 routing、禁用 plugins/apps、最小环境变量的临时仓库里真实调用当前 Codex 模型，保存 event JSONL 和最终输出；子集运行只会得到 `passed_partial`。
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
assets/
  WORK_RECEIPT_TEMPLATE.yaml
  DELIVERY_EVIDENCE_TEMPLATE.yaml
  agent-routing.json
  role-model-policy.json
  visualizations/*
  codex_agents/*.toml
scripts/
  audit_historical_threads.py
  install_agent_profiles.py
  inspect_codex_models.py
  configure_native_routing.py
  resolve_role_route.py
  verify_role_route_receipt.py
  run_profile_compat.py
  render_visualization.py
  validate_agent_profiles.py
```

兼容说明：slug 中的 `staf` 保留原包名，避免破坏现有显式调用。
