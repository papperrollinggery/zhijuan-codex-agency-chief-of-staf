#!/usr/bin/env python3
"""Resolve the Execution Root model from a live Codex App Server catalog."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from agency_task import load_json
from inspect_codex_models import (
    CodexAppServer,
    canonical_state_connection,
    collect_model_items,
    resolve_executable,
    root_provider_from_database,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "assets" / "execution-model-policy.json"
MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = load_json(path)
    if (
        policy.get("schema_version") != "1.0"
        or policy.get("display_model") != "GPT-5.6 Sol"
        or policy.get("reasoning") != "ultra"
        or policy.get("provider") != "openai"
        or policy.get("require_live_catalog") is not True
        or policy.get("fallback") != "manual_user_decision"
        or policy.get("silent_downgrade_allowed") is not False
    ):
        raise ValueError("execution model policy is invalid")
    order = policy.get("reasoning_order")
    if not isinstance(order, list) or "ultra" not in order or len(order) != len(set(order)):
        raise ValueError("execution model reasoning order is invalid")
    return policy


def _normalized_display(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _model_field(item: dict[str, Any]) -> str | None:
    value = item.get("id", item.get("model"))
    return value if isinstance(value, str) else None


def _display_field(item: dict[str, Any]) -> str | None:
    for key in ("display_name", "displayName", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _provider_field(item: dict[str, Any]) -> str | None:
    value = item.get("provider") or item.get("modelProvider")
    return value if isinstance(value, str) else None


def _effort_fields(item: dict[str, Any]) -> list[str]:
    raw = item.get("supported_reasoning", item.get("supportedReasoningEfforts"))
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for entry in raw:
        effort = entry.get("reasoningEffort") if isinstance(entry, dict) else entry
        if isinstance(effort, str) and effort not in result:
            result.append(effort)
    default = item.get("defaultReasoningEffort", item.get("default_reasoning"))
    if isinstance(default, str) and default not in result:
        result.append(default)
    return result


def normalize_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    live = raw.get("live_readback_verified")
    if live is None and isinstance(raw.get("provenance"), dict):
        live = raw["provenance"].get("live_readback_verified")
    source = raw.get("source")
    if source is None and isinstance(raw.get("provenance"), dict):
        source = raw["provenance"].get("source")
    models = raw.get("models")
    if not isinstance(models, list):
        raise ValueError("execution model catalog has no models array")
    normalized: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            raise ValueError("execution model catalog entry must be an object")
        model_id = _model_field(item)
        display = _display_field(item)
        provider = _provider_field(item)
        if model_id is None or not MODEL_ID_RE.fullmatch(model_id):
            raise ValueError("execution model catalog contains an invalid model id")
        if display is None:
            continue
        normalized.append(
            {
                "id": model_id,
                "display_name": display,
                "provider": provider,
                "supported_reasoning": _effort_fields(item),
                "provider_evidence": item.get("provider_evidence"),
            }
        )
    return {
        "source": source,
        "live_readback_verified": live is True,
        "models": normalized,
    }


def live_catalog(
    *,
    codex_bin: str,
    project: Path,
    codex_home: Path | None = None,
    state_db: Path | None = None,
    thread_id: str | None = None,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    if bool(state_db) != bool(thread_id):
        raise ValueError("state_db and thread_id must be supplied together")
    executable = resolve_executable(codex_bin)
    root = project.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("project must be a non-symlink directory")
    with CodexAppServer(
        executable,
        cwd=root,
        codex_home=codex_home.expanduser() if codex_home else None,
        timeout_seconds=timeout_seconds,
    ) as app:
        items = collect_model_items(app)
        root_provider: str | None = None
        provider_evidence = "catalog-advertised"
        if state_db is not None and thread_id is not None:
            with canonical_state_connection(state_db, app.codex_home) as (database, _identity):
                root_provider = root_provider_from_database(database, thread_id)
            provider_evidence = "root-state-inferred"
    models: list[dict[str, Any]] = []
    for item in items:
        model_id = item.get("model")
        display = _display_field(item)
        advertised_provider = item.get("modelProvider", item.get("provider"))
        provider = advertised_provider if isinstance(advertised_provider, str) else root_provider
        if not isinstance(model_id, str) or display is None:
            continue
        models.append(
            {
                "id": model_id,
                "display_name": display,
                "provider": provider,
                "provider_evidence": (
                    "catalog-advertised" if isinstance(advertised_provider, str) else provider_evidence
                ),
                "supported_reasoning": _effort_fields(item),
            }
        )
    return {
        "schema_version": "1.0",
        "source": "active-host-catalog",
        "live_readback_verified": True,
        "models": models,
    }


def verify_spawn_model_readback(
    resolution: dict[str, Any], readback: dict[str, Any]
) -> dict[str, Any]:
    expected = {
        "provider": resolution.get("provider"),
        "actual_model_id": resolution.get("resolved_model_id"),
        "actual_reasoning_effort": resolution.get("resolved_reasoning"),
    }
    mismatches = {
        key: {"expected": value, "actual": readback.get(key)}
        for key, value in expected.items()
        if readback.get(key) != value
    }
    if mismatches:
        return {
            **resolution,
            "status": "FAIL",
            "resolution_status": "readback_mismatch",
            "launch_allowed": False,
            "readback_verified": False,
            "readback_mismatches": mismatches,
        }
    return {
        **resolution,
        "readback_verified": True,
        "readback_mismatches": {},
    }


def resolve_execution_model(
    raw_catalog: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    spawn_readback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy()
    catalog = normalize_catalog(raw_catalog)
    base = {
        "display_request": policy["display_model"],
        "reasoning_request": policy["reasoning"],
        "provider": policy["provider"],
        "fallback": policy["fallback"],
        "catalog_source": catalog["source"],
        "catalog_live_readback_verified": catalog["live_readback_verified"],
        "readback_verified": False,
    }
    if policy["require_live_catalog"] and (
        not catalog["live_readback_verified"] or catalog["source"] != "active-host-catalog"
    ):
        return {
            **base,
            "status": "user_choice_required",
            "resolution_status": "unavailable",
            "resolved_model_id": None,
            "resolved_reasoning": None,
            "launch_allowed": False,
            "reason": "live_catalog_required",
            "choices": ["使用用户指定替代模型", "暂不启动"],
        }
    requested_display = _normalized_display(policy["display_model"])
    matches = [
        item
        for item in catalog["models"]
        if _normalized_display(item["display_name"]) == requested_display
        and item["provider"] == policy["provider"]
    ]
    if not matches:
        return {
            **base,
            "status": "user_choice_required",
            "resolution_status": "unavailable",
            "resolved_model_id": None,
            "resolved_reasoning": None,
            "launch_allowed": False,
            "reason": "requested_display_model_not_found",
            "choices": ["使用用户指定替代模型", "暂不启动"],
        }
    exact_ids = {item["id"] for item in matches}
    if len(exact_ids) != 1:
        return {
            **base,
            "status": "user_choice_required",
            "resolution_status": "unavailable",
            "resolved_model_id": None,
            "resolved_reasoning": None,
            "launch_allowed": False,
            "reason": "ambiguous_exact_model_id",
            "candidate_model_ids": sorted(exact_ids),
            "choices": ["使用用户指定替代模型", "暂不启动"],
        }
    match = matches[0]
    supported = [
        effort for effort in policy["reasoning_order"] if effort in match["supported_reasoning"]
    ]
    if policy["reasoning"] not in supported:
        highest = supported[-1] if supported else None
        return {
            **base,
            "status": "user_choice_required",
            "resolution_status": "user_choice_required",
            "resolved_model_id": match["id"],
            "resolved_reasoning": None,
            "highest_supported_reasoning": highest,
            "launch_allowed": False,
            "reason": "requested_reasoning_not_supported",
            "choices": [
                f"使用当前 Sol 支持的最高 Effort：{highest or '无可用值'}",
                "使用用户指定替代模型",
                "暂不启动",
            ],
        }
    resolution = {
        **base,
        "status": "resolved",
        "resolution_status": "resolved",
        "resolved_model_id": match["id"],
        "resolved_reasoning": policy["reasoning"],
        "provider_evidence": match.get("provider_evidence"),
        "launch_allowed": True,
        "choices": [],
    }
    return (
        verify_spawn_model_readback(resolution, spawn_readback)
        if spawn_readback is not None
        else resolution
    )


def run_self_test() -> dict[str, Any]:
    def catalog(models: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": "active-host-catalog",
            "live_readback_verified": True,
            "models": models,
        }

    available = catalog(
        [
            {
                "id": "gpt-5.6-sol-2026-07",
                "display_name": "GPT-5.6 Sol",
                "provider": "openai",
                "supported_reasoning": ["high", "ultra"],
            }
        ]
    )
    resolved = resolve_execution_model(available)
    if resolved["resolved_model_id"] != "gpt-5.6-sol-2026-07" or not resolved["launch_allowed"]:
        raise AssertionError("Sol ultra did not resolve")
    unsupported = resolve_execution_model(
        catalog(
            [
                {
                    "id": "gpt-5.6-sol-2026-07",
                    "display_name": "GPT-5.6 Sol",
                    "provider": "openai",
                    "supported_reasoning": ["high", "xhigh"],
                }
            ]
        )
    )
    if unsupported["resolution_status"] != "user_choice_required":
        raise AssertionError("unsupported ultra did not require user choice")
    absent = resolve_execution_model(catalog([]))
    if absent["resolved_model_id"] is not None or absent["reason"] != "requested_display_model_not_found":
        raise AssertionError("missing Sol was guessed")
    mismatch = resolve_execution_model(
        available,
        spawn_readback={
            "provider": "openai",
            "actual_model_id": "different-model",
            "actual_reasoning_effort": "ultra",
        },
    )
    if mismatch["status"] != "FAIL" or mismatch["resolution_status"] != "readback_mismatch":
        raise AssertionError("spawn model mismatch did not fail")
    return {
        "status": "self-test-passed",
        "sol_ultra": resolved["resolution_status"],
        "ultra_unsupported": unsupported["resolution_status"],
        "sol_absent": absent["resolution_status"],
        "spawn_mismatch": mismatch["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve the Agency Execution Root model.")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--spawn-readback", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = run_self_test()
    else:
        catalog = (
            load_json(args.catalog)
            if args.catalog
            else live_catalog(
                codex_bin=args.codex_bin,
                project=args.project,
                codex_home=args.codex_home,
                state_db=args.state_db,
                thread_id=args.thread_id,
                timeout_seconds=args.timeout_seconds,
            )
        )
        readback = load_json(args.spawn_readback) if args.spawn_readback else None
        result = resolve_execution_model(catalog, spawn_readback=readback)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"Execution model resolution failed: {exc}")
