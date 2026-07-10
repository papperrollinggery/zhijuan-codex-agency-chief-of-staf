# Long-Running Work

在用户明确要求 Goal、长期推进、定期检查、恢复任务或自动化时读取本文件。

## Goal

优先使用当前环境的原生 Goal 能力。Goal 包含：

- 一个结果导向的 objective。
- 不能突破的 constraints。
- 可执行的 verification。
- 明确的 done/blocked 条件。

Goal 是当前任务的持续目标，不是扩大权限。不要为每个 worker 建 Goal Ledger；短 worker 只继承父目标和自己的范围。

按 checkpoint 推进，每个 checkpoint 说明：当前结果、验证、剩余项和阻塞。完成标准未满足时继续做下一项有价值的工作。

原生 Goal 生命周期：

1. 仅在用户明确要求时处理 Goal；先读回当前 Goal。没有 active Goal 或现有 Goal 已结束时才创建；active Goal 同目标则续用，目标冲突则不得覆盖并请求用户选择。创建后再次读回 objective、状态和剩余预算/约束。
2. 每次恢复或 checkpoint 开始先读回现有 Goal，禁止重复创建或用本地文件冒充原生状态。
3. 推进实际任务并验证；状态摘要不能替代产物。
4. 只有 objective 已实现、完成标准全部有当前证据且没有必做项时，才调用原生更新能力标记 `complete`。
5. 完成更新后再次读回；最终回复报告真实状态。若宿主返回 token/时间用量，按其要求报告。
6. 只有同一阻塞达到宿主规定的连续阈值、且没有安全的有价值工作可继续时，才标记 `blocked`。临时额度、任务困难、不确定或尚未验证不等于 blocked。

原生 Goal 工具不可用时，明确写“Goal 生命周期未验证”，继续原授权范围内可完成的工作；不要创建 `GOAL.md`、Ledger 或伪造状态来替代。

## Plan 与 Goal

- 目标仍模糊：先研究或使用 Plan 形成可验证目标。
- 目标已清晰且需要多轮持续推进：使用 Goal。
- 单轮可完成：不用 Goal。

不要只建议用户输入 `/plan` 或 `/goal` 后停止；当前工具能直接建立或推进时就执行。

## Automation

只有用户明确要求定时、周期或后台触发时才创建 automation。Automation prompt 应显式调用本 Skill 或明确写出完整工作，不依赖 `AGENTS.md` 路由。

创建或核验 automation 时记录：

- automation id 和实际 prompt。
- 目标 task/thread 的真实 id 与 readback。
- schedule、时区和下一次 due。
- 本次 run 是否真实发生及其产物。
- 目标完成后的 pause/delete 状态。

`ACTIVE` 只证明配置存在，不证明本次运行。自然触发尚未到期时只能写 `NOT_DUE`，不能写失败；到期后没有 run evidence 才能写未运行或失败。

自动化发现失败模式时，在当前授权范围内修复并验证；不要自动写 Memory、Skill 或 `AGENTS.md`，除非用户明确要求。
