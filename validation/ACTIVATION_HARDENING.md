# Activation Hardening Validation

Date: 2026-07-04

This file records the v0.1.6 live activation smoke after installing the source bundle to:

```text
/Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf
```

## Local Gates

- `python3 scripts/install_skill.py --force --json`: `status=overwritten`, `installed_files=98`.
- Installed-copy parity: `diff -qr -x .git -x .codex -x __pycache__ -x .pytest_cache -x agency-thread-pilot -x .DS_Store /Users/jinjungao/.agents/skills/zhijuan-codex-agency-chief-of-staf .` exited 0.
- `bash scripts/quality_gate.sh .`: exited 0 and printed `Open-source package quality gate passed with documented ThreadOps evidence.`
- `scripts/quality_gate.sh` now generates a fresh temporary `ACTIVATION_CONTRACT_RECEIPT.json` during each run and checks receipt type, `status=valid`, eval coverage, and source hashes for `SKILL.md`, `agents/openai.yaml`, and `evals/activation.prompts.csv`.

## Smoke 1: Explicit Boot, No Dispatch

Thread: `019f2d91-0e96-7de1-9b25-8c3b7c545811`

Prompt:

```text
使用 $zhijuan-codex-agency-chief-of-staf。Activation smoke only: 不要改文件，不要创建子线程。先输出 COS_BOOT_RECEIPT，然后把当前任务判为 T0/T1，并记录 thread_dispatch_decision: no_dispatch 及原因。最后输出 SMOKE_RECEIPT。
```

Result:

```yaml
COS_BOOT_RECEIPT:
  skill_loaded: true
  trigger_type: explicit
  thread_role: COS
  title_action: title_update_blocked
  complexity: T0
  thread_tools_available: true
  thread_dispatch_decision: no_dispatch
  reason: "Activation smoke only; user explicitly forbade child-thread creation. Current thread id was not safely available for self-title update."

SMOKE_RECEIPT:
  status: done
  classification: T0
  changed_files: []
  child_threads_created: false
  thread_dispatch_decision: no_dispatch
```

Verdict: passed. Explicit invocation produced `COS_BOOT_RECEIPT` before task completion and honored the user's no-child-thread constraint.

## Smoke 2: Explicit Real Thread Dispatch

Coordinator thread: `019f2d91-2713-72f3-8a10-737a80eef610`

Worker thread: `019f2d92-193e-7a12-8c12-4e19d4c5e264`

Prompt:

```text
使用 $zhijuan-codex-agency-chief-of-staf。真实线程 smoke：不要改文件。请创建一个真实 Codex Thread 只读检查 README.md 是否包含 COS_BOOT_RECEIPT 和 THREAD_DISPATCH_RECEIPT，必须返回 THREAD_DISPATCH_RECEIPT、worker thread id、worker receipt、adoption/rejection、cleanup 状态。如果当前环境没有真实 Codex Thread 工具，必须输出 TOOL_BLOCKED，不得用 subagent 或同线程模拟。
```

Coordinator boot:

```yaml
COS_BOOT_RECEIPT:
  skill_loaded: true
  trigger_type: explicit
  thread_role: COS
  title_action: self_set
  complexity: T2
  thread_tools_available: true
  thread_dispatch_decision: dispatch
```

Worker receipt:

```yaml
WORKER_RECEIPT:
  task_id: TASK-README-SMOKE-001
  thread_role: read_only_worker
  status: done
  read_scope: README.md
  write_scope: none
  contains_COS_BOOT_RECEIPT: true
  contains_THREAD_DISPATCH_RECEIPT: true
  commands_run:
    - "pwd"
    - "ls -la README.md"
    - "rg -n 'COS_BOOT_RECEIPT|THREAD_DISPATCH_RECEIPT' README.md"
  changed_files: []
```

Coordinator final:

```yaml
THREAD_DISPATCH_RECEIPT:
  thread_id: "019f2d92-193e-7a12-8c12-4e19d4c5e264"
  thread_class: review_worker
  read_scope: "/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf/README.md"
  write_scope: "none"
  expected_receipt: "WORKER_RECEIPT"
  cleanup_plan: archive_after_receipt
  status: dispatched

adoption:
  decision: adopted

cleanup:
  status: archived

SMOKE_RECEIPT:
  status: done
  validation_status: 已验证
```

Verdict: passed. Explicit real-thread request created a real worker thread, returned a real worker receipt, adopted it, and archived cleanup.

## Residual Risk

These smoke tests prove the installed skill can activate and dispatch in this Codex Desktop environment. They do not prove every future Codex surface will discover the skill; upstream discovery/runtime issues can still affect specific app, CLI, IDE, or phone composers. The mitigation is to keep `allow_implicit_invocation: true`, use explicit `$zhijuan-codex-agency-chief-of-staf`, and add `references/AGENTS_ROUTING_SNIPPET.md` to `AGENTS.md` when default routing is required.

## Adversarial Review

- Round 1 activation critic thread `019f2d95-9679-7aa1-b2c0-0700e01ca043`: verdict `pass`; explicit invocation and real-thread dispatch-or-TOOL_BLOCKED rules are present.
- Round 2 validation critic thread `019f2d95-9e88-7240-ab97-aa0bfe0a4cee`: initial verdict `fail`; finding was that quality gate could pass by grepping stale historical smoke text.
- Round 2B validation re-review thread `019f2d97-74d8-7601-a4a2-cebf23b716c4`: verdict `pass`; blocker closed after adding fresh `ACTIVATION_CONTRACT_RECEIPT.json` generation and checks to the quality gate.
- Round 3 release honesty thread `019f2d95-a853-7051-b22f-7fa45924a30f`: verdict `go_for_commit_push_release_v0.1.6`; no blockers in scoped README/CHANGELOG/validation review.

Rejected evidence:

- Threads `019f2d94-40f1-7da2-89d4-7d998a740e59`, `019f2d94-5f22-7952-8f11-bae433fe7e8f`, and `019f2d94-6b2b-77a1-939a-418c5cdd930f` did not return review receipts within bounded polling and were archived as `thread_not_converged`.
