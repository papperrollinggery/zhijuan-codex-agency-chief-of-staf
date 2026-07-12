# Shared helper bootstrap for release gates. This file must be sourced by Bash.

if [[ ! -x /usr/bin/stat ]]; then
  echo "trusted gate bootstrap failed: /usr/bin/stat is unavailable" >&2
  return 1
fi

_agency_gate_helper_metadata() {
  local candidate="$1"
  local metadata mode
  metadata="$(/usr/bin/stat -f '%OLp|%u' -- "$candidate" 2>/dev/null)" || metadata=""
  mode="${metadata%%|*}"
  case "$mode" in
    ''|*[!0-7]*) ;;
    *) printf '%s\n' "$metadata"; return 0 ;;
  esac
  /usr/bin/stat -L -c '%a|%u' -- "$candidate"
}

_agency_gate_candidate_is_safe() {
  local candidate="$1"
  local metadata mode owner mode_value

  case "$candidate" in
    /usr/bin/*|/bin/*|/usr/local/bin/*|/opt/homebrew/bin/*|/Library/Frameworks/Python.framework/*|/opt/hostedtoolcache/Python/*)
      ;;
    *)
      return 1
      ;;
  esac
  case "$candidate" in
    *$'\n'*|*$'\r'*|*:*|*/../*|*/./*|*//*)
      return 1
      ;;
  esac
  [[ -f "$candidate" && -x "$candidate" ]] || return 1
  metadata="$(_agency_gate_helper_metadata "$candidate")" || return 1
  mode="${metadata%%|*}"
  owner="${metadata#*|}"
  case "$mode" in
    ''|*[!0-7]*) return 1 ;;
  esac
  case "$owner" in
    ''|*[!0-9]*) return 1 ;;
  esac
  mode_value=$((8#$mode))
  (( (mode_value & 8#022) == 0 )) || return 1
  [[ "$owner" == "0" || "$owner" == "$EUID" ]] || return 1
}

_agency_gate_resolve() {
  local label="$1"
  shift
  local candidate
  for candidate in "$@"; do
    if _agency_gate_candidate_is_safe "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "trusted gate bootstrap failed: no safe fixed-path $label helper" >&2
  return 1
}

_agency_gate_resolve_python() {
  local candidate
  for candidate in "$@"; do
    if _agency_gate_candidate_is_safe "$candidate" \
      && "$candidate" -E -s -S -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "trusted gate bootstrap failed: no safe fixed-path Python 3.10+ helper" >&2
  return 1
}

_agency_python_candidates=()
case "${pythonLocation:-}" in
  /opt/hostedtoolcache/Python/*)
    _agency_python_candidates+=("${pythonLocation}/bin/python3")
    ;;
esac
_agency_python_candidates+=(
  /opt/homebrew/bin/python3
  /usr/local/bin/python3
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3
  /usr/bin/python3
)

TRUSTED_PYTHON="$(_agency_gate_resolve_python "${_agency_python_candidates[@]}")"
TRUSTED_BASH="$(_agency_gate_resolve bash /bin/bash /usr/bin/bash)"
TRUSTED_GIT="$(_agency_gate_resolve git /usr/bin/git /bin/git /usr/local/bin/git /opt/homebrew/bin/git)"
TRUSTED_MKTEMP="$(_agency_gate_resolve mktemp /usr/bin/mktemp /bin/mktemp)"
TRUSTED_RM="$(_agency_gate_resolve rm /bin/rm /usr/bin/rm)"

TRUSTED_GATE_PATH="${TRUSTED_PYTHON%/*}:${TRUSTED_BASH%/*}:${TRUSTED_GIT%/*}:${TRUSTED_MKTEMP%/*}:${TRUSTED_RM%/*}"
readonly TRUSTED_PYTHON TRUSTED_BASH TRUSTED_GIT TRUSTED_MKTEMP TRUSTED_RM TRUSTED_GATE_PATH
export PATH="$TRUSTED_GATE_PATH"

unset _agency_python_candidates
unset -f _agency_gate_helper_metadata _agency_gate_candidate_is_safe _agency_gate_resolve _agency_gate_resolve_python
