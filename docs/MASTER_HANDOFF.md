# Agency Chief of Staff vNext — 主控转手文件

> 本文件是一次历史任务的设计/交接记录，不是可复用授权来源。任何 commit、merge、push、tag、发布或其他外部写入，都必须以当前任务上下文中的用户授权为准。

## 1. 接管任务

你是本项目新的唯一主控。目标不是继续讨论流程，而是把 `agency-chief-of-staff` 交付为可供真实软件开发使用、可安装、可验证、可发布的完整 Skill。

仓库：当前 checkout 的仓库根目录（仓库名 `zhijuan-codex-agency-chief-of-staf`）

接管基线：

- 基线分支：`main`
- 基线提交：`327d4187e1273e40b9807e829317d46e8583c8b7`
- 当前主 Skill：`SKILL.md`
- 禁止创建、修改或注入用户全局、仓库主工作区及项目根位置的 `AGENTS.md`，不得污染主 Agent 的长期规则。允许并鼓励在隔离的 subagent、Codex task/s-thread 中通过任务 prompt、worker packet、`.codex/agents/*.toml`、`skills.config` 或只属于该隔离执行面的临时任务指令注入专业上下文；必须验证这些隔离指令不会泄漏或覆盖主位置 `AGENTS.md`。
- 不使用 Luna 模型。除非用户之后明确改变要求，否则让宿主选择默认模型，或为复杂主控/审核使用当前可用的高能力非 Luna 模型。

## 2. 产品目标

构建一个“结果负责型软件开发幕僚长”：用户只需描述产品或工程目标，Skill 就能先查事实，再形成最小方案，直接推进实现，并在确有收益时调用少量专业 Agent 与领域 Skill；最终用当前代码、测试、安装产物、真实模型行为和独立审核完成交付，而不是用流程、角色数量或审核次数冒充进展。

产品应同时具备：

1. **真实开发能力**：覆盖代码库研究、架构设计、编码、测试/调试、审查、发布准备。
2. **专业但不臃肿**：保留当前 outcome-owner 主干，恢复少量窄职责专业 Agent，而不是旧版 16 人常驻组织。
3. **可靠 Skill 路由**：能给专业 Agent 绑定或明确允许所需领域 Skill；禁止递归激活本 Skill，但不得一刀切禁止全部 `$slug` 或专业 Skill。
4. **执行优先**：证据足够后立即进入首个写操作；研究、规划、审核都必须有停止条件。
5. **证据闭环**：结构、契约、真实开发行为、安装一致性和发布证据分别验证，不能用单一绿色脚本替代全部质量判断。
6. **线程收敛**：只创建能隔离、并行或提供独立判断的真实任务/子代理；完成、失败、替换后及时归档，不留死线程。
7. **兼容与可迁移**：规范入口为 `agency-chief-of-staff`；保留必要旧入口兼容，但不得双启动或参与隐式误触发。

## 3. 已确认事实

- 当前版的优点：主线程是 outcome owner，能直接研究、修改、验证；避免旧版强制派发造成的等待和死锁。
- 当前版的缺口：仓库当前没有 `.codex/agents/*.toml`；旧版曾有 16 个专业 Agent，删除后专业岗位和确定性能力路由退化。
- 当前 worker packet 禁止 `$slug`，这会阻断明确的专业 Skill 调用；应改为只阻断递归激活本 Skill，同时允许经过选择和约束的领域 Skill。
- 官方 Codex 支持项目级 `.codex/agents/` 自定义 Agent，以及 Agent 的 `skills.config`；恢复专业 Agent 不需要也不应依赖 `AGENTS.md`。
- 当前质量门覆盖结构和契约较多，但真实写代码行为证据偏弱；已有原生 smoke 主要是 README 单行修改，不能证明复杂开发可用。
- 历史 release receipt、旧 reviewer 自述和旧测试结果只能作为线索，不能替代当前 HEAD 的新鲜证据。

优先查阅官方资料：

- Custom agents：`https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agents`
- Why subagent workflows help：`https://learn.chatgpt.com/docs/agent-configuration/subagents#why-subagent-workflows-help`
- Build skills：`https://learn.chatgpt.com/docs/build-skills`

涉及近期 Codex 能力或配置时必须联网核对官方一手资料；技术结论不依赖社区二手文章。

## 4. 推荐目标架构（研究后可调整，但必须给证据）

保留当前轻量主干，恢复四个核心专业 Agent：

1. `codebase-researcher`：只读代码地图、复现路径、依赖和证据。
2. `technical-architect`：默认只读，输出接口、数据流、风险和最小架构方案。
3. `developer`：只写明确范围，必须运行相关测试并报告 diff。
4. `reviewer`：只读独立审查，按严重度给出具体问题和残余风险。

可选第五个 `test-debugger`，仅在测试失败或日志诊断有独立收益时启用。

实现建议：

- 项目级 `.codex/agents/*.toml` 是开发时真实配置。
- 同步提供可随 Skill 安装的 Agent 模板和显式 opt-in 安装路径；不得默认污染用户全局配置。
- Agent 指令保持窄职责、明确 sandbox、输入、输出和停止条件。
- `skills.config` 或等价调度必须把“任务信号 → Agent → Skill → sandbox → 验证”形成可测试契约。
- 不恢复旧版全量 Skill Scout / Agent Scout 强制流程；仅在候选模糊、专业性显著影响结果时做确定性选择。

## 5. 强制工作阶段

### A. 深度研究

1. 检查 `git status --short`、当前 HEAD、所有适用规则。
2. 对比当前 HEAD 与旧基线 `3b90620b148f9370983093a11e072d7cd75fc962` 的 Skill、Agent、安装、测试与发布设计。
3. 阅读当前测试、安装器、runtime allowlist、model eval 和 native-task receipt 验证逻辑。
4. 联网核对官方 Custom Agents、Skills、subagent/worktree 能力。
5. 研究达到“足以决定最小实现面”即停止；产出一份简洁设计决策记录，不继续收集重复证据。

