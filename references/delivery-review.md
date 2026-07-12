# Delivery and Independent Review

在 release readiness、Skill hardening、公开发布、多文件可靠性或客户可见交付时读取本文件。

## 证据层级

按以下顺序判断：

1. 当前文件、diff、构建、测试、工具 readback 和人工复核。
2. 与当前 commit/manifest 绑定的 fresh model smoke 或 thread evidence。
3. 当前 worker 产物，经主线程独立核验后采纳。
4. 历史 receipt、旧 validation 文档、标题和自述，只作线索。

任何 gate 只能证明它真实覆盖的不变量。字符串 grep、作者预写 fixture 或示例生成器不能证明模型行为。

## Cold review

默认给不同上下文中的原生 subagent 或专用 review 工具；只有用户已明确要求真实 task/thread 执行面时，才使用独立 task/thread reviewer：

- 原始目标和约束。
- 变更 diff 或最终 artifact。
- 实际运行的验证及原始结果。
- 允许读取的最小上下文。

要求 reviewer 直接读取审核时的当前 artifact，并返回至少一个未在委派 prompt 中披露的具体读回事实。主线程不得先读取该事实再转述给 reviewer。这个事实只证明实际读回，不能替代 diff、测试或领域判断。

不要给 reviewer 主线程的结论、预期答案或“应该找出的问题”。Reviewer packet 的`期望产物`只描述证据类型、必需标签和终态 schema；不得预填 artifact 原文、目标值、隐藏 marker 或其他本应由 reviewer 直接读回的事实。如果 reviewer 不读当前 artifact 也能只靠 packet 拼出成功终态，该 packet 不合格。默认 packet 也不含任何 `$slug` 或 guard-read 指令，避免 worker 再次进入主流程；真实 task/thread id 记录在工具 readback 或 receipt，不附加到六字段 packet。

同一主线程再次读 diff、运行 grep 或复跑测试是验证，不是独立 cold review。仅请求 `none` / `fork_context:false` 不算隔离 readback；若工具返回事件没有显式回显上下文隔离，最终必须原样包含机器可核验行 `COLD_CONTEXT_ISOLATION: UNVERIFIED`。不能从 reviewer id 绑定其直接读取事件时，还必须原样包含 `reviewer-owned read 未验证`。若当前环境没有独立 reviewer 能力，结论必须是 `独立审核未验证`。

代码审查按严重度输出文件、行号、影响和最小修复。文档/Skill/方案审查优先找会导致误触发、执行偏差、假完成、权限扩大或验证缺口的问题。

主线程修复后做定向复核。默认一轮 cold review 加一轮修复复核；继续增加 reviewer 必须有尚未覆盖的独立风险。

## Release readiness

至少核验：

- 当前工作树和目标 commit。
- runtime bundle/安装产物与源文件一致。
- 结构与 contract 测试。
- 隔离项目/配置中的真实模型前测；禁用无关 plugins/apps，绑定当前 manifest/case/runner，并确认专用 eval 凭据风险。same-user 临时 auth 不是 secret sandbox。
- 用户明确要求的真实 ThreadOps 证据。
- 独立 cold review 已收敛。
- 发布、push、tag、PR 等外部动作已获明确授权。

缺任何当前证据时写 `未验证`，不要用旧 release receipt 补位。

## 领域交付物

创意、提案、分镜、文案、研究或执行方案不能只凭线程完成或脚本 PASS 宣称 `client-ready`。还要检查：

- brief 和受众是否可追溯。
- 关键要求是否保留。
- artifact 是否真实存在且可打开/使用。
- 领域质量门是否通过。
- 来源、资产或参考是否可追溯。
- 独立领域审核是否完成。

需要机器审计时使用 [assets/DELIVERY_EVIDENCE_TEMPLATE.yaml](../assets/DELIVERY_EVIDENCE_TEMPLATE.yaml)。

## 验证措辞

- `已验证`：本轮有直接证据。
- `未验证`：尚未运行、工具不可用或只有历史线索。
- `验证失败`：本轮验证已运行且失败。

不要用 `PASS` 代替质量判断，除非同时说明 PASS 的具体范围。
