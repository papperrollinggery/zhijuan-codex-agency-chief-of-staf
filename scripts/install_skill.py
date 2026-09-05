#!/usr/bin/env python3
"""Install the runtime pair and lightweight discovery bridge without AGENTS routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import tempfile
import uuid
from pathlib import Path


CANONICAL_SKILL_NAME = "agency-chief-of-staff"
LEGACY_SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
DISCOVERY_SKILL_NAME = "agency-discuss-plan-execute-progress-archive"
INSTALL_NAMES = (CANONICAL_SKILL_NAME, LEGACY_SKILL_NAME)
MANAGED_INSTALL_NAMES = (*INSTALL_NAMES, DISCOVERY_SKILL_NAME)
SKILL_NAME = CANONICAL_SKILL_NAME
RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "assets/discovery_bridge/skill.template.md",
    "assets/discovery_bridge/openai.template.yaml",
    "references/real-threads.md",
    "references/delivery-review.md",
    "references/long-running-work.md",
    "references/history-audit.md",
    "references/software-development.md",
    "references/user-experience.md",
    "references/model-routing-and-budget.md",
    "references/task-lifecycle.md",
    "references/team-orchestration.md",
    "references/execution-session.md",
    "references/knowledge-archiving.md",
    "assets/WORK_RECEIPT_TEMPLATE.yaml",
    "assets/DELIVERY_EVIDENCE_TEMPLATE.yaml",
    "assets/WORKER_PROTOCOL_CONTRACT.json",
    "assets/agent-routing.json",
    "assets/role-model-policy.json",
    "assets/task-state.schema.json",
    "assets/task-execution-plan.schema.json",
    "assets/team-plan.schema.json",
    "assets/progress-event.schema.json",
    "assets/knowledge-deposit.schema.json",
    "assets/execution-session.schema.json",
    "assets/execution-model-policy.json",
    "assets/lifecycle-intents.json",
    "assets/visualizations/surface-registry.json",
    "assets/visualizations/data-contract.json",
    "assets/visualizations/task-surface.html",
    "assets/visualizations/decision-surface.html",
    "assets/codex_agents/codebase-researcher.toml",
    "assets/codex_agents/technical-architect.toml",
    "assets/codex_agents/developer.toml",
    "assets/codex_agents/writer.toml",
    "assets/codex_agents/reviewer.toml",
    "assets/codex_agents/test-debugger.toml",
    "assets/codex_agents/supervisor.toml",
    "scripts/audit_historical_threads.py",
    "scripts/install_skill.py",
    "scripts/install_agent_profiles.py",
    "scripts/run_profile_compat.py",
    "scripts/configure_native_routing.py",
    "scripts/inspect_codex_models.py",
    "scripts/verify_native_task_receipt.py",
    "scripts/verify_role_route_receipt.py",
    "scripts/protocol_contract.py",
    "scripts/validate_visualization_data.py",
    "scripts/render_visualization.py",
    "scripts/resolve_role_route.py",
    "scripts/validate_agent_profiles.py",
    "scripts/agency_task.py",
    "scripts/validate_task_state.py",
    "scripts/resolve_team_plan.py",
    "scripts/prepare_team_runtime.py",
    "scripts/agency_doctor.py",
    "scripts/prepare_execution_launch.py",
    "scripts/bind_execution_session.py",
    "scripts/resolve_execution_model.py",
    "scripts/update_task_progress.py",
    "scripts/complete_task.py",
    "scripts/archive_task.py",
    "scripts/deposit_knowledge.py",
    "scripts/validate_task_archive.py",
)
DISCOVERY_RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
)
DISCOVERY_TEMPLATE_FILES = {
    "SKILL.md": "assets/discovery_bridge/skill.template.md",
    "agents/openai.yaml": "assets/discovery_bridge/openai.template.yaml",
}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def runtime_source_path(root: Path, rel: str) -> Path:
    path = root / rel
    if path.is_symlink():
        raise ValueError(f"runtime source must not be a symlink: {rel}")
    if not path.is_file():
        raise ValueError(f"runtime bundle missing file: {rel}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"runtime source escapes package root: {rel}")
    return path


def runtime_files(skill_name: str) -> tuple[str, ...]:
    if skill_name in INSTALL_NAMES:
        return RUNTIME_FILES
    if skill_name == DISCOVERY_SKILL_NAME:
        return DISCOVERY_RUNTIME_FILES
    raise ValueError(f"unsupported install name: {skill_name}")


def validate_canonical_source(root: Path) -> None:
    """Reject execution from the rendered legacy bundle before it can rewrite both installs."""
    skill = runtime_source_path(root, "SKILL.md").read_text(encoding="utf-8")
    openai = runtime_source_path(root, "agents/openai.yaml").read_text(encoding="utf-8")
    if "\nname: agency-chief-of-staff\n" not in f"\n{skill}" or (
        "allow_implicit_invocation: true" not in openai
    ):
        raise ValueError(
            "installer source is not the canonical agency-chief-of-staff bundle; "
            "run scripts/install_skill.py from the canonical bundle"
        )


def render_runtime_bytes(root: Path, rel: str, skill_name: str = SKILL_NAME) -> bytes:
    source_rel = DISCOVERY_TEMPLATE_FILES[rel] if skill_name == DISCOVERY_SKILL_NAME else rel
    source = runtime_source_path(root, source_rel)
    data = source.read_bytes()
    if skill_name in {CANONICAL_SKILL_NAME, DISCOVERY_SKILL_NAME}:
        return data
    if skill_name != LEGACY_SKILL_NAME:
        raise ValueError(f"unsupported install name: {skill_name}")

    text = data.decode("utf-8")
    if rel == "SKILL.md":
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("name:"):
                lines[index] = f"name: {LEGACY_SKILL_NAME}"
            elif line.startswith("description:"):
                description = (
                    "Legacy explicit-call compatibility entry for $zhijuan-codex-agency-"
                    "chief-of-staf; use $agency-chief-of-staff for new work."
                )
                lines[index] = "description: " + json.dumps(description)
        text = "\n".join(lines) + "\n"
    elif rel == "agents/openai.yaml":
        lines = text.splitlines()
        replacements = {
            "display_name:": '  display_name: "Zhijuan Codex 幕僚长（旧入口兼容）"',
            "short_description:": (
                '  short_description: "旧显式调用兼容入口；新任务请使用 agency-chief-of-staff"'
            ),
        }
        for index, line in enumerate(lines):
            stripped = line.strip()
            for key, replacement in replacements.items():
                if stripped.startswith(key):
                    lines[index] = replacement
        text = "\n".join(lines) + "\n"
        text = text.replace(
            f'default_prompt: "使用 ${CANONICAL_SKILL_NAME}',
            f'default_prompt: "使用 ${LEGACY_SKILL_NAME}',
        ).replace("allow_implicit_invocation: true", "allow_implicit_invocation: false")
    return text.encode("utf-8")


def runtime_manifest(root: Path, skill_name: str = SKILL_NAME) -> dict[str, str]:
    return {
        rel: digest_bytes(render_runtime_bytes(root, rel, skill_name))
        for rel in runtime_files(skill_name)
    }


def installed_manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError(f"installed bundle contains a symlink: {relative}")
        if path.is_file():
            manifest[str(relative)] = digest(path)
    return manifest


def runtime_permission_report(root: Path, skill_name: str = SKILL_NAME) -> dict[str, object]:
    """Read back the exact sealed file/directory surface for one installed bundle."""
    expected_files = set(runtime_files(skill_name))
    expected_directories = {"."}
    for relative in expected_files:
        parent = Path(relative).parent
        while str(parent) not in {"", "."}:
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    if not root.exists():
        return {"current": False, "mismatches": ["missing-root"]}
    if root.is_symlink():
        raise ValueError("installed runtime root must be a non-symlink directory")
    if not root.is_dir():
        return {"current": False, "mismatches": ["root-not-directory"]}
    actual_files: set[str] = set()
    actual_directories = {"."}
    mismatches: list[str] = []
    if stat.S_IMODE(root.stat().st_mode) != 0o555:
        mismatches.append("mode:.:expected-0555")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"installed bundle contains a symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            actual_directories.add(relative)
            if stat.S_IMODE(info.st_mode) != 0o555:
                mismatches.append(f"mode:{relative}:expected-0555")
        elif stat.S_ISREG(info.st_mode):
            actual_files.add(relative)
            if stat.S_IMODE(info.st_mode) != 0o444:
                mismatches.append(f"mode:{relative}:expected-0444")
        else:
            mismatches.append(f"unsupported:{relative}")
    for relative in sorted(expected_files - actual_files):
        mismatches.append(f"missing-file:{relative}")
    for relative in sorted(actual_files - expected_files):
        mismatches.append(f"extra-file:{relative}")
    for relative in sorted(expected_directories - actual_directories):
        mismatches.append(f"missing-directory:{relative}")
    for relative in sorted(actual_directories - expected_directories):
        mismatches.append(f"extra-directory:{relative}")
    return {"current": not mismatches, "mismatches": mismatches}


def runtime_permissions_current(root: Path, skill_name: str = SKILL_NAME) -> bool:
    return runtime_permission_report(root, skill_name)["current"] is True


def copy_runtime(
    source: Path, target: Path, skill_name: str = SKILL_NAME
) -> None:
    for rel in runtime_files(skill_name):
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(render_runtime_bytes(source, rel, skill_name))


def seal_runtime_tree(root: Path) -> None:
    """Make an installed Runtime read-only so Python cannot create executable caches."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("runtime tree must be a non-symlink directory")
    directories = [root]
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"runtime tree contains a symlink: {path.relative_to(root)}")
        if path.is_dir():
            directories.append(path)
        elif path.is_file():
            path.chmod(0o444)
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        directory.chmod(0o555)


