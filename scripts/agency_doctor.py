#!/usr/bin/env python3
"""Read-only health report for Agency runtime, profiles, native APIs, and models."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from agency_task import safe_project_root
from inspect_codex_models import CodexAppServer, collect_model_items, resolve_executable
from install_skill import (
    CANONICAL_SKILL_NAME,
    LEGACY_SKILL_NAME,
    installed_manifest,
    runtime_manifest,
)
from resolve_execution_model import _display_field, _effort_fields, _normalized_display
from validate_agent_profiles import PROFILE_NAMES, validate_profile


ROOT = Path(__file__).resolve().parents[1]
ROUTING_MARKERS = (
    "AGENTS_" "ROUTING_SNIPPET",
    "BEGIN " "agency-chief-of-staff routing",
    "BEGIN " "zhijuan-codex-agency-chief-of-staf routing",
    "--agents-" "routing",
)


def manifest_hash(manifest: dict[str, str]) -> str | None:
    if not manifest:
        return None
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def implicit_policy(path: Path) -> bool | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if "allow_implicit_invocation: true" in text:
        return True
    if "allow_implicit_invocation: false" in text:
        return False
    return None


def bundle_report(skills_root: Path, skill_name: str) -> dict[str, Any]:
    target = skills_root / skill_name
    expected = runtime_manifest(ROOT, skill_name)
    try:
        actual = installed_manifest(target)
        state = "missing" if not target.exists() else "current" if actual == expected else "different"
        error = None
    except (OSError, ValueError) as exc:
        actual = {}
        state = "unreadable"
        error = str(exc)
    return {
        "location": str(target),
        "state": state,
        "source_manifest_sha256": manifest_hash(expected),
        "installed_manifest_sha256": manifest_hash(actual),
        "implicit_policy": implicit_policy(target / "agents" / "openai.yaml"),
        "error": error,
    }


def profile_report(project: Path) -> dict[str, Any]:
    target_root = project / ".codex" / "agents"
    result: dict[str, Any] = {}
    for profile in PROFILE_NAMES:
        target = target_root / f"{profile}.toml"
        source = ROOT / "assets" / "codex_agents" / f"{profile}.toml"
        if not target.exists():
            result[profile] = {"state": "missing", "same_runtime_source": False}
            continue
        try:
            validate_profile(target, profile, allow_bindings=True)
            source_text = source.read_text(encoding="utf-8").rstrip() + "\n"
            target_text = target.read_text(encoding="utf-8")
            same_source = target_text.startswith(source_text)
            result[profile] = {
                "state": "current" if target_text == source_text else "overlay" if same_source else "different",
                "same_runtime_source": same_source,
            }
        except (OSError, ValueError) as exc:
            result[profile] = {
                "state": "invalid",
                "same_runtime_source": False,
                "error": str(exc),
            }
    return {
        "location": str(target_root),
        "profiles": result,
        "present_count": sum(value["state"] != "missing" for value in result.values()),
        "required_count": len(PROFILE_NAMES),
    }


def _nested(config: object, *keys: str) -> object | None:
    value = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def native_report(project: Path, codex_bin: str, timeout_seconds: int) -> dict[str, Any]:
    executable_text = shutil.which(codex_bin) if not Path(codex_bin).is_absolute() else codex_bin
    if not executable_text:
        return {
            "codex": None,
            "agents_namespace": {"status": "unavailable", "value": None},
            "task_thread": {"status": "unavailable", "create_verified": False},
            "model_catalog": {"status": "unavailable", "models": []},
            "error": "codex executable not found",
        }
    try:
        executable = resolve_executable(codex_bin)
        with CodexAppServer(
            executable,
            cwd=project,
            codex_home=None,
            timeout_seconds=timeout_seconds,
        ) as app:
            models = collect_model_items(app)
            try:
                config_result = app.request(
                    "config/read", {"includeLayers": True, "cwd": str(project)}
                )
                namespace = _nested(
                    config_result.get("config"), "features", "multi_agent_v2", "tool_namespace"
                )
                namespace_report = {
                    "status": "read" if isinstance(namespace, str) else "unverified",
                    "value": namespace if isinstance(namespace, str) else None,
                }
            except ValueError as exc:
                namespace_report = {"status": "unverified", "value": None, "error": str(exc)}
            try:
                app.request("thread/list", {"limit": 1})
                thread_report = {
                    "status": "read-surface-available",
                    "read_verified": True,
                    "create_verified": False,
                    "note": "thread creation is not probed by the read-only doctor",
                }
            except ValueError as exc:
                thread_report = {
                    "status": "unverified",
                    "read_verified": False,
                    "create_verified": False,
                    "error": str(exc),
                }
        model_rows: list[dict[str, Any]] = []
        for item in models:
            model_id = item.get("model")
            display = _display_field(item)
            provider = item.get("modelProvider", item.get("provider"))
            if not isinstance(model_id, str):
                continue
            model_rows.append(
                {
                    "id": model_id,
                    "display_name": display,
                    "provider": provider if isinstance(provider, str) else None,
                    "supported_reasoning": _effort_fields(item),
                    "is_requested_sol": isinstance(display, str)
                    and _normalized_display(display) == _normalized_display("GPT-5.6 Sol"),
                }
            )
        return {
            "codex": str(executable),
            "agents_namespace": namespace_report,
            "task_thread": thread_report,
            "model_catalog": {
                "status": "live-read",
                "model_count": len(model_rows),
                "requested_sol_matches": [row for row in model_rows if row["is_requested_sol"]],
            },
            "error": None,
        }
    except (OSError, ValueError) as exc:
        return {
            "codex": executable_text,
            "agents_namespace": {"status": "unverified", "value": None},
            "task_thread": {"status": "unverified", "create_verified": False},
            "model_catalog": {"status": "unavailable", "models": []},
            "error": str(exc),
        }


def agents_rule_report(project: Path) -> dict[str, Any]:
    path = project / "AGENTS.md"
    if not path.exists():
        return {"exists": False, "conflict": False, "self_maintenance_boundary": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "exists": True,
        "conflict": any(marker in text for marker in ROUTING_MARKERS),
        "self_maintenance_boundary": "Repository Self-Maintenance Mode" in text,
    }


def doctor(project: Path, skills_root: Path, codex_bin: str, timeout_seconds: int) -> dict[str, Any]:
    root = safe_project_root(project)
    canonical = bundle_report(skills_root, CANONICAL_SKILL_NAME)
    legacy = bundle_report(skills_root, LEGACY_SKILL_NAME)
    profiles = profile_report(root)
    native = native_report(root, codex_bin, timeout_seconds)
    rules = agents_rule_report(root)
    thread = native.get("task_thread", {})
    catalog = native.get("model_catalog", {})
    checks = {
        "canonical_installed": canonical["state"] == "current",
        "legacy_installed": legacy["state"] == "current",
        "canonical_implicit_true": canonical["implicit_policy"] is True,
        "legacy_implicit_false": legacy["implicit_policy"] is False,
        "project_agents_conflict_free": rules["conflict"] is False,
        "native_thread_read_surface": (
            isinstance(thread, dict)
            and (
                thread.get("read_verified") is True
                or thread.get("status") == "read-surface-available"
            )
        ),
        "native_model_catalog_live": (
            isinstance(catalog, dict) and catalog.get("status") == "live-read"
        ),
    }
    return {
        "schema_version": "1.0",
        "status": "healthy" if all(checks.values()) else "attention-required",
        "project": str(root),
        "canonical": canonical,
        "legacy": legacy,
        "project_agent_profiles": profiles,
        "native": native,
        "project_agents_rules": rules,
        "checks": checks,
        "mutations_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Agency runtime doctor.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--skills-root", type=Path, default=Path.home() / ".agents" / "skills")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 60:
        raise ValueError("--timeout-seconds must be between 1 and 60")
    result = doctor(
        args.project,
        args.skills_root.expanduser().resolve(),
        args.codex_bin,
        args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Agency doctor failed: {exc}")
