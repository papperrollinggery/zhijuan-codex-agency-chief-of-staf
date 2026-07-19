#!/usr/bin/env python3
"""Prepare only the custom-agent profiles selected by one Team Plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agency_task import load_json, safe_project_root
from install_agent_profiles import (
    install_profiles,
    read_route_plan,
    route_bindings_from_plan,
    safe_target_root,
)
from validate_agent_profiles import PROFILE_NAMES


def file_digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def selected_profiles(team_plan: dict[str, Any]) -> tuple[str, ...]:
    if team_plan.get("schema_version") != "1.0" or team_plan.get("status") != "ready":
        raise ValueError("TEAM_PLAN.json must be a ready schema 1.0 plan")
    positions = team_plan.get("positions")
    if not isinstance(positions, list) or not positions:
        raise ValueError("TEAM_PLAN.json has no positions")
    result: list[str] = []
    for position in positions:
        if not isinstance(position, dict) or not isinstance(position.get("profile"), str):
            raise ValueError("TEAM_PLAN.json position is invalid")
        profile = position["profile"]
        if profile == "execution-root":
            continue
        if profile not in PROFILE_NAMES:
            raise ValueError(f"TEAM_PLAN.json selects an unknown profile: {profile}")
        if profile not in result:
            result.append(profile)
    return tuple(result)


def prepare_team_runtime(
    project: Path,
    team_plan_path: Path,
    *,
    apply: bool,
    force: bool = False,
    route_plan_path: Path | None = None,
) -> dict[str, Any]:
    root = safe_project_root(project)
    plan = load_json(team_plan_path)
    selected = selected_profiles(plan)
    agents_file = root / "AGENTS.md"
    agents_before = file_digest(agents_file)
    if not selected:
        return {
            "status": "not-required",
            "project": str(root),
            "selected_profiles": [],
            "profiles_written": [],
            "unselected_profiles_untouched": list(PROFILE_NAMES),
            "agents_md_touched": False,
        }

    routes: dict[str, tuple[str, str]] = {}
    route_plan_sha256: str | None = None
    if route_plan_path is not None:
        route_plan, route_plan_sha256 = read_route_plan(route_plan_path)
        all_routes = route_bindings_from_plan(route_plan)
        routes = {profile: all_routes[profile] for profile in selected if profile in all_routes}
    target = safe_target_root(root / ".codex" / "agents")
    source = Path(__file__).resolve().parents[1]
    result = install_profiles(
        source,
        target,
        {},
        force,
        not apply,
        routes,
        route_plan_sha256,
        selected,
    )
    agents_after = file_digest(agents_file)
    if agents_before != agents_after:
        raise RuntimeError("project AGENTS.md changed during selected-profile preparation")
    result.update(
        {
            "project": str(root),
            "selected_profiles": list(selected),
            "profiles_written": list(selected) if apply and result["status"] in {"installed", "replaced"} else [],
            "unselected_profiles_untouched": sorted(set(PROFILE_NAMES) - set(selected)),
            "apply_explicit": apply,
            "global_agent_config_touched": False,
            "agents_md_touched": False,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare Team Plan selected profiles in project/.codex/agents. "
            "Without --apply this is a dry run; no global Agent or AGENTS.md files are written."
        )
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--team-plan", type=Path, required=True)
    parser.add_argument("--route-plan", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.force and not args.apply:
        raise ValueError("--force requires explicit --apply")
    result = prepare_team_runtime(
        args.project,
        args.team_plan,
        apply=args.apply,
        force=args.force,
        route_plan_path=args.route_plan,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"Team runtime preparation failed: {exc}")

