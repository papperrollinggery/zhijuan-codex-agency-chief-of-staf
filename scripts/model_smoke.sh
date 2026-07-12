#!/bin/bash -p
case "$-" in
  *p*) ;;
  *) echo "model smoke requires /bin/bash -p" >&2; exit 1 ;;
esac
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "$SCRIPT_PATH" in
  /*) ;;
  *) SCRIPT_PATH="$PWD/$SCRIPT_PATH" ;;
esac
if [[ -L "$SCRIPT_PATH" ]]; then
  echo "model smoke must not be invoked through a symlink" >&2
  exit 1
fi
SCRIPT_DIR="${SCRIPT_PATH%/*}"
SCRIPT_DIR="$(cd -P -- "$SCRIPT_DIR" && pwd)"
# shellcheck source=trusted_gate_helpers.sh
source "$SCRIPT_DIR/trusted_gate_helpers.sh"

exec "$TRUSTED_PYTHON" -E -s -S "$SCRIPT_DIR/run_model_evals.py" "$@"
