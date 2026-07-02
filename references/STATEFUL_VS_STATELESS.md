# Stateful vs Stateless

Stateful Agent：

- 需要持续上下文
- 有 Task Card
- 有 Goal
- 有 Result Packet
- 有 Reviewer

Stateless Probe：

- 一次性探测
- 不改文件
- 不维护状态
- 不需要 Goal
- 返回 Probe Packet

优先用 Stateless Probe。  
只有需要连续上下文时才升级 Stateful Agent。
