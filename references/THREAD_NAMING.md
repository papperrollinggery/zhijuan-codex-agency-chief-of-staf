# Thread Naming

统一格式：

```text
[项目编号-线程编号-R轮次] 中文职位-英文缩写｜任务短名｜任务ID｜输出ID
```

示例：

```text
[P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000
[P01-TH04-R01] 技能侦察-SKS｜PPT技能匹配｜TASK-003｜OUT-SKILL
[P01-TH09-R01] 审查官-REV｜反证验收｜TASK-005｜OUT-REV
```

## 启动即命名

幕僚长-COS 启动时必须先处理当前线程标题：

```text
当前线程内有 set_thread_title 或等价工具：立即改为 [P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000
用户明确要求保留标题：不改名，记录 title_preserved_by_user
当前线程内没有标题工具：不声称已改名，记录 title_update_blocked，并要求调度层兜底
```

worker 线程由调度层创建或复用后，调度层必须尽快用规定格式命名；如果工具返回 pendingWorktreeId，必须等实际 thread_id 出现后再记录 dispatch receipt。

标题验证必须看 Codex thread 元数据：

```text
preferred evidence: read_thread/list_threads 显示的实际 title
insufficient evidence: worker 自述“已改名”但没有 thread 元数据
receipt title_action: self_set | dispatcher_set | title_preserved_by_user | title_update_blocked
```

如果 worker 自己没有成功改名，但调度层用 thread_id 修正了标题，记录 `dispatcher_set`，不要记录成 `self_set`。
