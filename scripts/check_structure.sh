#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

python3 scripts/validate_package.py .
python3 -m py_compile \
  scripts/install_skill.py \
  scripts/install_agent_profiles.py \
  scripts/validate_agent_profiles.py \
  scripts/validate_package.py \
  scripts/validate_behavior_cases.py \
  scripts/run_model_evals.py \
  scripts/audit_historical_threads.py

echo "Structure check passed."
