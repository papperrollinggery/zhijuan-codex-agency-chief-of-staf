# 使用说明

## 启动幕僚长

```text
使用 $zhijuan-codex-agency-chief-of-staf 启动幕僚长模式。
先判断当前项目、目标、输出物、复杂度，再决定是否进入 Plan / Goal。
```

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
1. 先判断复杂度 T0-T5。
2. 决定是否 Plan / Goal。
3. 扫描 Skill / Agent。
4. 为有状态线程分配 Goal。
5. 子线程只返回 Packet。
6. Reviewer 独立审查。
7. 幕僚长只负责管理和沟通，不做审核。
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
