#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

python3 scripts/validate_package.py .
PYCACHE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agency-chief-pycache.XXXXXX")"
trap 'rm -rf "$PYCACHE_ROOT"' EXIT
PYTHONPYCACHEPREFIX="$PYCACHE_ROOT" python3 -m py_compile \
  scripts/install_skill.py \
  scripts/install_agent_profiles.py \
  scripts/validate_agent_profiles.py \
  scripts/validate_package.py \
  scripts/validate_behavior_cases.py \
  scripts/run_model_evals.py \
  scripts/audit_historical_threads.py \
  scripts/resolve_role_route.py \
  scripts/configure_native_routing.py \
  scripts/inspect_codex_models.py \
  scripts/verify_native_task_receipt.py \
  scripts/verify_role_route_receipt.py \
  scripts/validate_visualization_data.py \
  scripts/render_visualization.py

echo "Structure check passed."