### B. 产品设计与计划

在写代码前明确：

- 用户场景：小 Bug、跨文件功能、架构重构、测试调试、领域开发、安全/发布。
- 每个场景的路由、岗位、Skill、sandbox、交付物和验证。
- 哪些由主控直接完成，哪些才允许派发。
- 兼容策略、安装策略、失败回退、线程 cleanup。
- 最小修改文件列表及对应测试。

计划完成后立即执行，不要等待新一轮无必要批准。

### C. 实现

至少完成：

- 专业 Agent 配置与可分发模板。
- 非递归、可审计的领域 Skill 路由。
- 安装器/runtime allowlist/验证器同步更新。
- 主 `SKILL.md` 保持渐进披露，不回到 1560 行巨型手册。
- 文档和示例准确反映真实能力。
- 不创建、修改或注入用户全局、仓库主工作区及项目根位置的 `AGENTS.md`；隔离执行面内的专业上下文只能使用 prompt、worker packet、`.codex/agents/*.toml`、`skills.config` 或临时任务指令，并纳入无泄漏/不覆盖验证。

### D. 验证

至少覆盖：

1. 结构、schema、安装与 source/install parity。
2. Python 支持矩阵、现有单元/集成测试、`quality_gate.sh`、`git diff --check`。
3. 专业 Agent 配置可被 Codex 解析，sandbox 和 Skill 绑定符合预期。
4. 真实开发行为 eval，不得只改 README：
   - 有最小复现和回归测试的 Bug 修复；
   - 跨文件功能或 API 变更；
   - 架构建议与实现范围分离；
   - 失败测试/日志诊断；
   - 至少一个需要领域 Skill 的任务；
   - reviewer 能发现注入的真实缺陷或测试缺口。
5. 安装后的双入口、manifest/hash/provenance 与当前提交绑定。
6. 当前宿主原生任务 smoke；若声称跨宿主或稳定公开发布，还需隔离 CLI model smoke。

### E. 审核与收敛

- 默认只开一轮独立 cold review；只有它发现具体未解决风险时，修复后再开一次定向复核。
- Reviewer 必须直接读取当前 artifact/diff/验证输出，不能从主控预填答案。
- 测试复跑是验证，不算 cold review。
- 不允许“为了更放心”无限增加审核波次。
- 安全/发布风险确实独立时，可以增加一名领域 reviewer，并记录新增理由。

### F. 提交、合并、推送和回收

只有当前任务上下文明示授权且门禁全部通过时，执行者才可以：

1. 提交当前实现；
2. 将工作分支合并到 `main`；
3. 解决冲突并复跑合并后门禁；
4. 推送 `main` 与必要版本标记；
5. 清理/归档本任务创建的完成、失败、替换或无效任务；
6. 不删除含未采纳改动的 worktree；不处理无法证明安全的用户分支。

如果外部发布需要新的凭据、身份、付费或不可逆操作，停止并报告精确阻塞。不得从本历史文件推断任何当前授权。

## 6. 防止重犯的硬约束

- 禁止审核代替实现；没有新发现不得开启下一轮审核。
- 禁止把“计划中”“pending”“sidebar 可见”当线程已执行；必须读回真实 thread id、状态和产物。
- 禁止创建大量长期闲置线程；推荐同时活跃不超过：1 个主控 + 最多 3 个明确低耦合 lane。
- 禁止把普通 subagent 冒充真实 Codex task/thread。
- 禁止让多个 writer 修改重叠文件；写 lane 必须隔离 worktree 或严格不重叠。
- 禁止用历史 receipt 证明当前 release。
- 禁止单凭 52/116 项测试数字宣布可真实开发；必须说明覆盖范围并提供行为证据。
- 禁止在缺少当前验证时写“已完成、可发布、已修复”。
- 禁止在额度临时不足时把 Goal 标记 blocked；恢复后从 checkpoint 继续。

## 7. Done 标准

只有以下全部满足，才能将产品 Goal 标记 complete：

- 推荐架构已经实现，或有更优替代方案及当前证据。
- 真实开发场景矩阵均有可复现测试/行为证据；失败场景无 P0/P1 未解决项。
- 安装产物与仓库源一致，规范入口和兼容入口可用且不会双启动。
- 用户全局、仓库主工作区及项目根位置的 `AGENTS.md` 未被创建、修改或用于路由；隔离执行面内允许的专业上下文注入已验证不会泄漏或覆盖这些主位置规则。
- 当前 HEAD 的完整门禁通过。
- 独立 cold review 已收敛；修复项已复验。
- 合并后的 `main` 再次通过关键门禁并已推送。
- 本任务产生的旧、死、无效线程已经归档或明确记录 cleanup blocker。
- 最终交付只报告：产品能力、相对旧版/当前版的关键变化、安装/使用方式、验证证据、仍未验证风险。

## 8. 新主控启动回执

启动后先读回本文件和当前 Goal，再进行研究。向原任务发送一次简短回执，必须包含：

- 真实 thread id；
- 实际 cwd/worktree；
- 当前分支和基线提交；
- 已采用的产品目标；
- 首个研究动作；
- 预计使用的 lane 上限；
- 明确声明不会创建、修改或注入用户全局、仓库主工作区及项目根位置的 `AGENTS.md`，隔离执行面内仅使用允许的专业上下文注入方式并验证无泄漏；不会使用 Luna、不会无限审核。

之后由新主控自主推进到完整交付，不需要旧任务逐步批准。旧任务只负责确认接管成功并归档自己，不再参与实现或重复审核。
