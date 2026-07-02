# SELF_IMPROVEMENT

## 输入来源

- 用户反馈
- Reviewer FAIL
- Gate FAIL
- Heartbeat 问题
- Rescue 事件
- 重复错误
- Skill Scout 匹配失败
- Goal Drift

## 处理动作

| 类型 | 默认动作 |
|---|---|
| 当前任务偏好 | 写 L1 记忆 |
| 项目规则 | 写 L2 记忆 / AGENTS.md 补丁 |
| 用户偏好 | 写 L3 候选记忆 |
| 强制禁令 | 写 L4 候选，需确认 |
| Skill 结构问题 | 生成 PATCH_PROPOSAL |
| 核心 Skill 问题 | Skill维护-SKM 生成补丁并跑检查 |

## 自动应用策略

- project_memory: auto
- project_agents_md: propose_or_auto
- skill_assets: auto_after_check
- skill_core: propose_by_default
- user_global_memory: propose_by_default
