#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

QUALITY_PYCACHE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agency-chief-quality-pycache.XXXXXX")"
trap 'rm -rf "$QUALITY_PYCACHE_ROOT"' EXIT
export PYTHONPYCACHEPREFIX="$QUALITY_PYCACHE_ROOT"

bash scripts/check_structure.sh .
python3 scripts/validate_behavior_cases.py evals/behavior_cases.json
python3 -m unittest discover -s tests -p 'test_*.py'
bash scripts/release_smoke.sh .
git diff --check

echo "Offline package/contract quality gate passed. This gate does not claim model or ThreadOps behavior."
