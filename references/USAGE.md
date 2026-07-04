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

## 发布验证

```bash
bash scripts/release_smoke.sh .
```

需要生成本地 pilot 证据时：

```bash
python3 scripts/pilot_harness.py --root . --out /tmp/agency-thread-pilot
```
