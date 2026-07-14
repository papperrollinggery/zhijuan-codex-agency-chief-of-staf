# 角色模型路由与成本治理

只在任务需要专业 Agent、用户要求控制模型/成本，或当前宿主暴露精确子模型路由时读取本文件。角色职责和 sandbox 仍由 `assets/codex_agents/` 定义；模型决策由 `assets/role-model-policy.json` 定义，二者不得互相覆盖。

## 决策顺序

1. 先判断是否值得委派。紧耦合、上下文很大或主线程能一次完成的工作留在主线程。
2. 选择完成任务所需的最少角色，再选择 `economy`、`balanced` 或 `quality` 预算。
3. 按角色和风险得到 `efficient`、`balanced` 或 `judgment` 模型能力档及 reasoning。
4. 从当前宿主 catalog、已加载 custom agent 或用户确认的 exact ID 解析具体模型。不得维护静态模型排行榜，也不得猜 model ID。
5. 只有当前派发 schema 接受精确控制时才传 model/reasoning；任何 override 都使用 `fork_turns="none"` 和自包含 packet。
6. 派发后分别记录已安排、已接受和运行身份已确认。配置存在、工具接受和实际运行不是同一件事。

## 角色默认值

| 角色 | 默认能力档 | 高风险能力档 | 默认用途 |
|---|---|---|---|
| codebase-researcher | efficient | balanced | 有界代码地图、复现和证据收集 |
| technical-architect | judgment | judgment + elevated reasoning | 接口、迁移和不可逆边界 |
| developer | balanced | judgment | 有界实现与集成 |
| reviewer | judgment | judgment + elevated reasoning | 独立审核、安全和发布判断 |
| test-debugger | efficient | balanced | 测试、日志和根因分类 |

高风险包括安全、发布、迁移、不可逆操作、跨系统兼容、证据冲突，或一次有界尝试后仍存在多个竞争根因。每个角色最多自动升级一次；不要让低成本角色反复失败后持续重试。

## 预算模式

- `economy`：最多委派 1 个角色、并行 1 个、不自动升级。优先把工作留给主线程，只保留真正需要的独立研究或审核。
- `balanced`：最多委派 2 个角色、并行 2 个、每个角色最多升级一次。默认选择。
- `quality`：最多委派 3 个角色、并行 3 个、允许高风险角色使用更强能力档。

成本单位是模型能力档的相对权重，只用于比较计划，不代表 token、货币、credits 或节省百分比。实际用量只能来自宿主或 provider 的计量。预算不能跳过必需 cold review、测试、安全门禁或验证；超预算工作必须明确回到主线程，不能静默删除。

运行 `python3 scripts/resolve_role_route.py --roles <逗号分隔角色> --risk <low|medium|high|critical> --budget <economy|balanced|quality>` 可得到确定性计划。默认输出人话；机器证据需要时才加 `--json`。

## 精确模型解析

精确路由需要 catalog snapshot：

```json
{
  "provenance": {
    "source": "active-host-catalog",
    "source_id": "current host catalog/readback identifier",
    "observed_for_current_task": true,
    "root_provider": "configured-provider-id"
  },
  "models": [
    {
      "id": "exact-model-id",
      "provider": "configured-provider-id",
      "model_class": "balanced",
      "supported_reasoning": ["medium", "high"],
      "available": true,
      "authenticated": true
    }
  ]
}
```

该 snapshot 必须带当前 task 的来源读回，不能由 Skill 猜测。直接 model override 的 provenance 应来自当前宿主 catalog 或用户确认 exact ID，并与 root provider 相同；custom-agent provenance 应证明角色已加载、provider 已固定且已认证。但 JSON 中的 provenance 只是调用方提供的可追踪声明，解析器只能校验结构，不能机械证明其真实来源；因此 exact 候选固定标为 `planned-unverified`，`catalog_provenance_confirmed` 固定为 false。只有派发工具接受和运行时 metadata 读回才能升级状态。catalog 缺失、provider 不明、模型不可用或 schema 不支持时，回退顺序为：已加载 named custom agent → 当前 schema 的 direct route → 现有只读 CLI compatibility → 主线程或隔离 worktree。

回退不得谎称目标模型已经使用。子 Agent 自述模型名不能证明运行身份。

## 用户界面

默认只告诉用户：采用节省/平衡/质量优先配置、安排了哪些工作、哪些工作留在主线程，以及路由是否真正核对。不要展示 model/provider/reasoning 参数、JSON、相对成本单位或 receipt；用户明确要求技术证据时再展开。

后台状态对应的前台表达：

- `planned`：已规划。
- `planned-unverified`：已得到精确候选，但 catalog 来源尚未机械确认。
- `accepted`：已成功安排。
- `confirmed`：实际运行身份已核对。
- `inherited-unverified`：已安排，但宿主未提供运行身份读回。
- `unavailable`：精确路由不可用，已回到现有执行方式。

## 外部顾问扩展位

保留 provider-neutral、root-facing、read-only 的 `external_advisor`。默认 `none`，核心流程不依赖 Claude 账号、Fable/Faber、Claude Code SDK、BridgeDeck 或任何 MCP。未来 adapter 只能读取自包含计划包并返回建议；不得编辑、派发、接触 executor 或批准最终交付。适配器缺失时静默使用原生流程，只有用户明确把该顾问设为必需时才阻塞。
