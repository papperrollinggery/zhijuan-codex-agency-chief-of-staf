#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

python3 scripts/validate_package.py .

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agency-release-smoke.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --json >"$TMP_ROOT/install.json"
python3 scripts/install_skill.py --target-root "$TMP_ROOT/skills" --dry-run --json >"$TMP_ROOT/dry-run.json"

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

echo "Release smoke passed: canonical and legacy bundles match source; model behavior not claimed."
