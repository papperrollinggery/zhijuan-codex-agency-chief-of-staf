# PATCH_PROPOSAL

## Patch ID

PATCH-

## 触发来源

用户反馈 / Reviewer FAIL / Heartbeat / Rescue / 重复错误

## 执行身份

- worker_thread_id:
- source_thread_id: 不填写
- worker_prompt_identity_contract: included | pending_until_thread_id_known
- 主 COS 执行证据: 不采用；如存在，记录 `cos_main_overexecution`

## 问题

待填写。

## 根因

待填写。

## 修改目标

- 

## 影响文件

- 

## 补丁内容

```diff
```

## 检查命令

```bash
bash scripts/check_structure.sh .
bash scripts/release_smoke.sh .
```

## 风险

- 

## 是否可自动应用

是 / 否

## Automation 生命周期

- dispatch_status: dispatched | dispatch_pending | tool_blocked | thread_not_converged | not_applicable
- self_improvement_status: needed | patch_proposed | patched | blocked | not_needed
- self_recycle_status: not_complete | deleted | paused | blocked | not_applicable
- self_recycle_evidence:

## Cleanup 安全

- cleanup_scope: audit_only | current_task_owned_clean_worker | blocked
- delete_files_allowed: false
- kill_process_allowed: false
- cleanup_blocked_reason:
