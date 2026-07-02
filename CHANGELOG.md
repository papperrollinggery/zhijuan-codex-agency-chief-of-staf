# Changelog

## Unreleased

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
