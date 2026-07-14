# Changelog

## Unreleased

## v0.2.0-rc.1 - 2026-07-14

- Published as a host-scoped release candidate: the current Codex Desktop path is verified, while portable unattended, cross-host, and stable-release behavior remains explicitly unverified pending isolated dedicated-credential model smoke.
- Aligned startup ordering with host Skill rules: one fixed explanation-only Skill usage notice may precede takeover, while task progress and task actions remain fail-closed.
- Made the natural-language takeover line the cross-host startup evidence and kept the hidden receipt optional, because some hosts strip HTML comments from persisted rollouts.

- Added deterministic role-to-model-class routing for the five bounded profiles, with economy/balanced/quality budgets, current-host catalog resolution, same-provider and `fork_turns=none` guards, truthful planned/accepted/confirmed states, root-owned overflow, and a provider-neutral optional advisor slot.
- Reworked the user-facing interaction into compact takeover, progress, decision, and delivery states; backstage markers remain machine-verifiable but render invisibly, while ordinary status stays in plain human language.
- Added OpenAI Visualizations routing for stage, decision, impact, evidence, numeric-trend, and current-image review; shipped compact responsive stage and decision templates, strict no-fake-curve/no-fake-preview fallbacks, light/dark CSS contract checks, and regression gates against backstage terms, hover flicker, animation, external resources, and network-capable markup.
- Added a permanent `cli-profile-compat` path for read-only professional roles when the host cannot select named custom agents, with an independent standalone CLI session, explicit context-injection disclosure, strict managed/restricted/read sandbox verification, immutable-input and tool-output binding, recursion-disabled execution, bounded timeout, AGENTS invariance, and automatic archive verification; cold-context isolation remains explicitly unverified.
- Added a fixed system-only tool `PATH` plus mandatory exit-0 `git diff` call/output receipts for reviewer and codebase-researcher compatibility runs; exit status is read only from the bound wrapper's structured top-level field, so missing `git` or misleading stdout cannot be reported as verified review evidence.
- Kept native named custom agents as an optional enhancement instead of a release dependency; write-capable developer work remains in the main outcome-owner session or an isolated worktree.
- Hardened reviewer terminal prompts and receipts to require an exact five-line schema and reject duplicate fields, extra lines, reordered fields, translated verdict decorations, and `PASS_*` prefix tricks.
- Added five bounded project custom-agent profiles plus distributable templates for codebase research, architecture, scoped development, independent review, and on-demand test diagnosis.
- Added an explicit opt-in agent-profile installer with conflict-safe replacement and `skills.config` domain-skill bindings; default Skill installation still writes no Agent or `AGENTS.md` configuration.
- Replaced the blanket worker-packet `$slug` ban with an exact self-recursion denylist, allowing selected domain Skills while blocking both Chief-of-Staff entrypoints.
- Added a software-development routing matrix, profile/template/schema validation, install tests, and isolation checks for project-level professional context.
- Made synthetic native-receipt tests use their own clean Git fixture so the offline quality gate remains runnable while legitimate source changes are uncommitted.
- Rewrote the 1,560-line role-and-receipt framework into a roughly 200-line outcome-owner workflow: goal, research, minimal plan, execution, verification, independent review, repair, and delivery.
- Made the main task a valid execution surface and limited delegation to work that benefits from parallelism, isolation, or an independent view.
- Replaced the fixed 16-role organization with dynamic research/execution/review subagent responsibilities and host-selected current models.
- Removed every `AGENTS.md` routing snippet, installer flag, template, and validation dependency; the installer now guarantees `agents_md_touched: false`.
- Replaced full-repository copying with a nine-file runtime allowlist and staged replacement with rollback.
- Replaced grep-heavy self-referential release gates with explicit package/contract checks, installer unit tests, and a real `codex exec` model-smoke runner.
- Split specialized guidance into four short on-demand references for real threads, delivery review, long-running work, and historical audits.
- Marked v0.1.x validation receipts as historical evidence rather than current model-behavior proof.
- Hardened the installer against source/target symlinks and post-commit backup-cleanup failures, with an independent runtime allowlist in the package validator.
- Hardened model smoke against unsafe case ids, artifact traversal, dangerous sandboxes, environment-secret inheritance, plugin/app contamination, partial-run overclaims, incomplete cold-review events, extra dirty files, and exact auth-value output leakage.
- Made model smoke require an explicit auth path and risk acknowledgement; documented that same-user temp auth is not a secret boundary and untrusted diffs need a disposable user/container plus dedicated low-privilege credentials.

## v0.1.7 - 2026-07-06