def make_runtime_tree_writable(root: Path) -> None:
    """Unseal an installer-owned staging or backup tree immediately before removal."""
    if root.is_symlink() or not root.is_dir():
        return
    root.chmod(0o700)
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)


def best_effort_remove(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            make_runtime_tree_writable(path)
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def replace_many_from_staging(source: Path, targets: dict[str, Path]) -> None:
    """Replace the runtime pair and discovery bridge in one rollback transaction."""
    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    promoted: set[str] = set()
    committed = False
    try:
        for skill_name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
            )
            staged[skill_name] = staging
            copy_runtime(source, staging, skill_name)
            seal_runtime_tree(staging)
            if installed_manifest(staging) != runtime_manifest(source, skill_name):
                raise RuntimeError(f"staged runtime manifest mismatch: {skill_name}")
            if not runtime_permissions_current(staging, skill_name):
                raise RuntimeError(f"staged runtime permission mismatch: {skill_name}")

        for skill_name, target in targets.items():
            if target.exists():
                backup = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
                target.rename(backup)
                backups[skill_name] = backup

        for skill_name, target in targets.items():
            staged[skill_name].rename(target)
            promoted.add(skill_name)
            if installed_manifest(target) != runtime_manifest(source, skill_name):
                raise RuntimeError(f"installed runtime manifest mismatch: {skill_name}")
            if not runtime_permissions_current(target, skill_name):
                raise RuntimeError(f"installed runtime permission mismatch: {skill_name}")
        committed = True
    except Exception:
        for skill_name, target in reversed(tuple(targets.items())):
            if skill_name in promoted and target.exists():
                best_effort_remove(target)
            backup = backups.get(skill_name)
            if backup is not None and backup.exists() and not target.exists():
                backup.rename(target)
        raise
    finally:
        for staging in staged.values():
            if staging.exists():
                best_effort_remove(staging)

    if committed:
        for backup in backups.values():
            if backup.exists():
                best_effort_remove(backup)


