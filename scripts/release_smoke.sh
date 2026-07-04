#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

bash scripts/check_structure.sh .

python3 - <<'PY'
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from toml_compat import loads as toml_loads

for path in sorted(Path("scripts").glob("*.py")):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

agent_roots = [Path("assets/codex_agents")]
if Path(".git").exists() or Path(".codex").exists():
    agent_roots.append(Path(".codex/agents"))

for root in agent_roots:
    if not root.exists():
        raise SystemExit(f"MISSING: {root}")
    files = sorted(root.glob("*.toml"))
    if len(files) != 16:
        raise SystemExit(f"EXPECTED 16 agents in {root}, found {len(files)}")
    for path in files:
        data = toml_loads(path.read_text(encoding="utf-8"))
        missing = [
            key
            for key in ("name", "description", "developer_instructions")
            if not data.get(key)
        ]
        if missing:
            raise SystemExit(f"{path} missing: {', '.join(missing)}")

print("OK: python scripts and agent TOML parsed")
PY

python3 scripts/validate_thread_name.py \
  "[P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000"
python3 scripts/validate_task_graph.py assets/TASK_GRAPH_TEMPLATE.md
python3 scripts/validate_agency_flow_receipt.py validation/AGENCY_FLOW_PILOT.md
python3 scripts/validate_release_receipt.py validation/release_receipt.json
python3 scripts/validate_release_receipt.py \
  evals/release_receipt.valid_no_stuck_review.json
python3 scripts/validate_release_receipt.py \
  evals/release_receipt.invalid_extra_wave_no_reason.json \
  --expect-invalid
python3 scripts/validate_release_receipt.py \
  evals/release_receipt.invalid_stuck_review_no_rescue.json \
  --expect-invalid
python3 scripts/validate_activation_contract.py .

python3 scripts/discover_skills.py --help >/dev/null
python3 scripts/discover_agents.py --help >/dev/null
python3 scripts/score_capabilities.py --help >/dev/null
python3 scripts/score_capabilities.py \
  --query "codex thread rescue" \
  --limit 5 \
  --json >/dev/null
python3 scripts/install_skill.py --help >/dev/null

python3 scripts/discover_skills.py \
  --root . \
  --query "zhijuan-codex-agency-chief-of-staf" \
  --limit 5 | grep -q "zhijuan-codex-agency-chief-of-staf"
if [ -d ".codex/agents" ]; then
  python3 scripts/discover_agents.py \
    --root .codex/agents \
    --query "skill-scout" \
    --limit 5 | grep -q ".codex/agents/skill-scout.toml"
fi

PILOT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/agency-pilot.XXXXXX")"
trap 'rm -rf "$PILOT_TMP"' EXIT
python3 scripts/pilot_harness.py --root . --out "$PILOT_TMP" >/dev/null

INSTALLED="$HOME/.agents/skills/zhijuan-codex-agency-chief-of-staf"
CURRENT="$(pwd -P)"
INSTALLED_REAL="$(cd "$INSTALLED" 2>/dev/null && pwd -P || true)"
if [ -d "$INSTALLED" ] && [ "$CURRENT" != "$INSTALLED_REAL" ]; then
  diff -qr \
    -x .git \
    -x .codex \
    -x __pycache__ \
    -x .pytest_cache \
    -x agency-thread-pilot \
    -x .DS_Store \
    "$INSTALLED" . >/dev/null
fi

echo "Release smoke check passed."
