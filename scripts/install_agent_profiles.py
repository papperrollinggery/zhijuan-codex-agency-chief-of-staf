#!/usr/bin/env python3
"""Explicitly install bounded custom-agent profiles into one chosen project."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from validate_agent_profiles import (
    PROFILE_NAMES,
    SELF_SKILL_NAMES,
    skill_name_from_file,
    validate_profile,
)


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


def rendered_profile(template: Path, skill_paths: list[Path]) -> bytes:
    text = template.read_text(encoding="utf-8").rstrip() + "\n"
    for path in skill_paths:
        text += (
            "\n[[skills.config]]\n"
            f"path = {json.dumps(str(path))}\n"
            "enabled = true\n"
        )
    return text.encode("utf-8")


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
) -> dict[str, object]:
    if target_root.is_symlink() or (target_root.exists() and not target_root.is_dir()):
        raise ValueError("agent target root must be a non-symlink directory")
    templates = source_root / "assets" / "codex_agents"
    rendered = {
        name: rendered_profile(templates / f"{name}.toml", bindings.get(name, []))
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
                validate_profile(staged, name, allow_bindings=True)
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
                validate_profile(target, name, allow_bindings=True)
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
    result = install_profiles(source_root, target_root, bindings, args.force, args.dry_run)
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
