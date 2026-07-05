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
| 当前任务偏好 | 写 L1 候选记忆或项目内说明 |
| 项目规则 | 派发目标项目 worker 产出 AGENTS.md 补丁和验证 |
| 用户偏好 | 写 L3 候选记忆；只有用户明确要求才落盘 |
| 强制禁令 | 写 L4 候选，需确认 |
| Skill 结构问题 | 派发 Skill维护-SKM 生成 PATCH_PROPOSAL 或最小补丁 |
| 核心 Skill 问题 | Skill维护-SKM / DEV worker 生成补丁并跑检查 |
| Heartbeat 到期 | 真实 dispatch / dispatch_pending / TOOL_BLOCKED / thread_not_converged |
| Heartbeat 发现失败模式 | 记录 bounded self-improvement path，派发 SKM 或生成补丁提案 |
| Automation 目标完成 | 删除或暂停 automation，记录 self-recycle evidence |

## 自动应用策略

- project_memory: candidate_or_worker_applied
- project_agents_md: target_project_worker_patch
- skill_assets: skill_maintenance_worker_after_check
- skill_core: skill_maintenance_worker_required
- user_global_memory: explicit_user_request_only
- automation_cleanup: delete_or_pause_only_with_receipt
- worktree_process_cache_cleanup: audit_only_unless_current_task_owned_clean_worker

## COS 边界

- 主 COS 只记录 failure mode、派发、读回、采纳/拒绝、归档。
- 主 COS 直接产生的 `commands_run`、`changed_files`、`quality_gate.sh`、`release_smoke.sh`、`ps`、`kill` 只能作为 `cos_main_overexecution` 线索。
- 跨项目优化必须进入目标项目会话或 target project-bound worker。
