#!/usr/bin/env python3
"""Resolve bounded role/model plans without changing Codex configuration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "assets" / "role-model-policy.json"
RISK_LEVELS = ("low", "medium", "high", "critical")
ROUTE_MODES = ("inherit", "direct", "custom-agent")
MODEL_CLASSES = frozenset({"efficient", "balanced", "judgment"})
REASONING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        fail(f"JSON input must be a regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON input must be an object: {path}")
    return value


def parse_roles(raw: str, known: set[str]) -> list[str]:
    roles = [item.strip() for item in raw.split(",") if item.strip()]
    if not roles:
        fail("at least one role is required")
    if len(roles) != len(set(roles)):
        fail("roles must not repeat")
    unknown = sorted(set(roles) - known)
    if unknown:
        fail(f"unknown roles: {', '.join(unknown)}")
    return roles


def validate_policy(policy: dict[str, object]) -> None:
    expected_top = {
        "schema_version",
        "policy_name",
        "root_ownership",
        "exact_model_resolution",
        "model_classes",
        "budget_modes",
        "profiles",
        "route_contract",
        "external_advisor",
    }
    if set(policy) != expected_top:
        fail("role-model policy top-level fields are invalid")
    if policy.get("schema_version") != 1:
        fail("role-model policy schema_version must be 1")
    if policy.get("policy_name") != "agency-role-model-routing":
        fail("role-model policy name is invalid")
    if policy.get("root_ownership") != "always":
        fail("role-model policy must preserve root ownership")
    if policy.get("exact_model_resolution") != [
        "active-host-catalog",
        "loaded-custom-agent",
        "user-confirmed-exact-id",
    ]:
        fail("role-model policy exact model resolution order is invalid")
    classes = policy.get("model_classes")
    budgets = policy.get("budget_modes")
    profiles = policy.get("profiles")
    route = policy.get("route_contract")
    if not isinstance(classes, dict) or set(classes) != {"efficient", "balanced", "judgment"}:
        fail("role-model policy model class set is invalid")
    if not isinstance(budgets, dict) or set(budgets) != {"economy", "balanced", "quality"}:
        fail("role-model policy budget mode set is invalid")
    if not isinstance(profiles, dict) or not profiles:
        fail("role-model policy profiles are missing")
    if not isinstance(route, dict) or route.get("override_fork_turns") != "none":
        fail("role-model policy must require fork_turns none for overrides")
    if set(route) != {
        "override_fork_turns",
        "same_provider_required_for_direct_model",
        "custom_agent_requires_authenticated_provider",
        "source_templates_pin_models",
        "automatic_global_config_writes",
        "truth_states",
    }:
        fail("role-model policy route contract fields are invalid")
    if (
        route.get("same_provider_required_for_direct_model") is not True
        or route.get("custom_agent_requires_authenticated_provider") is not True
        or route.get("source_templates_pin_models") is not False
        or route.get("automatic_global_config_writes") is not False
        or route.get("truth_states")
        != [
            "planned",
            "planned-unverified",
            "accepted",
            "confirmed",
            "inherited-unverified",
            "unavailable",
        ]
    ):
        fail("role-model policy route contract safety values are invalid")
    for name, model_class in classes.items():
        if not isinstance(model_class, dict):
            fail(f"model class must be an object: {name}")
        if set(model_class) != {
            "relative_cost_units",
            "intent",
            "default_reasoning",
            "elevated_reasoning",
        }:
            fail(f"model class fields are invalid: {name}")
        if not isinstance(model_class.get("relative_cost_units"), int) or model_class["relative_cost_units"] < 1:
            fail(f"model class cost must be a positive integer: {name}")
        for key in ("default_reasoning", "elevated_reasoning"):
            if model_class.get(key) not in {"low", "medium", "high", "xhigh"}:
                fail(f"model class reasoning is invalid: {name}:{key}")
    for name, budget in budgets.items():
        if not isinstance(budget, dict):
            fail(f"budget mode must be an object: {name}")
        if set(budget) != {
            "max_delegated_roles",
            "max_parallel_roles",
            "max_relative_cost_units",
            "max_auto_upgrades_per_role",
        }:
            fail(f"budget mode fields are invalid: {name}")
        for key in ("max_delegated_roles", "max_parallel_roles", "max_relative_cost_units", "max_auto_upgrades_per_role"):
            if not isinstance(budget.get(key), int) or budget[key] < 0:
                fail(f"budget value must be a non-negative integer: {name}:{key}")
        if budget["max_parallel_roles"] > budget["max_delegated_roles"]:
            fail(f"parallel role limit cannot exceed delegated role limit: {name}")
    for role, profile in profiles.items():
        if not isinstance(profile, dict):
            fail(f"profile policy must be an object: {role}")
        if set(profile) != {
            "default_model_class",
            "high_risk_model_class",
            "budget_priority",
            "independent_required",
        }:
            fail(f"profile policy fields are invalid: {role}")
        if profile.get("default_model_class") not in classes or profile.get("high_risk_model_class") not in classes:
            fail(f"profile model class is invalid: {role}")
        if not isinstance(profile.get("budget_priority"), int):
            fail(f"profile budget priority is invalid: {role}")
        if not isinstance(profile.get("independent_required"), bool):
            fail(f"profile independent-required flag is invalid: {role}")
    advisor = policy.get("external_advisor")
    if not isinstance(advisor, dict) or set(advisor) != {
        "default",
        "mode",
        "may_edit",
        "may_delegate",
        "may_approve_final_delivery",
        "optional_adapters",
    }:
        fail("external advisor contract fields are invalid")
    if (
        advisor.get("default") != "none"
        or advisor.get("mode") != "root-facing-read-only"
        or advisor.get("may_edit") is not False
        or advisor.get("may_delegate") is not False
        or advisor.get("may_approve_final_delivery") is not False
        or advisor.get("optional_adapters")
        != ["openai-custom-agent", "future-host-scoped-adapter"]
    ):
        fail("external advisor must remain optional, root-facing, and read-only")


def validate_catalog_provenance(
    catalog: dict[str, object], route_mode: str, root_provider: str | None
) -> dict[str, object]:
    if set(catalog) != {"provenance", "models"}:
        fail("catalog fields must be exactly provenance and models")
    provenance = catalog.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "source",
        "source_id",
        "observed_for_current_task",
        "root_provider",
    }:
        fail("catalog provenance contract is invalid")
    source = provenance.get("source")
    if source not in {"active-host-catalog", "loaded-custom-agent", "user-confirmed-exact-id"}:
        fail("catalog provenance source is unsupported")
    if not isinstance(provenance.get("source_id"), str) or not provenance["source_id"]:
        fail("catalog provenance source_id is required")
    if provenance.get("observed_for_current_task") is not True:
        fail("catalog must be observed for the current task")
    if route_mode == "direct":
        if source not in {"active-host-catalog", "user-confirmed-exact-id"}:
            fail("direct routing requires active-host or user-confirmed catalog provenance")
        if not root_provider or provenance.get("root_provider") != root_provider:
            fail("direct routing catalog root provider does not match the current task")
    if route_mode == "custom-agent" and source != "loaded-custom-agent":
        fail("custom-agent routing requires loaded custom-agent provenance")
    return provenance


def validate_catalog_models(catalog: dict[str, object]) -> list[dict[str, object]]:
    """Validate every supplied catalog record before eligibility filtering."""
    models = catalog.get("models")
    if not isinstance(models, list):
        fail("catalog models must be a list")
    validated: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            fail(f"catalog model entry {index} must be an object")
        model_id = item.get("id")
        provider = item.get("provider")
        model_class = item.get("model_class")
        efforts = item.get("supported_reasoning")
        available = item.get("available")
        if not isinstance(model_id, str) or not model_id:
            fail(f"catalog model id is invalid at index {index}")
        if model_id in seen_ids:
            fail(f"catalog model id is duplicated: {model_id}")
        seen_ids.add(model_id)
        if not isinstance(provider, str) or not provider:
            fail(f"catalog model provider is invalid: {model_id}")
        if model_class not in MODEL_CLASSES:
            fail(f"catalog model class is invalid: {model_id}")
        if not isinstance(efforts, list) or not efforts or any(
            value not in REASONING_LEVELS for value in efforts
        ):
            fail(f"catalog supported_reasoning is invalid: {model_id}")
        if len(efforts) != len(set(efforts)):
            fail(f"catalog supported_reasoning contains duplicates: {model_id}")
        if type(available) is not bool:
            fail(f"catalog availability is invalid: {model_id}")
        for field in ("authenticated", "loaded", "provider_pinned"):
            if field in item and type(item[field]) is not bool:
                fail(f"catalog {field} is invalid: {model_id}")
        if "agent_type" in item and (
            not isinstance(item["agent_type"], str) or not item["agent_type"]
        ):
            fail(f"catalog agent_type is invalid: {model_id}")
        relative_cost = item.get("relative_cost_units")
        if relative_cost is not None and (
            type(relative_cost) is not int or relative_cost < 0
        ):
            fail(f"catalog relative cost is invalid: {model_id}")
        validated.append(item)
    return validated


def choose_catalog_model(
    catalog: dict[str, object],
    model_class: str,
    reasoning: str,
    route_mode: str,
    root_provider: str | None,
) -> dict[str, object] | None:
    models = validate_catalog_models(catalog)
    candidates: list[dict[str, object]] = []
    for item in models:
        if item.get("model_class") != model_class or item.get("available") is not True:
            continue
        model_id = item.get("id")
        provider = item.get("provider")
        efforts = item["supported_reasoning"]
        assert isinstance(model_id, str) and isinstance(provider, str) and isinstance(efforts, list)
        if reasoning not in efforts:
            continue
        if route_mode == "direct" and (not root_provider or provider != root_provider):
            continue
        if route_mode == "custom-agent":
            if (
                item.get("authenticated") is not True
                or item.get("loaded") is not True
                or item.get("provider_pinned") is not True
                or not isinstance(item.get("agent_type"), str)
                or not item["agent_type"]
            ):
                continue
        candidates.append(item)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.get("relative_cost_units", 10**9)
            if isinstance(item.get("relative_cost_units", 10**9), int)
            else 10**9,
            str(item["id"]),
        ),
    )


def resolve_plan(
    policy: dict[str, object],
    roles: list[str],
    risk: str,
    budget_name: str,
    route_mode: str,
    catalog: dict[str, object] | None,
    root_provider: str | None,
) -> dict[str, object]:
    validate_policy(policy)
    profiles = policy["profiles"]
    classes = policy["model_classes"]
    budgets = policy["budget_modes"]
    assert isinstance(profiles, dict) and isinstance(classes, dict) and isinstance(budgets, dict)
    budget = budgets[budget_name]
    assert isinstance(budget, dict)
    high_risk = risk in {"high", "critical"}

    ranked = sorted(
        roles,
        key=lambda role: (-int(profiles[role]["budget_priority"]), roles.index(role)),  # type: ignore[index]
    )
    delegated: list[dict[str, object]] = []
    root_owned: list[dict[str, str]] = []
    total_units = 0
    max_roles = int(budget["max_delegated_roles"])
    max_parallel = int(budget["max_parallel_roles"])
    max_units = int(budget["max_relative_cost_units"])

    catalog_provenance: dict[str, object] | None = None
    if route_mode != "inherit" and catalog is not None:
        catalog_provenance = validate_catalog_provenance(catalog, route_mode, root_provider)
        validate_catalog_models(catalog)

    for role in ranked:
        profile = profiles[role]
        assert isinstance(profile, dict)
        model_class = str(profile["high_risk_model_class"] if high_risk else profile["default_model_class"])
        class_policy = classes[model_class]
        assert isinstance(class_policy, dict)
        units = int(class_policy["relative_cost_units"])
        reasoning = str(class_policy["elevated_reasoning"] if risk == "critical" else class_policy["default_reasoning"])
        if (
            max_parallel == 0
            or len(delegated) >= max_roles
            or total_units + units > max_units
        ):
            root_owned.append({"role": role, "reason": "budget capacity reserved for higher-priority delegated work"})
            continue

        entry: dict[str, object] = {
            "role": role,
            "model_class": model_class,
            "reasoning": reasoning,
            "relative_cost_units": units,
            "fork_turns": "none" if route_mode != "inherit" else None,
            "route_state": "inherited-unverified" if route_mode == "inherit" else "planned-unverified",
            "model": None,
            "provider": None,
            "agent_type": None,
            "dispatch_wave": len(delegated) // max_parallel + 1,
        }
        if route_mode != "inherit":
            if catalog is None:
                entry["route_state"] = "unavailable"
                entry["fallback"] = "use the named role with host inheritance; do not claim an exact model"
            else:
                selected = choose_catalog_model(catalog, model_class, reasoning, route_mode, root_provider)
                if selected is None:
                    entry["route_state"] = "unavailable"
                    entry["fallback"] = "use the named role with host inheritance; do not claim an exact model"
                else:
                    entry["model"] = selected["id"]
                    entry["provider"] = selected["provider"]
                    if route_mode == "custom-agent":
                        entry["agent_type"] = selected["agent_type"]
        delegated.append(entry)
        total_units += units

    return {
        "status": "plan-only" if all(item["route_state"] != "unavailable" for item in delegated) else "plan-only-with-fallback",
        "budget_mode": budget_name,
        "risk": risk,
        "route_mode": route_mode,
        "delegated": delegated,
        "root_owned": root_owned,
        "relative_cost_units": total_units,
        "limits": {
            "delegated_roles": max_roles,
            "parallel_roles": budget["max_parallel_roles"],
            "relative_cost_units": max_units,
            "auto_upgrades_per_role": budget["max_auto_upgrades_per_role"],
        },
        "claims": {
            "accepted": False,
            "confirmed": False,
            "actual_usage_measured": False,
            "catalog_input_schema_validated": catalog_provenance is not None,
            "catalog_provenance_confirmed": False,
        },
    }


def human_summary(plan: dict[str, object]) -> str:
    labels = {"economy": "节省", "balanced": "平衡", "quality": "质量优先"}
    delegated = plan["delegated"]
    root_owned = plan["root_owned"]
    assert isinstance(delegated, list) and isinstance(root_owned, list)
    fallback = any(item.get("route_state") == "unavailable" for item in delegated if isinstance(item, dict))
    result = f"采用{labels[str(plan['budget_mode'])]}配置：安排 {len(delegated)} 个专业角色"
    if root_owned:
        result += f"，另有 {len(root_owned)} 项由主线程完成"
    result += "。"
    if fallback:
        result += "精确模型路由当前不可用，已回到宿主模型；不会声称目标模型已经运行。"
    elif plan["route_mode"] == "inherit":
        result += "角色已规划，具体模型沿用宿主且运行身份尚未核对。"
    else:
        result += "精确模型已规划；只有派发接受并读回运行身份后才算确认。"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan bounded role/model routing without writing configuration.")
    parser.add_argument("--roles", required=True, help="Comma-separated existing Agency role names.")
    parser.add_argument("--risk", choices=RISK_LEVELS, default="medium")
    parser.add_argument("--budget", choices=("economy", "balanced", "quality"), default="balanced")
    parser.add_argument("--route-mode", choices=ROUTE_MODES, default="inherit")
    parser.add_argument("--catalog", type=Path, help="Current-host catalog snapshot for exact routing.")
    parser.add_argument("--root-provider", help="Current root provider id; required for direct routing.")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    policy = load_json(args.policy.expanduser().resolve())
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict):
        fail("role-model policy profiles are missing")
    roles = parse_roles(args.roles, set(profiles))
    if args.route_mode == "direct" and not args.root_provider:
        fail("direct routing requires --root-provider")
    catalog = load_json(args.catalog.expanduser().resolve()) if args.catalog else None
    plan = resolve_plan(policy, roles, args.risk, args.budget, args.route_mode, catalog, args.root_provider)
    print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else human_summary(plan))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Role route unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
