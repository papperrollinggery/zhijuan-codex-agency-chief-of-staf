# Real-World Forward-Test Prompts

Use these prompts to test whether the skill behaves naturally on real tasks. Do not give the tester the expected answer.

For each run, record whether the result started with `COS_BOOT_RECEIPT`, then whether it was direct, planned, goal-tracked, delegated, rescued, or rejected as `TOOL_BLOCKED`. When real Codex Threads are used, keep the thread id, receipt, adoption/rejection, and cleanup status.

1. 使用 $zhijuan-codex-agency-chief-of-staf。这个项目我想正式用起来，但不知道现在差什么，你帮我看看。
2. 使用 $zhijuan-codex-agency-chief-of-staf。给我一句最短调用方式。
3. 使用 $zhijuan-codex-agency-chief-of-staf。这个 Skill 到底装到哪里了？结构完整吗？
4. 使用 $zhijuan-codex-agency-chief-of-staf。我要用它来做一个 PPT 提案项目，应该调用哪些本机能力？
5. 使用 $zhijuan-codex-agency-chief-of-staf。我有个品牌活动想法，但方向还没定，你先帮我搭团队和讨论方式。
6. 使用 $zhijuan-codex-agency-chief-of-staf。我要让它长期跟进一个代码迁移和自动修复项目，不能半路忘目标。
7. 使用 $zhijuan-codex-agency-chief-of-staf。这里有一个故意缺字段的 YAML，请让执行者修、审查者查，并留下验证证据。
8. 使用 $zhijuan-codex-agency-chief-of-staf。这个低风险任务需要另一个线程检查一下，判断是否值得真的派发，并记录 thread id 或不派发原因。
9. 使用 $zhijuan-codex-agency-chief-of-staf。这个线程一直没结果，接管一下，只补失败项，不要重跑全部。
10. 使用 $zhijuan-codex-agency-chief-of-staf。它老把轻任务搞得太重，记住这个问题并提出修补方式，但先别改 Skill 本体。

## Activation Pressure Prompts

Use these to catch the specific failure where the model directly executes instead of booting COS.

1. 启动幕僚长。制定规划、开发、执行、审核，完整团队完成这个 Skill 的测试修复。
2. 按 Codex Agency 流程处理。开另一个线程做前测设计，主线程负责监察并记录 cleanup。
3. 我要真实 Codex Threads，不要同线程模拟；让规划、开发、审核分别跑，并归档完成线程。
4. 使用本 Skill。这个任务很小：告诉我当前仓库名字。
5. 使用 $zhijuan-codex-agency-chief-of-staf。帮我写一个绘画提示词，但先判断是否需要图像 Skill 或创意线程。

## Black-Box Complex Prompts

These prompts intentionally avoid `$skill`, Chief-of-Staff, thread, receipt, and cleanup wording. They test whether complex task wording is enough to route into the Skill when the surrounding project instructions allow it. The machine-readable set lives in `evals/blackbox_complex.prompts.csv`.

1. 这个仓库我想正式对外发布，但不确定差什么。请先判断缺口，只做最小必要修复，并给出可验证结论。
2. 线上导出功能偶发失败，已有日志、用户截图和一个半成品补丁。请先理清证据、定位风险，再安排修复和复核。
3. 先调研现有做法，再在这个项目里落一个最小可用实现，最后说明哪些结论来自本机验证。
