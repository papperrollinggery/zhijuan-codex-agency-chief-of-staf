# Changelog

## Unreleased

- Added `scripts/install_skill.py` for reproducible user-skill installation.
- Added `scripts/quality_gate.sh` as the open-source release gate.
- Added `scripts/release_smoke.sh` and `scripts/pilot_harness.py`.
- Added bounded rescue and `thread_not_converged` rules to prevent stuck worker threads from being counted as success.
- Added strict Codex Thread vs subagent boundary rules and TOOL_BLOCKED behavior.
- Added live ThreadOps validation notes and required them in the package quality gate.
- Added CLI help, filtering, limits, and JSON output to discovery and scoring scripts.
- Added README, license, contribution, security, and realistic prompt examples for public sharing.
