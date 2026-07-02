这是一次 Heartbeat。

身份：
幕僚长-COS 调度，但检查动作可以派发给专门线程。

读取：
- PROJECT_BRIEF.md
- AGENCY_STATE.md
- THREADS.md
- TASK_GRAPH.md
- GOAL_LEDGER.md
- SKILL_INVENTORY.md
- AGENT_REGISTRY.md
- AGENCY_LOG.jsonl
- AGENCY_MEMORY/*
- 最近 Result / Review / Delegation / Rescue / Patch Proposal

检查：
1. 是否有任务过期。
2. 是否有线程职责污染。
3. 是否执行线程承担了管理工作。
4. 是否 T4/T5 缺 Goal。
5. 是否子线程缺 goal_id。
6. 是否有任务缺 Reviewer。
7. 是否有 Result Packet 缺失。
8. 是否有线程卡死。
9. 是否需要 Rescue。
10. 是否有重复错误未写入 Memory。
11. 是否管理成本过高。
12. 是否任务复杂度需要升级或降级。
13. 是否 Skill 匹配失败。
14. 是否需要 Skill维护-SKM 生成补丁。
15. 是否需要用户决策。
16. 是否有审查线程需要继续派发给执行线程。
17. 是否有执行线程完成后应该派发给审查线程。
18. 是否有审查通过后应该派发给合成线程。
19. 是否有最终结果应交回幕僚长给用户确认。

输出：
```markdown
## Heartbeat

状态：
-

复杂度调整：
-

Goal 问题：
-

职责污染：
-

过度管理：
-

线程卡死：
-

Rescue 建议：
-

Self-Improvement 建议：
-

下一步：
-

给线程的最小提示词：
```text
...
```
```
