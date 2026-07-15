#!/usr/bin/env python3
"""Resolve bounded role/model plans without changing Codex configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from inspect_codex_models import (
    CodexAppServer,
    binary_version,
    build_resolver_catalog,
    canonical_state_connection,
    catalog_source_id,
    collect_model_items,
    provider_evidence_for_bindings,
    root_provider_from_database,
    resolve_executable,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "assets" / "role-model-policy.json"
RISK_LEVELS = ("low", "medium", "high", "critical")
ROUTE_MODES = ("inherit", "direct", "custom-agent")
MODEL_CLASSES = frozenset({"efficient", "balanced", "judgment"})
REASONING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
SUPPORTED_PROFILES = frozenset(
    {
        "codebase-researcher",
        "technical-architect",
        "developer",
        "writer",
        "reviewer",
        "test-debugger",
        "supervisor",
    }
)
_ATTESTATION_KEY = object()


class LiveCatalogAttestation:
    __slots__ = ("catalog_sha256", "requested_thread_id", "source_id")

    def __init__(
        self,
        *,
        catalog_sha256: str,
        requested_thread_id: str,
        source_id: str,
        _key: object,
    ) -> None:
        if _key is not _ATTESTATION_KEY:
            raise ValueError("live catalog attestations can only be issued by verification")
        self.catalog_sha256 = catalog_sha256
        self.requested_thread_id = requested_thread_id
        self.source_id = source_id


def catalog_sha256(catalog: dict[str, object]) -> str:
    data = json.dumps(
        catalog, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _issue_live_catalog_attestation(
    catalog: dict[str, object],
) -> LiveCatalogAttestation:
    provenance = catalog.get("provenance")
    if not isinstance(provenance, dict):
        fail("cannot attest a catalog without provenance")
    thread_id = provenance.get("requested_thread_id")
    source_id = provenance.get("source_id")
    if not isinstance(thread_id, str) or not isinstance(source_id, str):
        fail("cannot attest a catalog with incomplete provenance")
    return LiveCatalogAttestation(
        catalog_sha256=catalog_sha256(catalog),
        requested_thread_id=thread_id,
        source_id=source_id,
        _key=_ATTESTATION_KEY,
    )


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"JSON input must be a non-symlink regular file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"JSON input must be a single regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
    finally:
        os.close(descriptor)
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSON input must be UTF-8: {path}") from exc
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
        "native_routing",
        "external_advisor",
    }
    if set(policy) != expected_top:
        fail("role-model policy top-level fields are invalid")
    if policy.get("schema_version") != 2:
        fail("role-model policy schema_version must be 2")
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
        "native_tool_namespace",
        "required_direct_spawn_fields",
        "required_agent_spawn_fields",
        "same_provider_required_for_direct_model",
        "custom_agent_requires_authenticated_provider",
        "source_templates_pin_models",
        "automatic_global_config_writes",
        "external_models_default_enabled",
        "catalog_adapter",
        "live_catalog_verification_required_for_dispatch",
        "receipt_verifier",
        "compatibility_fallback",
        "truth_states",
    }:
        fail("role-model policy route contract fields are invalid")
    if (
        route.get("same_provider_required_for_direct_model") is not True
        or route.get("native_tool_namespace") != "agents"
        or route.get("required_direct_spawn_fields")
        != ["model", "reasoning_effort", "fork_turns"]
        or route.get("required_agent_spawn_fields") != ["agent_type", "fork_turns"]
        or route.get("custom_agent_requires_authenticated_provider") is not True
        or route.get("source_templates_pin_models") is not False
        or route.get("automatic_global_config_writes") is not False
        or route.get("external_models_default_enabled") is not False
        or route.get("catalog_adapter") != "scripts/inspect_codex_models.py"
        or route.get("live_catalog_verification_required_for_dispatch") is not True
        or route.get("receipt_verifier") != "scripts/verify_role_route_receipt.py"
        or route.get("compatibility_fallback") != "scripts/run_profile_compat.py"
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
            if type(budget.get(key)) is not int or budget[key] < 0:
                fail(f"budget value must be a non-negative integer: {name}:{key}")
        if budget["max_auto_upgrades_per_role"] not in {0, 1}:
            fail(f"automatic role upgrade limit must be zero or one: {name}")
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
    if set(profiles) != SUPPORTED_PROFILES:
        fail("role-model policy profiles must be exactly the seven shipped roles")
    native = policy.get("native_routing")
    if not isinstance(native, dict) or set(native) != {
        "configurator",
        "explicit_apply_required",
        "new_task_required_after_apply",
        "managed_fields",
    }:
        fail("native routing contract fields are invalid")
    if (
        native.get("configurator") != "scripts/configure_native_routing.py"
        or native.get("explicit_apply_required") is not True
        or native.get("new_task_required_after_apply") is not True
        or native.get("managed_fields")
        != [
            "features.multi_agent_v2.hide_spawn_agent_metadata",
            "features.multi_agent_v2.tool_namespace",
            "features.multi_agent_v2.multi_agent_mode_hint_text",
            "features.multi_agent_v2.usage_hint_text",
        ]
    ):
        fail("native routing safety values are invalid")
    advisor = policy.get("external_advisor")
    if not isinstance(advisor, dict) or set(advisor) != {
        "default",
        "enabled_by_default",
        "core_dependency",
        "mode",
        "may_edit",
        "may_delegate",
        "may_approve_final_delivery",
        "optional_adapters",
    }:
        fail("external advisor contract fields are invalid")
    if (
        advisor.get("default") != "none"
        or advisor.get("enabled_by_default") is not False
        or advisor.get("core_dependency") is not False
        or advisor.get("mode") != "root-facing-read-only"
        or advisor.get("may_edit") is not False
        or advisor.get("may_delegate") is not False
        or advisor.get("may_approve_final_delivery") is not False
        or advisor.get("optional_adapters")
        != ["openai-custom-agent", "claude-fable-mcp"]
    ):
        fail("external advisor must remain optional, root-facing, and read-only")


def validate_catalog_provenance(
    catalog: dict[str, object], route_mode: str, root_provider: str | None
) -> dict[str, object]:
    if set(catalog) != {"schema_version", "provenance", "models"}:
        fail("catalog fields must be exactly schema_version, provenance, and models")
    if catalog.get("schema_version") != 2:
        fail("catalog schema_version must be 2")
    provenance = catalog.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "source",
        "source_id",
        "observed_for_requested_thread",
        "requested_thread_id",
        "root_provider",
        "canonical_state_store_bound",
        "model_provider_evidence",
    }:
        fail("catalog provenance contract is invalid")
    source = provenance.get("source")
    if source not in {"active-host-catalog", "loaded-custom-agent", "user-confirmed-exact-id"}:
        fail("catalog provenance source is unsupported")
    if not isinstance(provenance.get("source_id"), str) or not provenance["source_id"]:
        fail("catalog provenance source_id is required")
    observed = provenance.get("observed_for_requested_thread")
    thread_id = provenance.get("requested_thread_id")
    canonical = provenance.get("canonical_state_store_bound")
    provider_evidence = provenance.get("model_provider_evidence")
    if type(observed) is not bool or type(canonical) is not bool:
        fail("catalog requested-thread provenance flags are invalid")
    if thread_id is not None and (
        not isinstance(thread_id, str)
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", thread_id)
        is None
    ):
        fail("catalog requested thread id is invalid")
    if provider_evidence not in {
        "catalog-advertised",
        "root-state-inferred",
        "loaded-custom-agent-readback",
        "user-confirmed",
    }:
        fail("catalog model provider evidence is invalid")
    if route_mode == "direct":
        if source not in {"active-host-catalog", "user-confirmed-exact-id"}:
            fail("direct routing requires active-host or user-confirmed catalog provenance")
        if root_provider != "openai" or provenance.get("root_provider") != "openai":
            fail("core direct routing requires the current OpenAI provider")
        if source == "active-host-catalog" and (
            observed is not True or thread_id is None or canonical is not True
        ):
            fail("active-host direct routing requires canonical requested-thread readback")
        if source == "user-confirmed-exact-id" and (
            observed is not False
            or thread_id is not None
            or canonical is not False
            or provider_evidence != "user-confirmed"
        ):
            fail("user-confirmed catalog provenance is inconsistent")
        if not root_provider or provenance.get("root_provider") != root_provider:
            fail("direct routing catalog root provider does not match the requested root")
    if route_mode == "custom-agent" and source != "loaded-custom-agent":
        fail("custom-agent routing requires loaded custom-agent provenance")
    if route_mode == "custom-agent" and (
        provenance.get("root_provider") != "openai"
        or observed is not True
        or thread_id is None
        or provider_evidence != "loaded-custom-agent-readback"
    ):
        fail("core custom-agent routing requires an OpenAI loaded-agent readback")
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
        provider_evidence = item.get("provider_evidence")
        if not isinstance(model_id, str) or not model_id:
            fail(f"catalog model id is invalid at index {index}")
        if model_id in seen_ids:
            fail(f"catalog model id is duplicated: {model_id}")
        seen_ids.add(model_id)
        if not isinstance(provider, str) or not provider:
            fail(f"catalog model provider is invalid: {model_id}")
        if provider != "openai" or model_id.lower().startswith("claude-"):
            fail(f"core catalog model must use the OpenAI provider: {model_id}")
        if provider_evidence not in {
            "catalog-advertised",
            "root-state-inferred",
            "loaded-custom-agent-readback",
            "user-confirmed",
        }:
            fail(f"catalog model provider evidence is invalid: {model_id}")
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
    role: str,
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
                or item["agent_type"] != role
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


def verify_live_catalog(
    catalog: dict[str, object],
    *,
    codex_bin: str,
    codex_home: Path | None,
    cwd: Path,
    state_db: Path,
    thread_id: str,
    root_provider: str,
    timeout_seconds: int,
) -> LiveCatalogAttestation:
    """Rebuild a direct-route catalog from the live host before dispatch use."""

    validate_catalog_provenance(catalog, "direct", root_provider)
    models = validate_catalog_models(catalog)
    provenance = catalog["provenance"]
    assert isinstance(provenance, dict)
    if provenance.get("source") != "active-host-catalog":
        fail("live verification requires an active-host catalog")
    if provenance.get("requested_thread_id") != thread_id:
        fail("live catalog thread does not match --thread-id")
    bindings: dict[str, str] = {}
    classes: set[str] = set()
    for item in models:
        model_id = item["id"]
        model_class = item["model_class"]
        assert isinstance(model_id, str) and isinstance(model_class, str)
        if model_class in classes:
            fail("live catalog contains more than one model for a capability class")
        classes.add(model_class)
        bindings[model_id] = model_class

    executable = resolve_executable(codex_bin)
    version = binary_version(executable)
    live_cwd = cwd.expanduser().resolve()
    if cwd.is_symlink() or not live_cwd.is_dir():
        fail(f"live catalog cwd must be a regular directory: {cwd}")
    with CodexAppServer(
        executable,
        cwd=live_cwd,
        codex_home=codex_home.expanduser() if codex_home is not None else None,
        timeout_seconds=timeout_seconds,
    ) as app:
        items = collect_model_items(app)
        with canonical_state_connection(
            state_db, app.codex_home
        ) as (database, state_identity):
            observed_provider = root_provider_from_database(database, thread_id)
            if observed_provider != root_provider:
                fail("live root provider does not match --root-provider")
        state_binding: dict[str, object] = {
            "thread_id": thread_id,
            **state_identity,
        }
    source_id = catalog_source_id(
        executable=executable,
        version=version,
        items=items,
        root_provider=observed_provider,
        state_binding=state_binding,
    )
    live_provider_evidence = provider_evidence_for_bindings(
        items,
        bindings,
        root_provider=observed_provider,
        fallback="root-state-inferred",
    )
    rebuilt = build_resolver_catalog(
        items,
        bindings,
        root_provider=observed_provider,
        source_id=source_id,
        provenance_source="active-host-catalog",
        requested_thread_id=thread_id,
        canonical_state_store_bound=True,
        model_provider_evidence=live_provider_evidence,
    )
    if rebuilt != catalog:
        fail("catalog does not match a fresh live App Server and state readback")
    return _issue_live_catalog_attestation(catalog)


def resolve_plan(
    policy: dict[str, object],
    roles: list[str],
    risk: str,
    budget_name: str,
    route_mode: str,
    catalog: dict[str, object] | None,
    root_provider: str | None,
    catalog_attestation: LiveCatalogAttestation | None = None,
) -> dict[str, object]:
    validate_policy(policy)
    profiles = policy["profiles"]
    classes = policy["model_classes"]
    budgets = policy["budget_modes"]
    assert isinstance(profiles, dict) and isinstance(classes, dict) and isinstance(budgets, dict)
    budget = budgets[budget_name]
    assert isinstance(budget, dict)
    auto_upgrades = int(budget["max_auto_upgrades_per_role"])
    high_risk = risk in {"high", "critical"} and auto_upgrades > 0

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

    if catalog_attestation is not None and (
        not isinstance(catalog_attestation, LiveCatalogAttestation)
        or route_mode != "direct"
        or catalog is None
    ):
        fail("catalog attestation is currently supported only for direct routes")
    catalog_attested = catalog_attestation is not None
    if catalog_attestation is not None:
        provenance = catalog.get("provenance")
        assert isinstance(provenance, dict)
        if (
            catalog_attestation.catalog_sha256 != catalog_sha256(catalog)
            or catalog_attestation.requested_thread_id
            != provenance.get("requested_thread_id")
            or catalog_attestation.source_id != provenance.get("source_id")
        ):
            fail("live catalog attestation does not bind this catalog")
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
        reasoning = str(
            class_policy["elevated_reasoning"]
            if risk == "critical" and auto_upgrades > 0
            else class_policy["default_reasoning"]
        )
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
            "route_state": (
                "inherited-unverified"
                if route_mode == "inherit"
                else (
                    "planned"
                    if catalog_attested
                    and catalog_provenance is not None
                    and catalog_provenance.get("source")
                    in {"active-host-catalog", "loaded-custom-agent"}
                    else "planned-unverified"
                )
            ),
            "model": None,
            "provider": None,
            "agent_type": None,
            "dispatch_wave": len(delegated) // max_parallel + 1,
            "dispatch_contract": None,
        }
        if route_mode != "inherit":
            if catalog is None:
                entry["route_state"] = "unavailable"
                entry["fallback"] = "use the named role with host inheritance; do not claim an exact model"
            else:
                selected = choose_catalog_model(
                    catalog, role, model_class, reasoning, route_mode, root_provider
                )
                if selected is None:
                    entry["route_state"] = "unavailable"
                    entry["fallback"] = "use the named role with host inheritance; do not claim an exact model"
                else:
                    entry["model"] = selected["id"]
                    entry["provider"] = selected["provider"]
                    if route_mode == "direct" and catalog_attested:
                        entry["dispatch_contract"] = {
                            "namespace": "agents",
                            "arguments": {
                                "model": selected["id"],
                                "reasoning_effort": reasoning,
                                "fork_turns": "none",
                            },
                        }
        delegated.append(entry)
        total_units += units

    return {
        "schema_version": 2,
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
            "catalog_provenance_locally_consistent": bool(
                catalog_attested
                and catalog_provenance is not None
                and catalog_provenance.get("source")
                in {"active-host-catalog", "loaded-custom-agent"}
            ),
            "catalog_live_readback_verified": catalog_attested,
            "catalog_provenance_confirmed": False,
            "same_provider_independently_advertised": bool(
                catalog_attested
                and catalog is not None
                and isinstance(catalog.get("models"), list)
                and catalog["models"]
                and all(
                    isinstance(item, dict)
                    and item.get("provider_evidence") == "catalog-advertised"
                    for item in catalog["models"]
                )
            ),
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
    parser.add_argument(
        "--catalog",
        type=Path,
        help=(
            "Catalog snapshot used for planning. A direct dispatch contract additionally "
            "requires --verify-live-catalog; custom-agent remains plan-only."
        ),
    )
    parser.add_argument(
        "--verify-live-catalog",
        action="store_true",
        help=(
            "Rebuild and compare a direct-route catalog before emitting dispatch arguments; "
            "requires --state-db, --thread-id, and --root-provider."
        ),
    )
    parser.add_argument("--root-provider", help="Current root provider id; required for direct routing.")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    policy = load_json(args.policy.expanduser())
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict):
        fail("role-model policy profiles are missing")
    roles = parse_roles(args.roles, set(profiles))
    if args.route_mode == "direct" and not args.root_provider:
        fail("direct routing requires --root-provider")
    catalog = load_json(args.catalog.expanduser()) if args.catalog else None
    if args.verify_live_catalog:
        if (
            args.route_mode != "direct"
            or catalog is None
            or args.state_db is None
            or args.thread_id is None
        ):
            fail(
                "--verify-live-catalog requires direct mode, --catalog, --state-db, and --thread-id"
            )
        if not 1 <= args.timeout_seconds <= 120:
            fail("--timeout-seconds must be between 1 and 120")
        catalog_attestation = verify_live_catalog(
            catalog,
            codex_bin=args.codex_bin,
            codex_home=args.codex_home,
            cwd=args.cwd,
            state_db=args.state_db,
            thread_id=args.thread_id,
            root_provider=args.root_provider,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        catalog_attestation = None
    plan = resolve_plan(
        policy,
        roles,
        args.risk,
        args.budget,
        args.route_mode,
        catalog,
        args.root_provider,
        catalog_attestation=catalog_attestation,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else human_summary(plan))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Role route unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
