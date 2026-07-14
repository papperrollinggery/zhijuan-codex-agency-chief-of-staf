#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"
SOURCE_ROOT="$PWD"

python3 scripts/validate_package.py .

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agency-release-smoke.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

if test -f "$SOURCE_ROOT/AGENTS.md"; then
  source_agents_before="FILE:$(shasum -a 256 "$SOURCE_ROOT/AGENTS.md" | awk '{print $1}')"
elif test -e "$SOURCE_ROOT/AGENTS.md" || test -L "$SOURCE_ROOT/AGENTS.md"; then
  source_agents_before="OTHER:$(stat -f '%HT:%z:%m' "$SOURCE_ROOT/AGENTS.md")"
else
  source_agents_before="ABSENT"
fi

python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --json >"$TMP_ROOT/install.json"
python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --dry-run --json >"$TMP_ROOT/dry-run.json"

PROFILE_NAMES=(codebase-researcher technical-architect developer reviewer test-debugger)
PROFILE_SOURCES=(
  "$SOURCE_ROOT"
  "$TMP_ROOT/skills/agency-chief-of-staff"
  "$TMP_ROOT/skills/zhijuan-codex-agency-chief-of-staf"
)
PROFILE_LABELS=(source canonical legacy)

for index in 0 1 2; do
  label="${PROFILE_LABELS[$index]}"
  profile_source="${PROFILE_SOURCES[$index]}"
  project="$TMP_ROOT/project-$label"
  isolated_home="$TMP_ROOT/home-$label"
  mkdir -p "$project"
  mkdir -p "$isolated_home/.codex"
  printf 'USER SENTINEL\n' >"$project/AGENTS.md"
  printf 'GLOBAL SENTINEL\n' >"$isolated_home/.codex/AGENTS.md"
  agents_before="$(shasum -a 256 "$project/AGENTS.md" | awk '{print $1}')"
  global_agents_before="$(shasum -a 256 "$isolated_home/.codex/AGENTS.md" | awk '{print $1}')"
  HOME="$isolated_home" python3 "$profile_source/scripts/install_agent_profiles.py" \
    --target-root "$project/.codex/agents" \
    --json >"$TMP_ROOT/agent-install-$label.json"
  agents_after="$(shasum -a 256 "$project/AGENTS.md" | awk '{print $1}')"
  global_agents_after="$(shasum -a 256 "$isolated_home/.codex/AGENTS.md" | awk '{print $1}')"
  test "$agents_before" = "$agents_after"
  test "$global_agents_before" = "$global_agents_after"
  for profile in "${PROFILE_NAMES[@]}"; do
    cmp \
      "$profile_source/assets/codex_agents/$profile.toml" \
      "$project/.codex/agents/$profile.toml"
  done
  python3 "$profile_source/scripts/run_profile_compat.py" --help \
    >"$TMP_ROOT/profile-compat-help-$label.txt"
  grep -Fq "Run a bounded read-only profile" "$TMP_ROOT/profile-compat-help-$label.txt"
done

if test -f "$SOURCE_ROOT/AGENTS.md"; then
  source_agents_after="FILE:$(shasum -a 256 "$SOURCE_ROOT/AGENTS.md" | awk '{print $1}')"
elif test -e "$SOURCE_ROOT/AGENTS.md" || test -L "$SOURCE_ROOT/AGENTS.md"; then
  source_agents_after="OTHER:$(stat -f '%HT:%z:%m' "$SOURCE_ROOT/AGENTS.md")"
else
  source_agents_after="ABSENT"
fi
test "$source_agents_before" = "$source_agents_after"

python3 - "$TMP_ROOT/install.json" "$TMP_ROOT/dry-run.json" <<'PY'
import json
import sys
from pathlib import Path

install = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dry_run = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if install["status"] != "installed":
    raise SystemExit(f"unexpected install status: {install['status']}")
if dry_run["status"] != "already-installed":
    raise SystemExit(f"unexpected dry-run status: {dry_run['status']}")
if install.get("agents_md_touched") is not False:
    raise SystemExit("installer did not prove AGENTS.md remained untouched")
if install["manifests"] != dry_run["manifests"]:
    raise SystemExit("runtime pair manifest drift after install")
if set(install["targets"]) != {"agency-chief-of-staff", "zhijuan-codex-agency-chief-of-staf"}:
    raise SystemExit("installer did not produce the canonical and legacy pair")
PY

python3 - \
  "$TMP_ROOT/agent-install-source.json" \
  "$TMP_ROOT/agent-install-canonical.json" \
  "$TMP_ROOT/agent-install-legacy.json" <<'PY'
import json
import sys
from pathlib import Path

for receipt in map(Path, sys.argv[1:]):
    result = json.loads(receipt.read_text(encoding="utf-8"))
    if result["status"] != "installed":
        raise SystemExit(f"unexpected agent install status: {result['status']}")
    if len(result["profiles"]) != 5:
        raise SystemExit("agent installer did not produce five bounded profiles")
    if result.get("agents_md_touched") is not False or result.get("self_skill_bindings") is not False:
        raise SystemExit("agent installer isolation contract failed")
PY

PROFILE_COMPAT_INSTALLED_ROOT="$TMP_ROOT/skills" \
  python3 -m unittest \
  tests.test_profile_compat.ProfileCompatibilityTests.test_installed_bundles_execute_full_receipt_flow

echo "Release smoke passed: canonical/legacy bundles, opt-in profiles, and permanent read-only compatibility runner match source; model behavior not claimed."
