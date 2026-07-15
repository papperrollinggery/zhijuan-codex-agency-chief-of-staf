# 角色模型路由与成本治理

只在任务需要专业 Agent、用户要求控制模型/成本，或当前宿主暴露精确子模型路由时读取本文件。角色职责和 sandbox 仍由 `assets/codex_agents/` 定义；模型决策由 `assets/role-model-policy.json` 定义，二者不得互相覆盖。

## 决策顺序

1. 先判断是否值得委派。紧耦合、上下文很大或主线程能一次完成的工作留在主线程。
2. 选择完成任务所需的最少角色，再选择 `economy`、`balanced` 或 `quality` 预算。
3. 按角色和风险得到 `efficient`、`balanced` 或 `judgment` 模型能力档及 reasoning。
4. 从当前宿主 catalog、宿主机械读回的已加载 custom agent，或用户确认的 exact ID 解析具体模型。不得把 catalog 自报字段当作加载证明，不得维护静态模型排行榜，也不得猜 model ID。
5. 只有当前派发 schema 接受精确控制时才传 model/reasoning；任何 override 都使用 `fork_turns="none"` 和自包含 packet。
6. 派发后分别记录已安排、已接受和运行身份已确认。配置存在、工具接受和实际运行不是同一件事。

## 角色默认值

| 角色 | 默认能力档 | 高风险能力档 | 默认用途 |
|---|---|---|---|
| codebase-researcher | efficient | balanced | 有界代码地图、复现和证据收集 |
| technical-architect | judgment | judgment | 接口、迁移和不可逆边界 |
| developer | balanced | judgment | 有界实现与集成 |
| writer | balanced | judgment | 用户文档、release notes、报告和交付文字 |
| reviewer | judgment | judgment | 独立审核、安全和发布判断 |
| test-debugger | efficient | balanced | 测试、日志和根因分类 |
| supervisor | judgment | judgment | Goal 覆盖、证据缺口和发布边界只读审计 |

`developer` 是代码 executor。`supervisor` 不协调其他 Agent、不批准最终交付，也不取代 root outcome owner。

当预算允许自动升级时，`high` 与 `critical` 都升级到角色的高风险模型能力档；只有 `critical` 再把 reasoning 从该能力档的默认值升到 elevated 值。`economy` 的自动升级额度为 0，因此即使风险为 `high` 或 `critical`，也保留角色默认模型能力档与默认 reasoning；若该强度不足，工作回到主线程或改用更高预算。高风险包括安全、发布、迁移、不可逆操作、跨系统兼容、证据冲突，或一次有界尝试后仍存在多个竞争根因。每个角色最多自动升级一次；不要让低成本角色反复失败后持续重试。

## 预算模式

- `economy`：最多委派 1 个角色、并行 1 个、不自动升级。优先把工作留给主线程，只保留真正需要的独立研究或审核。
- `balanced`：最多委派 3 个角色、每一波最多并行 3 个、每个角色最多升级一次。默认选择。
- `quality`：最多委派 5 个角色、每一波最多并行 3 个、允许高风险角色使用更强能力档。

“最多委派”限制整个计划中的角色总数；“并行”只限制同一执行波次。路由脚本会输出波次，但它只是成本与顺序计划，不是调度器，也不代表宿主已经接受任何派发。

成本单位是模型能力档的相对权重，只用于比较计划，不代表 token、货币、credits 或节省百分比。实际用量只能来自宿主或 provider 的计量。预算不能跳过必需 cold review、测试、安全门禁或验证；超预算工作必须明确回到主线程，不能静默删除。

运行 `python3 scripts/resolve_role_route.py --roles <逗号分隔角色> --risk <low|medium|high|critical> --budget <economy|balanced|quality>` 可得到确定性计划。默认输出人话；机器证据需要时才加 `--json`。

## 精确模型解析

精确路由先从当前 Codex App Server 读取目录，并从该 App Server 返回的 `codexHome/state_5.sqlite` 读回调用方明确指定线程的 root provider。这个绑定证明“规范状态库中该线程的 provider”和“同一 App Server 暴露的模型目录”在本机一致，不会自动证明该线程就是当前前台 task。调用方根据目录描述、reasoning 支持与任务风险，显式把每个需要的能力档绑定到 exact model；脚本不维护静态模型排行榜，也不猜能力档：

```bash
python3 scripts/inspect_codex_models.py \
  --codex-bin /absolute/path/to/active/codex \
  --state-db ~/.codex/state_5.sqlite \
  --thread-id <current-root-thread-id> \
  --class-binding efficient=<exact-visible-model-id> \
  --class-binding balanced=<exact-visible-model-id> \
  --class-binding judgment=<exact-visible-model-id> \
  > /tmp/current-codex-catalog.json

python3 scripts/resolve_role_route.py \
  --roles codebase-researcher,developer,reviewer \
  --risk high \
  --budget quality \
  --route-mode direct \
  --root-provider openai \
  --catalog /tmp/current-codex-catalog.json \
  --verify-live-catalog \
  --codex-bin /absolute/path/to/active/codex \
  --state-db ~/.codex/state_5.sqlite \
  --thread-id <current-root-thread-id> \
  --cwd "$PWD" \
  --json \
  > /tmp/live-route-plan.json

python3 scripts/install_agent_profiles.py \
  --target-root /absolute/project/.codex/agents \
  --route-plan /tmp/live-route-plan.json \
  --json
```