def replace_from_staging(
    source: Path, target: Path, skill_name: str = SKILL_NAME
) -> None:
    """Compatibility helper for focused installer tests."""
    effective_name = target.name if target.name in MANAGED_INSTALL_NAMES else skill_name
    replace_many_from_staging(source, {effective_name: target})


def emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {result['target_root']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install canonical/legacy runtime bundles and the discovery bridge. This command "
            "never reads or modifies project or global AGENTS.md files."
        )
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="Directory containing user skills. Defaults to ~/.agents/skills.",
    )
    parser.add_argument("--force", action="store_true", help="Replace a differing pair.")
    parser.add_argument("--dry-run", action="store_true", help="Check without copying.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    raw_target_root = args.target_root.expanduser()
    try:
        validate_canonical_source(source)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {
            "source": str(source),
            "target_root": str(raw_target_root),
            "status": "conflict",
            "message": str(exc),
            "agents_md_touched": False,
        }
        emit(result, args.json)
        raise SystemExit(1)
    if raw_target_root.is_symlink():
        result = {
            "source": str(source),
            "target_root": str(raw_target_root),
            "status": "conflict",
            "message": "target root is a symlink; refusing to follow it",
            "agents_md_touched": False,
        }
        emit(result, args.json)
        raise SystemExit(1)
    target_root = raw_target_root.resolve()
    targets = {name: target_root / name for name in MANAGED_INSTALL_NAMES}
    expected = {name: runtime_manifest(source, name) for name in MANAGED_INSTALL_NAMES}

    for name, target in targets.items():
        if target.is_symlink():
            result = {
                "source": str(source),
                "target_root": str(target_root),
                "status": "conflict",
                "message": f"target is a symlink; refusing to replace it: {name}",
                "agents_md_touched": False,
            }
            emit(result, args.json)
            raise SystemExit(1)

    states: dict[str, str] = {}
    permissions_before: dict[str, dict[str, object]] = {}
    try:
        for name, target in targets.items():
            if not target.exists():
                states[name] = "missing"
                permissions_before[name] = {
                    "current": False,
                    "mismatches": ["missing-root"],
                }
            else:
                permission_report = runtime_permission_report(target, name)
                permissions_before[name] = permission_report
                states[name] = (
                    "current"
                    if installed_manifest(target) == expected[name]
                    and permission_report["current"] is True
                    else "different"
                )
    except (OSError, ValueError) as exc:
        result = {
            "source": str(source),
            "target_root": str(target_root),
            "status": "conflict",
            "message": f"unsafe or unreadable target bundle: {exc}",
            "agents_md_touched": False,
        }
        emit(result, args.json)
        raise SystemExit(1)

    if all(state == "current" for state in states.values()):
        status = "already-installed"
    elif args.dry_run:
        status = "would-install" if all(v == "missing" for v in states.values()) else "would-replace"
    elif any(state != "missing" for state in states.values()) and not args.force:
        result = {
            "source": str(source),
            "target_root": str(target_root),
            "status": "conflict",
            "states": states,
            "message": (
                "installed runtime set differs; re-run with --force to replace the "
                "canonical/legacy pair and discovery bridge"
            ),
            "agents_md_touched": False,
        }
        emit(result, args.json)
        raise SystemExit(1)
    else:
        status = "installed" if all(v == "missing" for v in states.values()) else "replaced"
        replace_many_from_staging(source, targets)
        for name, target in targets.items():
            if installed_manifest(target) != expected[name]:
                raise SystemExit(f"installed runtime manifest does not match source: {name}")
            if not runtime_permissions_current(target, name):
                raise SystemExit(f"installed runtime permissions do not match source: {name}")

    result = {
        "source": str(source),
        "target_root": str(target_root),
        "targets": {name: str(path) for name, path in targets.items()},
        "status": status,
        "states_before": states,
        "permissions_before": permissions_before,
        "runtime_files_per_bundle": len(RUNTIME_FILES),
        "runtime_file_counts": {
            name: len(runtime_files(name)) for name in MANAGED_INSTALL_NAMES
        },
        "manifests": expected,
        "agents_md_touched": False,
    }
    emit(result, args.json)


if __name__ == "__main__":
    main()
