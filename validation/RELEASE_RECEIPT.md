# Release Convergence Receipt

Machine-readable source: `validation/release_receipt.json`.

This receipt is the single release table for dispatch, adoption or rejection, cleanup, and review verdicts. Worker receipts and council notes are supporting evidence only; release readiness is decided from this consolidated artifact plus the validators.

| Thread | Class | Wave | Receipt | Adoption | Cleanup | Verdict |
|---|---|---:|---|---|---|---|
| `019f23be-a188-7402-968e-f223d32e4419` | scout worker | - | received | adopted | archived | n/a |
| `019f23be-a3a0-7a60-9849-419ec1424b46` | agent scout worker | - | received | adopted | archived | n/a |
| `019f23bf-ed5b-7c61-9f44-b3fc2c41825a` | implementation worker | - | received | adopted | archived | n/a |
| `019f23c6-cec3-7ad2-a68b-2bb16f9ef8b0` | review worker | 1 | received | adopted | archived | PASS |
| `019f23a0-bdf5-79d1-8d2d-5730a27be2ee` | review worker | 2 | missing | rejected | archived | thread_not_converged; bounded rescue |
| `019f23a4-2d6e-7690-9ae0-78c7a4014151` | review worker | 2 | received | adopted after fix | archived | conditional-go |

Release review budget:

- `max_review_waves`: 2
- `max_parallel_reviewers_per_deliverable`: 2
- `review_receipt_poll_limit`: 3
- Every added review wave requires `add_review_wave_reason`.
- After one cold review and one domain or rebuttal review converge, stop adding reviewers unless `additional_review_wave_reason` explains why the current evidence is insufficient.
- Post-stop bounded goal-readiness audit reason: user challenged whether the long-running three-project goal was actually complete after prior evidence showed unverified natural heartbeat and worker-routing failures. This audit is bounded evidence collection, not open-ended release reviewer expansion.

Stuck review rule:

- No reviewer receipt within the poll limit becomes `thread_not_converged`.
- Cleanup must be `archived` or `cleanup_blocked`.
- A bounded rescue reviewer must be recorded with `rescue_thread_id`.

## Cross-Project Hardening Recheck

Round: `2026-07-05-three-project-hardening-recheck`

Current local validation evidence:

| Project | Command | Result |
|---|---|---|
| `zhijuan-codex-agency-chief-of-staf` | `python3 scripts/validate_activation_contract.py .` | PASS |
| `zhijuan-codex-agency-chief-of-staf` | `python3 scripts/validate_domain_deliverable_contract.py .` | PASS |
| `zhijuan-codex-agency-chief-of-staf` | `bash scripts/check_structure.sh .` | PASS |
| `zhijuan-codex-agency-chief-of-staf` | `bash scripts/quality_gate.sh .` | PASS |
| `zhijuan-codex-agency-chief-of-staf` | `bash scripts/release_smoke.sh .` | PASS |
| `zhijuan-codex-agency-chief-of-staf` | `git diff --check` | PASS |
| `DIR SKILL` | `PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_project.py` | PASS |
| `DIR SKILL` | `git diff --check` | PASS |
| `ad-creative-orchestrator` | `python3 tools/check_gate_fixtures.py` | PASS |
| `ad-creative-orchestrator` | `python3 tools/run_checks.py` | PASS |
| `ad-creative-orchestrator` | `python3 tools/check_distribution.py` | PASS |
| `ad-creative-orchestrator` | `git diff --check` | PASS |

Project-main thread status:

