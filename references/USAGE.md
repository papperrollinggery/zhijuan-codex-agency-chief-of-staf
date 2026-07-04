# 使用说明

## 启动幕僚长

```text
使用 $zhijuan-codex-agency-chief-of-staf 启动幕僚长模式。
第一条可见输出先给 `COS_BOOT_RECEIPT`，再判断当前项目、目标、输出物、复杂度，并决定是否进入 Plan / Goal。
```

如果不写 `$zhijuan-codex-agency-chief-of-staf`，但说“幕僚长 / Codex Agency / 完整团队 / 真实 Codex Threads / thread id / receipt / cleanup / 自动调度 / 反驳审核 / 线程卡住”，也应触发本 Skill。

## 进入 Plan mode

```text
/plan 使用 $zhijuan-codex-agency-chief-of-staf 进入前期共创。
请澄清项目、目标、输出物、限制、候选方向，并判断是否需要 Goal。
```

## 进入 Goal mode

```text
/goal 按 GOAL_LEDGER.md 中 ROOT-GOAL 执行。使用 $zhijuan-codex-agency-chief-of-staf 保持幕僚长职责，不亲自执行；完成项目分级、Skill 匹配、线程派发、状态收敛和用户确认。
```

## 做 Skill 匹配

```text
使用 $zhijuan-codex-agency-chief-of-staf 派发 技能侦察-SKS。
扫描本机所有相关 Skill，比较哪个最适合当前任务，并输出 Skill Selection Packet。
```

## 复杂任务调度

```text
使用 $zhijuan-codex-agency-chief-of-staf 调度此任务。
要求：
1. 先输出 `COS_BOOT_RECEIPT`。
2. 判断复杂度 T0-T5。
3. 决定是否 Plan / Goal。
4. 扫描 Skill / Agent。
5. 为有状态线程分配 Goal。
6. 子线程只返回 Packet。
7. Reviewer 独立审查。
8. 幕僚长只负责管理和沟通，不做审核。
```

## 强制真实线程

```text
使用 $zhijuan-codex-agency-chief-of-staf。请创建真实 Codex Threads 的 isolated worktree worker 来修这个问题，并返回 thread id、THREAD_DISPATCH_RECEIPT、worker receipt 和 cleanup 状态；如果当前环境没有真实线程工具，请报告 TOOL_BLOCKED，不要用 subagent 代替。
```

## Heartbeat

```text
使用 $zhijuan-codex-agency-chief-of-staf 做一次 Heartbeat。
检查 Goal 遗忘、职责污染、线程卡死、任务不收敛、重复错误、Skill 匹配失败，并建议 Rescue 或 Skill 自我优化。
```

Codex automation heartbeat 只执行 automation prompt。若自动化 prompt 没有显式写 `使用 $zhijuan-codex-agency-chief-of-staf`，且目标线程/项目没有 AGENTS routing shim，就不会自动启动幕僚长。像“只发送一句话，其他什么都不要做”的 heartbeat 不应被本 Skill 接管。

可验证 contract:

- 需要 COS heartbeat 时，automation prompt 必须保留 `使用 $zhijuan-codex-agency-chief-of-staf`，或目标上下文必须有 AGENTS routing shim；输出应先出现 `COS_BOOT_RECEIPT`。
- T4/T5 heartbeat 不能只在同线程“检查一下”；必须真实派发 worker，或在缺工具时输出 `TOOL_BLOCKED`。
- 只发送固定一句话的 heartbeat 是 plain emitter，不需要也不应出现 `COS_BOOT_RECEIPT`。
- 声称 Heartbeat/Automation 已启用时，必须给出 `automation_prompt` 文本/路径加 `prompt_contains_skill_invocation: true`，或明确的 `agents_routing_evidence` / `AGENTS routing shim`；裸 `AGENTS.md` 提及、未检查 AGENTS.md、没有 prompt evidence 的启用声称按 invalid 处理。

## 发布验证

```bash
bash scripts/release_smoke.sh .
```

## 领域交付验证

创意、分镜、提案、资料整理、文案、故事、执行规划等任务，如果要声明 `client-ready`、`ready to send`、`可交付` 或 `可发布`，必须收敛 `DOMAIN_DELIVERABLE_RECEIPT`，不能只靠 worker receipt 或测试 PASS。

```bash
python3 scripts/validate_domain_deliverable_contract.py .
```

需要生成本地 pilot 证据时：

```bash
python3 scripts/pilot_harness.py --root . --out /tmp/agency-thread-pilot
```
