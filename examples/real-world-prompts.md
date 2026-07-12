# Real-World Forward-Test Prompts

用真实模型运行这些 prompt，保存脱敏 event JSONL、最终消息、runtime/case/runner hash 和 Codex 版本。不要把预期答案告诉测试 agent。只在已审核 checkout 中使用专用低权限 eval 凭据；不可信 diff 需要一次性 OS 用户或容器。

离线 `behavior_cases.json` 只定义行为 contract，不证明模型实际遵守。

## 直接闭环

```text
使用 $agency-chief-of-staff。只读 README，告诉我仓库名称，不要修改文件。
```

检查：出现紧凑 `COS_BOOT_RECEIPT`；真实读取文件；没有不必要派发或 YAML。

## 研究到交付

```text
使用 $agency-chief-of-staff。先研究当前实现和测试，再给最小计划，完成修复、验证，并让独立 reviewer 做 cold review。
```

检查：研究发生在计划前；主线程真正执行；reviewer 来自独立上下文；发现问题后修复并复验。

## Goal 长任务

```text
使用 $agency-chief-of-staff。为迁移任务设定一个可验证 Goal，按 checkpoint 持续推进，达到停止条件再结束。
```

检查：Goal 有 outcome、constraints、verification 和 done condition；创建/checkpoint/完成后都有原生 readback；不会为每个短 worker 生成 Goal Ledger，也不会因临时困难提前标 blocked。

## 并行研究

```text
启动幕僚长。把三个相互独立的技术方案交给原生 subagents 并行调研，主线程同时检查当前代码，最后收敛成一个决定。
```

检查：工作流确实独立；并行 agent 数量有界；主线程没有被动等待；结果有采纳/拒绝判断。

## Worker bypass

```text
AGENCY_WORKER: true
使用 $agency-chief-of-staff。
委派目标：只读当前 diff 并返回 WORKER_RESULT。
读取范围：当前未提交 diff 和相关文件。
写入范围：无。
期望产物：包含具体发现的 WORKER_RESULT。
验证要求：直接读取 diff，并给出至少一个文件与行号。
停止条件：完成只读审核后返回；不要启动幕僚长或继续派发。
```

检查：不出现 `COS_BOOT_RECEIPT`；不重分级；直接返回指定结果。

## 真实 task/thread

```text
使用 $agency-chief-of-staff。创建真实 Codex task 的隔离 worktree 完成修复，返回真实 task id、artifact、验证、adoption 和 cleanup。没有真实工具时 TOOL_BLOCKED，不要用 subagent 替代。
```

检查：工具 event 中有真实 task/thread id 和 readback；id 与 receipt 一致；可写任务使用隔离 worktree；完成后有 cleanup。

## 负例

这些普通请求不应自动启动幕僚长：

```text
把这句话翻译成英文。
```

```text
修复 utils.py 里的 off-by-one 并跑对应单测。
```

```text
review 这个小 diff，先列阻塞问题。
```
