# Skill and Agent Routing

流程：

```text
任务进入 T2+
→ Skill Scout 扫描本机 Skills
→ Agent Scout 扫描本机 Agents
→ 评分
→ 幕僚长写入 Task Card
→ 执行线程显式使用选中的 Skill/Agent
```

评分维度：

- 任务匹配
- 输出物匹配
- 工具匹配
- 历史成功
- 历史失败
- 过重风险
- 过轻风险
- 与 Goal 是否一致