- Clarified that real customer-project injection, DIR live-user acceptance, and ADCO client/PPT-ready/domain acceptance are post-release dogfood boundaries, while customer-facing client-ready claims still require `DOMAIN_DELIVERABLE_RECEIPT`.
- Added project-state convergence receipts and field-level `release_receipt` gates so release status claims must match explicit receipt fields.
- Clarified README release status wording so the package is described as local-hardened release-candidate quality instead of over-claiming open-source-ready publication.
- Added a required Chinese `THREAD_DISPATCH_RECEIPT` dispatch summary card so worker dispatches are readable before any machine YAML appears.
- Added Chinese-first compact visible output rules so light `COS_BOOT_RECEIPT` responses stay readable while machine receipts remain available for dispatch, heartbeat, and release evidence.
- Added the same Chinese-first output rule to the project/global `AGENTS.md` routing shim and validation gates so cross-project COS starts do not regress to English-heavy receipts.
- Added explicit installer support for project/global `AGENTS.md` routing shims without making the default install silently modify user rules.
- Hardened the dispatch handshake so `thread_dispatch_decision: dispatch` must immediately converge to `THREAD_DISPATCH_RECEIPT` or `TOOL_BLOCKED`.
- Added bounded worker receipt polling so dispatched workers that do not return receipts are marked `thread_not_converged` and rescued instead of passively waited on.
- Blocked the live-test failure mode where COS falls back to current-worktree implementation after both the original worker and rescue worker fail to return receipts.
- Documented that Codex automation heartbeats execute their configured prompt and only start this Skill when the prompt or AGENTS routing explicitly invokes it.
- Added poll pacing and startup grace so complex workers are not killed by three rapid readbacks before they have time to produce a receipt.
- Added domain-deliverable gates and `DOMAIN_DELIVERABLE_RECEIPT` validation so creative, storyboard, proposal, research, copy, story, execution, and planning work cannot be called client-ready from process receipts alone.
- Tightened domain-deliverable validation so `verdict: PASS` requires passing domain gates plus `cold_reviewed_and_domain_reviewed`; all-FAIL gate receipts are now blocked.
- Tightened activation validation so UUID-only dispatch self-reports are invalid while legitimate `pending_worktree_id` + `dispatch_pending` receipts remain valid.
- Added release convergence gates with `max_review_waves`, `max_parallel_reviewers_per_deliverable`, required `add_review_wave_reason`, and stuck-review bounded rescue validation.
- Hardened worker receipt identity so role-specific worker packets must include the worker's own Codex `thread_id`; receipts that copy `source_thread_id` or the main thread id are now rejected as `invalid_worker_thread_id`.
- Hardened worker dispatch prompts so the Chief-of-Staff must inject the worker's actual `thread_id` into the worker prompt and record `worker_prompt_identity_contract: included`; dispatch receipts missing this proof are blocked.
- Hardened natural heartbeat acceptance so reviewers must return `NOT_DUE` before `next_natural_due_at_local` instead of misclassifying user-triggered in-progress turns as heartbeat failures.
- Hardened missing-cwd worker handling so a worker cannot self-create or re-checkout its missing isolated worktree and then claim adopted execution evidence.
- Added `validation/release_receipt.json` plus `scripts/validate_release_receipt.py` so dispatch, adoption/rejection, cleanup, and review verdicts converge into one machine-readable release artifact.
- Expanded implicit routing metadata for release readiness, public repository publishing, reusable Skill hardening, and multi-file reliability validation.
- Tightened black-box complex prompts so realistic complex tasks must require dispatch-or-TOOL_BLOCKED without leaking thread/receipt wording.
- Added black-box complex-task activation prompts that avoid `$skill`, COS, thread, receipt, and cleanup giveaway terms.
- Added activation fixture coverage for COS main-thread over-execution so direct implementation claims are not accepted as routed worker evidence.
- Clarified that Skill descriptions improve selection probability, while project `AGENTS.md` routing is required to force default Chief-of-Staff behavior.
- Added a local historical-thread audit script and fixture to detect prior Chief-of-Staff activation, dispatch, pending worktree, non-converged review, title/readback, and cross-project routing failure modes.
- Documented the historical evidence hierarchy so old thread titles, worker self-report, `pendingWorktreeId`, and `thread_not_converged` cannot be mistaken for completion evidence.

## v0.1.6 - 2026-07-04

- Hardened activation so explicit or routed Chief-of-Staff runs must emit `COS_BOOT_RECEIPT` before doing task work.
- Re-enabled implicit invocation for natural-language triggers such as 幕僚长, 完整团队, true Codex Threads, receipt, cleanup, Plan/Goal orchestration, and stuck-thread rescue.
- Added activation regression prompts, AGENTS routing snippet, boot/dispatch receipt templates, and quality-gate validation for dispatch-or-TOOL_BLOCKED behavior.

## v0.1.5 - 2026-07-03

- Clarified post-release validation evidence so historical release-candidate receipts are not confused with current release status.
- Added quality-gate checks that block stale "public release still required" wording after a release is complete.
- Expanded CI coverage to Python 3.10, 3.11, and 3.12 to exercise the TOML compatibility path.

## v0.1.4 - 2026-07-03

- Added a required Agency-flow pilot receipt and validator so release/council receipts cannot substitute for SKS/AGS/DEV/REV worker receipts.
- Added a live bounded-rescue Agency pilot receipt covering SKS, AGS, DEV, REV, rejected non-converged DEV, adoption/rejection, and cleanup.
- Corrected the Agency pilot receipt to adopt a post-fix REV2 PASS receipt and record the earlier pre-fix REV FAIL as rejected evidence.
- Added COS startup and dispatcher title discipline: threads self-title when possible, dispatcher fallback applies `set_thread_title`, and release evidence must use thread metadata rather than worker self-report alone.
- Added worker-role isolation rules so execution/review workers do not load or impersonate the full COS Skill.
- Added a TOML compatibility loader so release helper scripts do not require Python 3.11 `tomllib`.
- Added `scripts/install_skill.py` for reproducible user-skill installation.
- Added `scripts/quality_gate.sh` as the open-source release gate.
- Added `scripts/release_smoke.sh` and `scripts/pilot_harness.py`.
- Added bounded rescue and `thread_not_converged` rules to prevent stuck worker threads from being counted as success.
- Added strict Codex Thread vs subagent boundary rules and TOOL_BLOCKED behavior.
- Added live ThreadOps validation notes and required them in the package quality gate.
- Added CLI help, filtering, limits, and JSON output to discovery and scoring scripts.
- Added README, license, contribution, security, and realistic prompt examples for public sharing.
