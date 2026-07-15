#!/usr/bin/env python3
"""Explicitly install bounded custom-agent profiles into one chosen project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

from resolve_role_route import REASONING_LEVELS
from validate_agent_profiles import (
    PROFILE_NAMES,
    SELF_SKILL_NAMES,
    skill_name_from_file,
    validate_profile,
)


MAX_ROUTE_PLAN_BYTES = 1024 * 1024
MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")


def parse_binding(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--skill must use ROLE=/absolute/path/to/SKILL.md")
    role, raw_path = value.split("=", 1)
    if role not in PROFILE_NAMES:
        raise ValueError(f"unknown agent role in --skill: {role}")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("--skill paths must be absolute")
    name = skill_name_from_file(path)
    if name in SELF_SKILL_NAMES:
        raise ValueError(f"recursive self-skill binding is forbidden: {name}")
    return role, path.resolve()


def rendered_profile(
    template: Path,
    skill_paths: list[Path],
    route: tuple[str, str] | None = None,
) -> bytes:
    text = template.read_text(encoding="utf-8").rstrip() + "\n"
    if route is not None:
        model, reasoning = route
        text += (
            "\n"
            f"model = {json.dumps(model)}\n"
            f"model_reasoning_effort = {json.dumps(reasoning)}\n"
        )
    for path in skill_paths:
        text += (
            "\n[[skills.config]]\n"
            f"path = {json.dumps(str(path))}\n"
            "enabled = true\n"
        )
    return text.encode("utf-8")


def read_route_plan(path: Path) -> tuple[dict[str, object], str]:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError("--route-plan must be an absolute path")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(expanded, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("route plan must be a single-link regular file")
        if before.st_size > MAX_ROUTE_PLAN_BYTES:
            raise ValueError("route plan exceeds 1 MiB")
        chunks: list[bytes] = []
        remaining = MAX_ROUTE_PLAN_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(data) > MAX_ROUTE_PLAN_BYTES:
            raise ValueError("route plan exceeds 1 MiB")
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("route plan changed while it was read")
        public = os.stat(expanded, follow_symlinks=False)
        if (public.st_dev, public.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("route plan path identity changed while it was read")
    finally:
        os.close(descriptor)
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("route plan must be valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("route plan must be a JSON object")
    return parsed, hashlib.sha256(data).hexdigest()


def route_bindings_from_plan(plan: dict[str, object]) -> dict[str, tuple[str, str]]:
    claims = plan.get("claims")
    if (
        plan.get("schema_version") != 2
        or plan.get("status") != "plan-only"
        or plan.get("route_mode") != "direct"
        or not isinstance(claims, dict)
        or claims.get("catalog_live_readback_verified") is not True
        or claims.get("catalog_provenance_locally_consistent") is not True
        or claims.get("accepted") is not False
        or claims.get("confirmed") is not False
    ):
        raise ValueError(
            "route plan is not a schema-consistent unaccepted direct plan"
        )
    delegated = plan.get("delegated")
    if not isinstance(delegated, list) or not delegated:
        raise ValueError("route plan has no delegated roles")
    result: dict[str, tuple[str, str]] = {}
    for entry in delegated:
        if not isinstance(entry, dict):
            raise ValueError("route plan delegated entry must be an object")
        role = entry.get("role")
        model = entry.get("model")
        reasoning = entry.get("reasoning")
        contract = entry.get("dispatch_contract")
        if not isinstance(role, str) or role not in PROFILE_NAMES or role in result:
            raise ValueError("route plan has an unknown or duplicate role")
        if entry.get("provider") != "openai" or entry.get("route_state") != "planned":
            raise ValueError(f"route plan role is not an available OpenAI route: {role}")
        if not isinstance(model, str) or not MODEL_ID_RE.fullmatch(model):
            raise ValueError(f"route plan model id is invalid: {role}")
        if not isinstance(reasoning, str) or reasoning not in REASONING_LEVELS:
            raise ValueError(f"route plan reasoning is invalid: {role}")
        if entry.get("fork_turns") != "none" or not isinstance(contract, dict):
            raise ValueError(f"route plan does not isolate the role: {role}")
        arguments = contract.get("arguments")
        if (
            contract.get("namespace") != "agents"
            or not isinstance(arguments, dict)
            or arguments
            != {
                "model": model,
                "reasoning_effort": reasoning,
                "fork_turns": "none",
            }
        ):
            raise ValueError(f"route plan dispatch contract mismatch: {role}")
        result[role] = (model, reasoning)
    return result


def best_effort_remove(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        return False
    return not path.exists() and not path.is_symlink()


def safe_target_root(raw_target_root: Path) -> Path:
    expanded = raw_target_root.expanduser()
    if not expanded.is_absolute():
        raise ValueError("agent target root must be an absolute project .codex/agents path")
    absolute = expanded.absolute()
    if absolute.name != "agents" or absolute.parent.name != ".codex":
        raise ValueError("agent target root must end with project/.codex/agents")
    project_root = absolute.parent.parent
    for component in (project_root, absolute.parent, absolute):
        if component.is_symlink():
            raise ValueError(
                f"agent target path must not traverse a symlink: {component}"
            )
    resolved_project = project_root.resolve(strict=False)
    resolved_target = absolute.resolve(strict=False)
    if resolved_target != resolved_project / ".codex" / "agents":
        raise ValueError("agent target escaped the explicit project .codex/agents path")
    return resolved_target


def install_profiles(
    source_root: Path,
    target_root: Path,
    bindings: dict[str, list[Path]],
    force: bool,
    dry_run: bool,
    routes: dict[str, tuple[str, str]] | None = None,
    route_plan_sha256: str | None = None,
) -> dict[str, object]:
    if target_root.is_symlink() or (target_root.exists() and not target_root.is_dir()):
        raise ValueError("agent target root must be a non-symlink directory")
    templates = source_root / "assets" / "codex_agents"
    routes = routes or {}
    rendered = {
        name: rendered_profile(
            templates / f"{name}.toml",
            bindings.get(name, []),
            routes.get(name),
        )
        for name in PROFILE_NAMES
    }
    states: dict[str, str] = {}
    for name, content in rendered.items():
        target = target_root / f"{name}.toml"
        if target.is_symlink():
            raise ValueError(f"agent target must not be a symlink: {target.name}")
        if not target.exists():
            states[name] = "missing"
        elif not target.is_file():
            raise ValueError(f"agent target must be a regular file: {target.name}")
        elif target.read_bytes() == content:
            states[name] = "current"
        else:
            states[name] = "different"
    if all(state == "current" for state in states.values()):
        status = "already-installed"
    elif any(state == "different" for state in states.values()) and not force:
        raise ValueError("agent profiles differ; re-run with --force to replace managed files")
    elif dry_run:
        status = "would-install" if all(state == "missing" for state in states.values()) else "would-replace"
    else:
        target_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".agency-profiles.staging-", dir=target_root.parent))
        backups: dict[str, Path] = {}
        promoted: set[str] = set()
        try:
            for name, content in rendered.items():
                staged = staging / f"{name}.toml"
                staged.write_bytes(content)
                validate_profile(
                    staged,
                    name,
                    allow_bindings=True,
                    expected_route=routes.get(name),
                )
            for name in PROFILE_NAMES:
                target = target_root / f"{name}.toml"
                if target.exists():
                    backup = target_root / f".{name}.toml.backup-{uuid.uuid4().hex}"
                    target.rename(backup)
                    backups[name] = backup
            for name in PROFILE_NAMES:
                target = target_root / f"{name}.toml"
                (staging / f"{name}.toml").rename(target)
                promoted.add(name)
                validate_profile(
                    target,
                    name,
                    allow_bindings=True,
                    expected_route=routes.get(name),
                )
        except Exception as exc:
            recovery_errors: list[str] = []
            for name in reversed(PROFILE_NAMES):
                target = target_root / f"{name}.toml"
                if name in promoted and target.exists():
                    if not best_effort_remove(target):
                        recovery_errors.append(f"remove promoted {target.name}")
                backup = backups.get(name)
                if backup is not None and backup.exists() and not target.exists():
                    try:
                        backup.rename(target)
                    except OSError:
                        recovery_errors.append(f"restore backup {target.name}")
            if recovery_errors:
                raise RuntimeError(
                    "agent profile rollback is incomplete: " + ", ".join(recovery_errors)
                ) from exc
            raise
        finally:
            best_effort_remove(staging)
        cleanup_errors: list[str] = []
        for backup in backups.values():
            if not best_effort_remove(backup):
                cleanup_errors.append(backup.name)
        if cleanup_errors:
            raise RuntimeError(
                "agent profiles are active but backup cleanup failed: "
                + ", ".join(cleanup_errors)
            )
        status = "installed" if all(state == "missing" for state in states.values()) else "replaced"
    return {
        "status": status,
        "target_root": str(target_root),
        "states_before": states,
        "profiles": list(PROFILE_NAMES),
        "skill_bindings": {
            role: [str(path) for path in paths] for role, paths in bindings.items()
        },
        "route_bindings": {
            role: {"model": route[0], "model_reasoning_effort": route[1]}
            for role, route in sorted(routes.items())
        },
        "route_plan_sha256": route_plan_sha256,
        "route_plan_attestation": (
            "caller-asserted-unverified" if routes else None
        ),
        "route_state": "configured-unverified" if routes else "inherited-unverified",
        "self_skill_bindings": False,
        "agents_md_touched": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly install project custom-agent profiles. No default target is "
            "provided, and this command never reads or writes AGENTS.md."
        )
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        required=True,
        help="Exact project .codex/agents directory to manage.",
    )
    parser.add_argument(
        "--route-plan",
        type=Path,
        help=(
            "Absolute resolver JSON that the caller freshly generated with "
            "--verify-live-catalog. The installer validates its schema and binds its "
            "hash but does not independently re-run the live attestation. "
            "Selected profiles receive exact model and reasoning overrides; spawn/runtime "
            "still require independent readback."
        ),
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Optional repeatable ROLE=/absolute/path/to/SKILL.md binding.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[1]
    target_root = safe_target_root(args.target_root)
    bindings: dict[str, list[Path]] = {}
    seen: set[tuple[str, Path]] = set()
    for raw in args.skill:
        role, path = parse_binding(raw)
        item = (role, path)
        if item in seen:
            raise ValueError(f"duplicate --skill binding: {raw}")
        seen.add(item)
        bindings.setdefault(role, []).append(path)
    routes: dict[str, tuple[str, str]] = {}
    route_plan_sha256: str | None = None
    if args.route_plan is not None:
        route_plan, route_plan_sha256 = read_route_plan(args.route_plan)
        routes = route_bindings_from_plan(route_plan)
    result = install_profiles(
        source_root,
        target_root,
        bindings,
        args.force,
        args.dry_run,
        routes,
        route_plan_sha256,
    )
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else f"{result['status']}: {result['target_root']}"
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Agent profile install failed: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
