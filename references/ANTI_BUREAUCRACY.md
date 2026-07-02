# Anti-Bureaucracy

规则：

1. T0 不建文件。
2. T1 不开团队。
3. T2 不建复杂 Task Graph。
4. T3 以上才做多线程。
5. T4/T5 才做 Goal + Heartbeat。
6. 执行线程只返回 Packet。
7. 记录官负责状态。
8. 管理动作必须降低返工概率。
9. 幕僚长不审核、不执行、不记录全局状态。
10. 子线程是否启动由复杂度决定，不是硬门槛。
11. 当用户明确限定“只补测失败项 / 不重跑全部 / 不创建子线程 / 只写指定目录”时，按 bounded rescue 处理：不得升级为全量 Agency 流程，只写指定产物并运行指定验证。
12. 轻任务的正确表现是更少动作和更快闭环，不是生成更多管理模板。
13. 执行/审核线程先交付命令结果、artifact 或 receipt，再解释流程。
14. 一次收敛提醒后仍没有 artifact 或 receipt，按 `thread_not_converged` 处理并触发 bounded rescue。
