#!/usr/bin/env python3
"""Install canonical and legacy-compatible runtime bundles without AGENTS routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path


CANONICAL_SKILL_NAME = "agency-chief-of-staff"
LEGACY_SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
INSTALL_NAMES = (CANONICAL_SKILL_NAME, LEGACY_SKILL_NAME)
SKILL_NAME = CANONICAL_SKILL_NAME
RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/real-threads.md",
    "references/delivery-review.md",
    "references/long-running-work.md",
    "references/history-audit.md",
    "assets/WORK_RECEIPT_TEMPLATE.yaml",
    "assets/DELIVERY_EVIDENCE_TEMPLATE.yaml",
    "scripts/audit_historical_threads.py",
)


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


def render_runtime_bytes(root: Path, rel: str, skill_name: str = SKILL_NAME) -> bytes:
    source = runtime_source_path(root, rel)
    data = source.read_bytes()
    if skill_name == CANONICAL_SKILL_NAME:
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
                    "chief-of-staf. Use only when the user explicitly invokes that exact "
                    "slug; new and implicit use must select $agency-chief-of-staff."
                )
                lines[index] = "description: " + json.dumps(description)
        text = "\n".join(lines) + "\n"
    elif rel == "agents/openai.yaml":
        text = text.replace(
            'display_name: "Zhijuan 结果负责型 Codex 幕僚长"',
            'display_name: "Zhijuan Codex 幕僚长（旧入口兼容）"',
        ).replace(
            'short_description: "从目标研究到执行、验证、独立审核与最终交付的结果闭环"',
            'short_description: "旧显式调用兼容入口；新任务请使用 agency-chief-of-staff"',
        ).replace(
            f'default_prompt: "使用 ${CANONICAL_SKILL_NAME}',
            f'default_prompt: "使用 ${LEGACY_SKILL_NAME}',
        ).replace("allow_implicit_invocation: true", "allow_implicit_invocation: false")
    return text.encode("utf-8")


def runtime_manifest(root: Path, skill_name: str = SKILL_NAME) -> dict[str, str]:
    return {
        rel: digest_bytes(render_runtime_bytes(root, rel, skill_name))
        for rel in RUNTIME_FILES
    }


def installed_manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"installed bundle contains a symlink: {path.relative_to(root)}")
        if path.is_file() and "__pycache__" not in path.parts:
            manifest[str(path.relative_to(root))] = digest(path)
    return manifest


def copy_runtime(
    source: Path, target: Path, skill_name: str = SKILL_NAME
) -> None:
    for rel in RUNTIME_FILES:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(render_runtime_bytes(source, rel, skill_name))


def best_effort_remove(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def replace_many_from_staging(source: Path, targets: dict[str, Path]) -> None:
    """Replace every managed bundle as one rollback-capable pair transaction."""
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
            if installed_manifest(staging) != runtime_manifest(source, skill_name):
                raise RuntimeError(f"staged runtime manifest mismatch: {skill_name}")

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
    effective_name = target.name if target.name in INSTALL_NAMES else skill_name
    replace_many_from_staging(source, {effective_name: target})


def emit(result: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {result['target_root']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install canonical and legacy-compatible runtime bundles. This command "
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
    targets = {name: target_root / name for name in INSTALL_NAMES}
    expected = {name: runtime_manifest(source, name) for name in INSTALL_NAMES}

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
    try:
        for name, target in targets.items():
            if not target.exists():
                states[name] = "missing"
            elif installed_manifest(target) == expected[name]:
                states[name] = "current"
            else:
                states[name] = "different"
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
    elif any(state != "missing" for state in states.values()) and not args.force:
        result = {
            "source": str(source),
            "target_root": str(target_root),
            "status": "conflict",
            "states": states,
            "message": "installed pair differs; re-run with --force to replace both bundles",
            "agents_md_touched": False,
        }
        emit(result, args.json)
        raise SystemExit(1)
    elif args.dry_run:
        status = "would-install" if all(v == "missing" for v in states.values()) else "would-replace"
    else:
        status = "installed" if all(v == "missing" for v in states.values()) else "replaced"
        replace_many_from_staging(source, targets)
        for name, target in targets.items():
            if installed_manifest(target) != expected[name]:
                raise SystemExit(f"installed runtime manifest does not match source: {name}")

    result = {
        "source": str(source),
        "target_root": str(target_root),
        "targets": {name: str(path) for name, path in targets.items()},
        "status": status,
        "states_before": states,
        "runtime_files_per_bundle": len(RUNTIME_FILES),
        "manifests": expected,
        "agents_md_touched": False,
    }
    emit(result, args.json)


if __name__ == "__main__":
    main()
