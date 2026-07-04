# Changelog

## Unreleased

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