目录适配器只接受当前目录中可见、reasoning 兼容的 exact ID；核心路径固定要求 OpenAI provider 并拒绝 Claude。App Server 若为模型返回 provider 字段，证据记为 `catalog-advertised`；若当前目录缺少该字段，只能将规范状态库中的 root provider 记为 `root-state-inferred`，不得把它说成每个模型的独立 provider 证明。规范 state DB 通过 WAL 可见的只读事务读取，并对数据库及活动 WAL/SHM 的文件身份做前后校验；这防止常见替换竞态和 stale-WAL 读回，但不是对同一 OS 用户任意恶意代码的安全隔离。`--root-provider` 单独提供时不会被当作机械读回；即使用户同时明确 `--confirm-root-provider`，也只得到人工确认的 `planned-unverified` 候选。只有 CLI 在同一次调用中用 `--verify-live-catalog` 重建并逐字比对 catalog，才会输出可执行的 direct dispatch contract；不带 live 验证的 catalog 只能得到 `planned-unverified`，不能派发。即使得到 `planned`，也仍不等于工具接受或子任务实际运行。

可执行派发工具必须暴露 `agents` namespace，并接受 direct route 的 `model`、`reasoning_effort`、`fork_turns`，或能按名称选择项目 custom agent。当前 resolver 只为 live-verified direct route 输出 dispatch contract；`install_agent_profiles.py --route-plan` 可以把该 contract 的 exact OpenAI model/reasoning 固化到选中的项目 agent 文件，使 named-agent spawn 不再只能继承根模型。installer 逐字段验证序列化 plan 的 claims、role、provider、model、reasoning、`fork_turns=none` 和 dispatch contract，并绑定 SHA-256，但不会重新连接 App Server/state 证明 JSON 的 live 来源；因此安装回执明确写 `route_plan_attestation: caller-asserted-unverified` 和 `route_state: configured-unverified`，未选中角色继续继承。安全用法是 live resolver 成功后立即安装，再用真实 spawn/readback 验收。`custom-agent` resolver 模式仍只校验候选与角色一致性。先只读检查：

```bash
python3 scripts/configure_native_routing.py \
  --status \
  --codex-bin /absolute/path/to/active/codex \
  --json
```

配置未启用时，可先运行无 `--apply` 的 dry-run；只有用户明确同意修改个人 Codex 配置后才追加 `--apply`。脚本会隔离探测目标客户端、PATH 每个可执行 `codex`、已发现的系统级/用户级 macOS Desktop 内嵌 CLI，以及每个显式 `--compat-bin`；任一共享配置客户端不接受完整四字段 preset 时都在写入前失败。四个受管字段中的任一既有用户值与目标值不同时，也必须先明确 `--replace-existing-policy`；`--allow-incompatible-client` 只有用户单独接受该客户端可能无法启动时才能使用。status 与 `--require-effective` 仍会如实报告不兼容；disable/recover 不受不兼容门禁阻塞，并会在请求客户端不兼容时选择已探测兼容客户端恢复同一用户配置，没有兼容客户端则失败，不绕过 App Server 自写 TOML。脚本只管理并可恢复四个 `multi_agent_v2` 字段：先持久化 pending journal，再写配置并要求 user/effective 双读回。中断或回滚异常会保留 `recovery-needed` journal，先 dry-run 检查 `--recover`，再经明确授权执行 `--recover --apply`。成功后需新建 task；安装 Skill 本身不会自动修改配置。

派发完成后用 `scripts/verify_role_route_receipt.py` 从规范 state DB 绑定 parent edge、child state、session metadata，以及与唯一 completion 相同 `turn_id` 的 turn context。需要证明 direct override 的原始调用参数时追加 `--require-native-spawn-call`；verifier 会再绑定父 rollout 中唯一的 `agents.spawn_agent` call/output、call ID、`model`、`reasoning_effort` 与 `fork_turns=none`，任何缺失、重复或漂移都失败。该 receipt 的状态仍是 `locally-consistent`：它证明指定 parent/child、父调用参数和 child 实际 provider/model/effort 在本机持久化证据中一致，但 `current_task_binding_verified: false` 时还必须由宿主可见的当前 parent/task readback 补齐，才可对用户表达为 `confirmed`。未要求父调用绑定时 `native_spawn_call_arguments_verified` 保持 `false`，不能反推调用参数。

catalog 缺失、provider 不明、模型不可用或 schema 不支持时，回退顺序为：宿主已经机械读回的 named custom agent → 当前 schema 的 direct route → 随包只读 CLI fallback → 主线程或隔离 worktree。当前 resolver 没有 loaded-agent 机械 attestor，因此 `custom-agent` catalog 只生成不可执行的 `planned-unverified` 候选；不能把自报的 `loaded=true` 当成派发授权。

回退不得谎称目标模型已经使用。子 Agent 自述模型名不能证明运行身份。

## 用户界面

默认只告诉用户：采用节省/平衡/质量优先配置、安排了哪些工作、哪些工作留在主线程，以及路由是否真正核对。不要展示 model/provider/reasoning 参数、JSON、相对成本单位或 receipt；用户明确要求技术证据时再展开。

后台状态对应的前台表达：

- `planned`：已规划。
- `planned-unverified`：已得到精确候选，但 catalog 来源尚未机械确认。
- `accepted`：已成功安排。
- `confirmed`：规范状态库和 rollout 已核对实际运行身份，且宿主可见 readback 已把指定 parent 绑定为当前任务。
- `inherited-unverified`：已安排，但宿主未提供运行身份读回。
- `unavailable`：精确路由不可用，已回到现有执行方式。

## 外部顾问扩展位

保留 Codex host-scoped、root-facing、read-only 的 `external_advisor` 作为可选扩展位。默认 `none`、默认关闭且不是核心依赖；本包不安装、不探测也不调用 Claude/Fable。未来 `claude-fable-mcp` adapter 只能在用户已安装并明确启用时读取自包含计划包并返回建议；不得编辑、派发、接触 executor 或批准最终交付。适配器缺失时继续 Codex-only 流程，只有用户明确把它设为必需时才阻塞。
