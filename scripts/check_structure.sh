#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
missing=0

check_file() {
  local f="$1"
  if [ ! -f "$ROOT/$f" ]; then
    echo "MISSING: $f"
    missing=1
  else
    echo "OK: $f"
  fi
}

check_dir() {
  local d="$1"
  if [ ! -d "$ROOT/$d" ]; then
    echo "MISSING: $d"
    missing=1
  else
    echo "OK: $d"
  fi
}

check_file "SKILL.md"
check_file "README.md"
check_file "LICENSE"
check_file "CHANGELOG.md"
check_file "CONTRIBUTING.md"
check_file "SECURITY.md"
check_file "Makefile"
check_file "agents/openai.yaml"
check_file "validation/THREADOPS_VALIDATION.md"
check_file "validation/COUNCIL_ROUNDS.md"
check_file "validation/AGENCY_FLOW_PILOT.md"
check_file "validation/receipts/ROUND1_RELEASE_ENGINEERING.md"
check_file "validation/receipts/ROUND2_BEHAVIOR.md"
check_file "validation/receipts/ROUND3_RELEASE_GO_NO_GO.md"

check_dir "assets"
check_dir "assets/codex_agents"
check_dir "references"
check_dir "scripts"
check_dir "validation"
check_dir "validation/receipts"

for f in \
  PROJECT_BRIEF_TEMPLATE.md \
  AGENCY_STATE_TEMPLATE.md \
  THREADS_TEMPLATE.md \
  TASK_GRAPH_TEMPLATE.md \
  MODE_ROUTER_TEMPLATE.md \
  PLAN_SESSION_TEMPLATE.md \
  GOAL_LEDGER_TEMPLATE.md \
  GOAL_CONTRACT_TEMPLATE.yaml \
  SKILL_INVENTORY_TEMPLATE.md \
  AGENT_REGISTRY_TEMPLATE.md \
  TASK_CARD_TEMPLATE.md \
  RESULT_PACKET_TEMPLATE.yaml \
  PROBE_PACKET_TEMPLATE.yaml \
  REVIEW_PACKET_TEMPLATE.yaml \
  DELEGATION_PACKET_TEMPLATE.yaml \
  SYNTHESIS_PACKET_TEMPLATE.yaml \
  RESCUE_PACKET_TEMPLATE.yaml \
  MEMORY_RULE_TEMPLATE.md \
  ERROR_BANK_TEMPLATE.md \
  DO_NOT_REPEAT_TEMPLATE.md \
  SELF_IMPROVEMENT_TEMPLATE.md \
  PATCH_PROPOSAL_TEMPLATE.md \
  CHIEF_OF_STAFF_PROMPT.md \
  PLANNER_PROMPT.md \
  GOAL_STEWARD_PROMPT.md \
  SKILL_SCOUT_PROMPT.md \
  AGENT_SCOUT_PROMPT.md \
  EXECUTOR_PROMPT.md \
  REVIEWER_PROMPT.md \
  ARCHIVIST_PROMPT.md \
  SYNTHESIZER_PROMPT.md \
  RESCUE_PROMPT.md \
  SKILL_MAINTAINER_PROMPT.md \
  HEARTBEAT_PROMPT.md
do
  check_file "assets/$f"
done

for f in \
  planner.toml \
  goal-steward.toml \
  skill-scout.toml \
  agent-scout.toml \
  archivist.toml \
  strategist.toml \
  researcher.toml \
  creative-director.toml \
  art-director.toml \
  technical-architect.toml \
  executor.toml \
  developer.toml \
  reviewer.toml \
  synthesizer.toml \
  rescue-agent.toml \
  skill-maintainer.toml
do
  check_file "assets/codex_agents/$f"
done

for f in \
  USAGE.md \
  DYNAMIC_ROUTING.md \
  CODEX_CONTROL_SURFACE.md \
  THREAD_NAMING.md \
  SKILL_AND_AGENT_ROUTING.md \
  PLAN_GOAL_PROTOCOL.md \
  STATEFUL_VS_STATELESS.md \
  DELEGATION_CHAIN.md \
  SELF_IMPROVEMENT.md \
  ANTI_BUREAUCRACY.md
do
  check_file "references/$f"
done

for f in \
  check_structure.sh \
  discover_skills.py \
  discover_agents.py \
  score_capabilities.py \
  validate_thread_name.py \
  append_event.py \
  validate_task_graph.py \
  validate_agency_flow_receipt.py \
  propose_skill_patch.py \
  release_smoke.sh \
  pilot_harness.py \
  install_skill.py \
  quality_gate.sh \
  install_codex_agents.sh
do
  check_file "scripts/$f"
done

if [ "$missing" -eq 1 ]; then
  echo "Skill structure check failed."
  exit 1
fi

echo "Skill structure check passed."
