# Self Improvement

目标：

让 Skill 根据反馈变聪明。

来源：

- 用户反馈
- Reviewer FAIL
- Gate FAIL
- Heartbeat
- Rescue
- 重复错误

默认：

- 幕僚长只记录 failure mode、派发 Skill维护-SKM / DEV、读回 receipt、采纳或拒绝；不得在主 COS 线程直接改 Skill、跑 gate、清理进程或把自己的 shell 输出当完成证据。
- Heartbeat / Automation 发现重复失败时，必须进入有界 self-improvement：生成补丁提案或派发 Skill维护-SKM，并在 `COS_HEARTBEAT_RUN_RECEIPT.self_improvement_*` 写明路径和证据。
- Automation 目标完成后必须自我回收：删除或暂停 automation，并记录 `self_recycle_status: deleted | paused` 与配置/工具回执；只写 heartbeat 存在不算生命周期完成。
- Memory 只写候选；用户全局记忆、全局规则、删除/清理/发布类动作必须按上级安全规则确认。
- Core `SKILL.md`、`assets/`、`references/`、`scripts/` 的补丁必须由 Skill维护-SKM / DEV worker 执行并跑对应 gate。

处理动作：

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

自动应用策略：

- project_memory: candidate_or_worker_applied
- project_agents_md: target_project_worker_patch
- skill_assets: skill_maintenance_worker_after_check
- skill_core: skill_maintenance_worker_required
- user_global_memory: explicit_user_request_only
- automation_cleanup: delete_or_pause_only_with_receipt
- worktree_process_cache_cleanup: audit_only_unless_current_task_owned_clean_worker
