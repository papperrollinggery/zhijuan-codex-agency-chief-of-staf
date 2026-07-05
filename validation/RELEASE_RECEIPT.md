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
| `019f2e9d-c7a1-7b83-9b24-05117432c52f` | `ad-creative-orchestrator` | `ADCO_PROJECT_COS_CURRENT_RECEIPT` | received; reviewer `019f3037...` marked `thread_not_converged` / archived / rejected evidence; split adoption still blocked; legacy dirty worktree kept open |
| `019f2e9c-dafb-7750-ac10-3fdcbf8669b5` | `ad-creative-orchestrator` | `ADCO_DIRTY_WORKTREE_REVIEW_RECEIPT` | received; split adoption recommended; archived |
| `019f2ea1-bb8b-7da2-825e-dd4e496b292d` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_IMPLEMENTATION_RECEIPT` | `thread_not_converged`; systemError; no receipt; archived; temporary worktree no longer present |
| `019f2eab-ff09-7db3-ab78-16ae6dd383b4` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_RESCUE_RECEIPT` | rescue attempted; systemError; no receipt; archived; temporary worktree no longer present |
| `019f2eac-aa97-7ec2-9591-d09c4414bce9` | `ad-creative-orchestrator` | `ADCO_SPLIT_FAILURE_AUDIT_RECEIPT` | read-only rescue attempted; systemError; no receipt; archived |
| `019f3036-2085-75f0-a174-fcbe807c81bf` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_AUTOMATION_AUDIT_RECEIPT` | received; adopted after fixing `cos` heartbeat target and installed-copy drift; archived |
| `019f3036-fe20-7a00-b5eb-14ea205bad24` | `zhijuan-codex-agency-chief-of-staf` | `THREE_PROJECT_AUTOMATION_AUDIT_RECEIPT` | duplicate dispatch; no receipt; archived/interrupted as `thread_not_converged` |
| `019f3037-5b77-7773-a7c4-0461f2e6f5ce` | `ad-creative-orchestrator` | `ADCO_SPLIT_ADOPTION_CURRENT_REVIEW_RECEIPT` | no receipt; archived/interrupted as `thread_not_converged`; rejected evidence |
| `019f3048-3210-7f90-85aa-36f220371d68` | `zhijuan-codex-agency-chief-of-staf` | `HEARTBEAT_TRIGGER_AUDIT_RECEIPT` | received; adopted after heartbeat smoke evidence; archived |
| `019f3049-354c-7031-a196-2d315e7f7a9f` | `zhijuan-codex-agency-chief-of-staf` | `HEARTBEAT_SMOKE_RECEIPT` | temporary heartbeat target; produced `COS_BOOT_RECEIPT` and `HEARTBEAT_SMOKE_RECEIPT`; archived |

Automation receipt:

| Automation | Kind | Status | Target thread | Purpose |
|---|---|---|---|---|
| `cos` | heartbeat | ACTIVE | `019f2354-f00c-7132-90d7-fb6c26ff2ecf` | continue three-project COS hardening every 6 hours with current-state checks, gates/tests, receipt cleanup, and no remote push |

Automation target audit:

- Previous target `019f17c2-b4f2-7a93-aa9a-a0c124b1545d` was read back as `Weekly Workflow Packaging Audit`; the `cos` heartbeat fired there at `2026-07-05T01:30:51Z` and reported `TOOL_BLOCKED`, which explains why the active COS project thread did not visibly advance.
- Current target is verified as `019f2354-f00c-7132-90d7-fb6c26ff2ecf`, title `[P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000`, cwd `/Users/jinjungao/work/zhijuan-codex-agency-chief-of-staf`.
- A bounded temporary heartbeat `cos-heartbeat-smoke-target-temporary` was attached to idle target thread `019f3049-354c-7031-a196-2d315e7f7a9f`; it fired at `2026-07-05T03:20:21Z` and produced both `COS_BOOT_RECEIPT` and `HEARTBEAT_SMOKE_RECEIPT`. The temporary automation was deleted and the thread was archived.
- Installed copy drift was resolved with `python3 scripts/install_skill.py --force --agents-routing project --project-root . --json`, followed by `bash scripts/release_smoke.sh .` passing without `SKIP_INSTALLED_COPY_DIFF`.

Current hard limits:

- No remote push has been performed in this round.
- Creative/storyboard/proposal/copy/story deliverables are not claimed client-ready without `DOMAIN_DELIVERABLE_RECEIPT`.
- The old ADCO project-main thread could not be steered and was replaced by `019f2e9d-c7a1-7b83-9b24-05117432c52f`.
- ADCO split adoption implementation and bounded rescue both failed with systemError before receipts; no split adoption into main is claimed.
- New ADCO split-adoption reviewer `019f3037-5b77-7773-a7c4-0461f2e6f5ce` also failed to provide a receipt within budget and was archived/interrupted; it is rejected as evidence.
- After archival, failed temporary worktree paths `d6f2` and `0e1f` were no longer present, so no unreceived split-adoption diff is claimed.
- Legacy dirty worktree `/Users/jinjungao/.codex/worktrees/adco-skill-hardening/ad-creative-orchestrator` still exists and remains the only retained dirty-worktree evidence.
- The heartbeat smoke proves explicit Skill invocation can fire through Codex heartbeat and produce `COS_BOOT_RECEIPT`, but the long-running six-hour `cos` automation has not yet naturally fired in active thread `019f2354-f00c-7132-90d7-fb6c26ff2ecf` after target correction.
- A transient invalid placeholder dispatch receipt with `thread_id: "pending"` was emitted during the continuation and is rejected as evidence; only the later real `019f3048...` dispatch receipt is counted.
