#!/bin/bash -p
case "$-" in
  *p*) ;;
  *) echo "quality gate requires /bin/bash -p" >&2; exit 1 ;;
esac
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "$SCRIPT_PATH" in
  /*) ;;
  *) SCRIPT_PATH="$PWD/$SCRIPT_PATH" ;;
esac
if [[ -L "$SCRIPT_PATH" ]]; then
  echo "quality gate must not be invoked through a symlink" >&2
  exit 1
fi
SCRIPT_DIR="${SCRIPT_PATH%/*}"
SCRIPT_DIR="$(cd -P -- "$SCRIPT_DIR" && pwd)"
# shellcheck source=trusted_gate_helpers.sh
source "$SCRIPT_DIR/trusted_gate_helpers.sh"

ROOT="${1:-.}"
cd "$ROOT"

"$TRUSTED_PYTHON" -E -s -S scripts/validate_package.py --git-executable "$TRUSTED_GIT" .
"$TRUSTED_PYTHON" -E -s -S -m py_compile \
  scripts/install_skill.py \
  scripts/validate_package.py \
  scripts/validate_behavior_cases.py \
  scripts/run_model_evals.py \
  scripts/audit_historical_threads.py
echo "Structure check passed."

"$TRUSTED_PYTHON" -E -s -S scripts/validate_behavior_cases.py evals/behavior_cases.json
"$TRUSTED_PYTHON" -E -s -S -m unittest discover -s tests -p 'test_*.py'
"$TRUSTED_BASH" -p scripts/release_smoke.sh .
"$TRUSTED_GIT" diff --check

echo "Offline package/contract quality gate passed. This gate does not claim model or ThreadOps behavior."