| Thread | Project | Expected receipt | Status |
|---|---|---|---|
| `019f2e3c-93f6-7b40-8616-4945feb79c0d` | `DIR SKILL` | `DIR_CURRENT_STATE_RECEIPT` | received; customer-preview gate patch verified |
| `019f2e3c-9a52-7d70-845a-9db49acbb7bf` | `ad-creative-orchestrator` | `ADCO_CURRENT_STATE_RECEIPT` | blocked then replaced; archived after `send_message_to_thread` returned `no active turn to steer` |
| `019f2e9d-c7a1-7b83-9b24-05117432c52f` | `ad-creative-orchestrator` | `ADCO_PROJECT_COS_CURRENT_RECEIPT` | received; reviewer `019f3037...` marked `thread_not_converged` / archived / rejected evidence; later fork rescue adopted partial ThreadOps receipt fixture as `5101dbf`; legacy dirty worktree kept open |
| `019f2e9c-dafb-7750-ac10-3fdcbf8669b5` | `ad-creative-orchestrator` | `ADCO_DIRTY_WORKTREE_REVIEW_RECEIPT` | received; split adoption recommended; archived |
| `019f2ea1-bb8b-7da2-825e-dd4e496b292d` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_IMPLEMENTATION_RECEIPT` | `thread_not_converged`; systemError; no receipt; archived; temporary worktree no longer present |
| `019f2eab-ff09-7db3-ab78-16ae6dd383b4` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_RESCUE_RECEIPT` | rescue attempted; systemError; no receipt; archived; temporary worktree no longer present |
| `019f2eac-aa97-7ec2-9591-d09c4414bce9` | `ad-creative-orchestrator` | `ADCO_SPLIT_FAILURE_AUDIT_RECEIPT` | read-only rescue attempted; systemError; no receipt; archived |
| `019f3036-2085-75f0-a174-fcbe807c81bf` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_AUTOMATION_AUDIT_RECEIPT` | received; adopted after fixing `cos` heartbeat target and installed-copy drift; archived |
| `019f3036-fe20-7a00-b5eb-14ea205bad24` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_AUTOMATION_AUDIT_RECEIPT` | duplicate dispatch; no receipt; archived/interrupted as `thread_not_converged` |
| `019f3037-5b77-7773-a7c4-0461f2e6f5ce` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_CURRENT_REVIEW_RECEIPT` | no receipt; archived/interrupted as `thread_not_converged`; rejected evidence |
| `019f3048-3210-7f90-85aa-36f220371d68` | `zhijuan-codex-agency-chief-of-staf` | `HEARTBEAT_TRIGGER_AUDIT_RECEIPT` | received; adopted after heartbeat smoke evidence; archived |
| `019f3049-354c-7031-a196-2d315e7f7a9f` | `zhijuan-codex-agency-chief-of-staf` | `HEARTBEAT_SMOKE_RECEIPT` | temporary heartbeat target; produced `COS_BOOT_RECEIPT` and `HEARTBEAT_SMOKE_RECEIPT`; archived |
| `019f3051-957a-76f1-8cd1-658620da147c` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_IMPLEMENTATION_RECEIPT` | invalid receipt; worker reported its isolated worktree was missing, self-created it from main HEAD, and produced 3-file diff; archived and rejected evidence; `f7b3` retained dirty as rejected evidence |
| `019f3058-9213-73b3-9c60-a6284b6b77e9` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_FORK_RESCUE_RECEIPT` | received; single-file ThreadOps receipt failure-path fixture adopted into ADCO main as `5101dbf`; archived; temporary worktree removed by archive |
| `019f3065-dd2a-7df0-beaf-8f9fbc780742` | `ad-creative-orchestrator` | `ADCO_LEGACY_DIRTY_DIFF_DISPOSITION_RECEIPT_CORRECTED` | received after correcting thread id; legacy branch has no commits ahead of main; `adopt_now=none`; disposition `evidence_only_keep_open`; archived |
| `019f306b-5652-7322-9ac2-ecdd651fae2f` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_GOAL_READINESS_AUDIT_RECEIPT` | no receipt; booted COS/no_dispatch despite role-specific reviewer prompt; archived as `thread_not_converged`; rejected evidence; rescued by `019f3075...` |
| `019f3075-a3e9-7660-9813-dc39a8cb0d04` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_GOAL_READINESS_AUDIT_RECEIPT` | received after unarchive/convergence follow-up; did not emit `COS_BOOT_RECEIPT`; verdict `complete_ready=false`; archived; adopted after current-fact correction |
| `019f3084-0e9b-7900-8724-6db0121cf919` | `zhijuan-codex-agency-chief-of-staf` | `SKM_HEARTBEAT_RUN_RECEIPT` | received from isolated Skill-maintainer worker; original receipt self-reported `thread_id: unknown`; controller corrected real thread id, adopted heartbeat run receipt hardening after validation, and archived |
| `019f3090-c370-7952-91a9-ce3ca910e4ee` | `zhijuan-codex-agency-chief-of-staf` | `COS_HEARTBEAT_RUN_RECEIPT` | temporary heartbeat run receipt smoke fired twice, but receipt used root thread `019f2354...` instead of target `019f3090...` and set `target_thread_verified=false`; archived; rejected as progress evidence; adopted only as regression fixture |
| `019f30a0-cf3c-77a1-8681-4609c1927c0f` | `zhijuan-codex-agency-chief-of-staf` | `COS_HEARTBEAT_RUN_RECEIPT` | strict temporary heartbeat smoke emitted `target_thread_verified=true` with matching target id/title/cwd; archived; adopted as positive strict smoke evidence, not as natural `cos` heartbeat completion |
| `019f30ab-0554-7f60-a1ef-588f162a16e3` | `zhijuan-codex-agency-chief-of-staf` | `STALE_WORKTREE_THREAD_REVIEW_RECEIPT` | received; reviewer found missing-cwd worker handling was documented but not hard-blocked; adopted after adding `thread_cwd_missing` rules, audit category, activation fixtures, history fixture, and quality-gate checks; archived |
| `019f30b7-3879-76c2-87ab-76286de8142f` | `zhijuan-codex-agency-chief-of-staf` | `COS_STALE_WORKTREE_INCIDENT_REVIEW_RECEIPT` | receipt marker received but `thread_id` incorrectly copied source/main thread `019f2354...`; archived and rejected as completion evidence; adopted only as hardening input for `invalid_worker_thread_id` |
| `019f30b4-34b3-79c1-9d8c-3b44d90571d0` | `zhijuan-codex-agency-chief-of-staf` | `COS_NATURAL_HEARTBEAT_ACCEPTANCE_REVIEW_RECEIPT` | receipt marker received with correct worker id but verdict `FAIL` before next due; archived and rejected as acceptance evidence; adopted only as hardening input for due-window validation |

Automation receipt:

| Automation | Kind | Status | Target thread | Purpose |
|---|---|---|---|---|
| `cos` | heartbeat | ACTIVE | `019f2354-f00c-7132-90d7-fb6c26ff2ecf` | continue three-project COS hardening every 6 hours with current-state checks, gates/tests, receipt cleanup, and no remote push |

Natural heartbeat acceptance:

- Current check time: `2026-07-05T13:30:48+08:00`
- Latest check time: `2026-07-05T13:30:48+08:00`
- Last config update: `2026-07-05T12:49:24.944+08:00`
- Next six-hour due time: `2026-07-05T18:49:24.944+08:00`
- Acceptance criterion: after the due time, `read_thread 019f2354-f00c-7132-90d7-fb6c26ff2ecf` must show a heartbeat-created turn containing `COS_BOOT_RECEIPT` and `COS_HEARTBEAT_RUN_RECEIPT` with `target_thread_verified=true`, correct target id/title/cwd, due status, dispatch outcome, rescue decision, and next check; otherwise record `thread_not_converged` or `TOOL_BLOCKED` instead of claiming completion.

Automation target audit:

- Previous target `019f17c2-b4f2-7a93-aa9a-a0c124b1545d` was read back as `Weekly Workflow Packaging Audit`; the `cos` heartbeat fired there at `2026-07-05T01:30:51Z` and reported `TOOL_BLOCKED`, which explains why the active COS project thread did not visibly advance.
- Current target is verified as `019f2354-f00c-7132-90d7-fb6c26ff2ecf`, title `[P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000`, cwd `/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf`.
- The live `cos` automation prompt was updated through `codex_app.automation_update` to explicitly require `COS_HEARTBEAT_RUN_RECEIPT` and to carry the expected target id/title/cwd. This reset the six-hour natural due window to `2026-07-05T18:49:24.944+08:00`.
- A bounded temporary heartbeat `cos-heartbeat-smoke-target-temporary` was attached to idle target thread `019f3049-354c-7031-a196-2d315e7f7a9f`; it fired at `2026-07-05T03:20:21Z` and produced both `COS_BOOT_RECEIPT` and `HEARTBEAT_SMOKE_RECEIPT`. The temporary automation was deleted and the thread was archived.
- A later bounded heartbeat run receipt smoke `cos-heartbeat-run-receipt-smoke-temporary` targeted `019f3090-c370-7952-91a9-ce3ca910e4ee`; it fired twice and emitted `COS_HEARTBEAT_RUN_RECEIPT`, but the receipt copied root/source thread `019f2354...` into `target_thread_id` and set `target_thread_verified=false`. The temporary automation was deleted, the target thread was archived, and this is rejected as progress evidence.
- A strict bounded heartbeat run receipt smoke `cos-heartbeat-strict-run-receipt-smoke-temporary` targeted `019f30a0-cf3c-77a1-8681-4609c1927c0f`; with explicit target id/title/cwd in the prompt, it emitted `COS_HEARTBEAT_RUN_RECEIPT` with `target_thread_verified=true`, `dispatch_required=false`, and `dispatch_outcome=not_required_user_forbid_threads`. The temporary automation was deleted and the target thread archived.
- Installed copy drift was resolved with `python3 scripts/install_skill.py --force --agents-routing project --project-root . --json`, followed by `bash scripts/release_smoke.sh .` passing without `SKIP_INSTALLED_COPY_DIFF`.
- Heartbeat run evidence is now hardened with `COS_HEARTBEAT_RUN_RECEIPT` / `HEARTBEAT_RUN_RECEIPT`: automation enablement alone no longer counts as a run; every T4/T5 heartbeat must record target readback, due status, dispatch requirement/outcome, `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED`, stuck/rescue decision, and next due/check.
- `target_thread_verified: false`, `unknown`, or unverified target text is now a hard validation failure for heartbeat run receipts; the regression fixture is `heartbeat-run-target-unverified-invalid`.

Current hard limits:

- No remote push has been performed in this round.
- Creative/storyboard/proposal/copy/story deliverables are not claimed client-ready without `DOMAIN_DELIVERABLE_RECEIPT`.
- The old ADCO project-main thread could not be steered and was replaced by `019f2e9d-c7a1-7b83-9b24-05117432c52f`.
- ADCO split adoption implementation and early bounded rescue attempts failed with systemError before receipts; those failed threads are rejected as evidence.
- New ADCO split-adoption reviewer `019f3037-5b77-7773-a7c4-0461f2e6f5ce` also failed to provide a receipt within budget and was archived/interrupted; it is rejected as evidence.
- ADCO split-adoption retry worker `019f3051-957a-76f1-8cd1-658620da147c` explains the screenshot: it is bound to temporary worktree `/Users/jinjungao/.codex/worktrees/f7b3/ad-creative-orchestrator`, not the main ADCO project. Its receipt says the isolated worktree was missing and that the worker created it from main HEAD, then changed `tools/validate_project.py`, `tools/check_gate_fixtures.py`, and `tools/test_goal_workflow.py`. This is invalid evidence; the thread was archived, the dirty worktree is retained only as rejected evidence, and the failure mode is now covered by `missing-cwd-worker-self-recreated-invalid`.
- ADCO split-adoption fork rescue worker `019f3058-9213-73b3-9c60-a6284b6b77e9` produced a valid receipt. The bounded ThreadOps receipt fixture was adopted into ADCO main as commit `5101dbf Harden ThreadOps receipt gate fixtures`, with `python3 tools/check_gate_fixtures.py`, `python3 tools/run_checks.py`, `python3 tools/check_distribution.py`, and `git diff --check` all passing; its temporary worktree `f436` was removed by thread archive.
- Archived temporary ADCO worker worktrees such as `d6f2`, `0e1f`, and `f436` can show "current working directory missing" when reopened in Codex; the ADCO main path `/Users/jinjungao/work/ad-creative-orchestrator` and retained legacy dirty evidence worktree remain verified separately.
- Missing worker cwd/worktree is now a hard failure mode: `thread_cwd_missing` must be recorded with `thread_not_converged`, `adoption_status: rejected_evidence`, and `cleanup_status: archived | cleanup_blocked`; a worker that self-creates or re-checkouts a missing worktree is also invalid and cannot produce adopted evidence.
- ADCO legacy dirty disposition reviewer `019f3065-dd2a-7df0-beaf-8f9fbc780742` concluded `adopt_now=none`: the legacy branch has no commits ahead of main, main is ahead by 3 commits, and the remaining dirty diff is `evidence_only_keep_open` rather than safe migration material. The first receipt had a self-id mismatch and was corrected before adoption as evidence.
- Goal-readiness reviewer `019f306b-5652-7322-9ac2-ecdd651fae2f` did not produce `THREE_PROJECT_GOAL_READINESS_AUDIT_RECEIPT`; it emitted COS boot/no-dispatch behavior instead of executing the review worker task. This is now covered by `COS_WORKER_BYPASS` rules and activation fixtures, but the original thread is rejected evidence.
- Bounded rescue reviewer `019f3075-a3e9-7660-9813-dc39a8cb0d04` was dispatched after updating the project routing block and did not emit `COS_BOOT_RECEIPT`, confirming the bypass direction. It was initially interrupted by coordinator error while active, then unarchived and resumed; it produced `THREE_PROJECT_GOAL_READINESS_AUDIT_RECEIPT` with `complete_ready=false` and was archived.
- Skill-maintainer worker `019f3084-0e9b-7900-8724-6db0121cf919` added heartbeat run receipt hardening; because its own receipt used `thread_id: unknown`, adoption uses controller readback for the real thread id plus main-worktree validation rather than the self-id claim.
- Temporary heartbeat run receipt smoke target `019f3090-c370-7952-91a9-ce3ca910e4ee` produced the required receipt marker but not valid target readback; it is rejected as evidence and now covered by `heartbeat-run-target-unverified-invalid`.
- Strict heartbeat run receipt smoke target `019f30a0-cf3c-77a1-8681-4609c1927c0f` produced valid target readback when the prompt carried explicit target metadata; this is accepted as positive smoke evidence but does not replace natural `cos` heartbeat acceptance.
- Stale-worktree incident reviewer `019f30b7-3879-76c2-87ab-76286de8142f` produced the expected receipt marker but filled `thread_id` with the source/main thread ID, so it is invalid worker receipt evidence. The failure mode is now covered by `role-worker-bypass-source-thread-id-invalid` and release validator status `invalid_worker_thread_id`.
- Natural heartbeat acceptance reviewer `019f30b4-34b3-79c1-9d8c-3b44d90571d0` produced the expected receipt marker with the correct worker id but returned `FAIL` before the configured next due time. The failure mode is now covered by `natural-heartbeat-before-due-fail-invalid`; before due, the only valid acceptance verdict is `NOT_DUE`.
- After archival, failed temporary worktree paths `d6f2` and `0e1f` were no longer present, so no diff from those failed paths is claimed.
- Legacy dirty worktree `/Users/jinjungao/.codex/worktrees/adco-skill-hardening/ad-creative-orchestrator` still exists and remains the only retained dirty-worktree evidence.
- The heartbeat smoke proves explicit Skill invocation can fire through Codex heartbeat and produce `COS_BOOT_RECEIPT`, but as of `2026-07-05T13:30:48+08:00` the long-running six-hour `cos` automation is not due until `2026-07-05T18:49:24.944+08:00`, so natural-fire completion remains unproven rather than failed.
- Residual-process scan found no lingering gate/test/playwright/vite/npm worker processes from validation; no `adco-check-*` temp dirs remained; cache dirs were removed. Multiple stale `xcodebuildmcp` MCP server pairs were sleeping, so older duplicate pairs were terminated and the newest pair was left running.
- Transient invalid placeholder dispatch receipts with `thread_id: "pending"` or `thread_id: "dispatch_pending"` were emitted during continuations and are rejected as evidence; only real `thread_id` rows or non-empty `pending_worktree_id` rows are counted.
