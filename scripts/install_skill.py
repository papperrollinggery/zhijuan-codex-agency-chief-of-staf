#!/usr/bin/env python3
"""Install the minimal runtime skill bundle without touching project guidance."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
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


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def runtime_source_path(root: Path, rel: str) -> Path:
    path = root / rel
    if path.is_symlink():
        raise ValueError(f"runtime source must not be a symlink: {rel}")
    if not path.is_file():
        raise ValueError(f"runtime bundle missing file: {rel}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"runtime source escapes package root: {rel}")
    return path


def runtime_manifest(root: Path) -> dict[str, str]:
    return {rel: digest(runtime_source_path(root, rel)) for rel in RUNTIME_FILES}


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


def copy_runtime(source: Path, target: Path) -> None:
    for rel in RUNTIME_FILES:
        source_path = runtime_source_path(source, rel)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def best_effort_remove(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def replace_from_staging(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
    )
    backup: Path | None = None
    committed = False
    staging_promoted = False
    try:
        copy_runtime(source, staging)
        if installed_manifest(staging) != runtime_manifest(source):
            raise RuntimeError("staged runtime manifest does not match source")

        if target.exists():
            backup_candidate = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
            target.rename(backup_candidate)
            backup = backup_candidate
        staging.rename(target)
        staging_promoted = True
        if installed_manifest(target) != runtime_manifest(source):
            raise RuntimeError("installed runtime manifest does not match source")
        committed = True
    except Exception:
        if backup is not None and backup.exists():
            failed_target: Path | None = None
            if target.exists():
                failed_target = target.parent / f".{target.name}.failed-{uuid.uuid4().hex}"
                target.rename(failed_target)
            backup.rename(target)
            if failed_target is not None:
                best_effort_remove(failed_target)
        elif staging_promoted and target.exists():
            best_effort_remove(target)
        raise
    finally:
        if staging.exists():
            best_effort_remove(staging)

    # The replacement is already committed and verified. Backup cleanup must never
    # turn a valid install into a failed rollback from a partially deleted backup.
    if committed and backup is not None and backup.exists():
        best_effort_remove(backup)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install the minimal runtime bundle. This command never reads or modifies "
            "project or global AGENTS.md files."
        )
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="Directory containing user skills. Defaults to ~/.agents/skills.",
    )
    parser.add_argument("--name", default=SKILL_NAME, help="Installed folder name.")
    parser.add_argument("--force", action="store_true", help="Replace a differing install.")
    parser.add_argument("--dry-run", action="store_true", help="Check without copying.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    args = parser.parse_args()

    if not args.name or Path(args.name).name != args.name or args.name in {".", ".."}:
        parser.error("--name must be one folder name without path separators")

    source = Path(__file__).resolve().parents[1]
    target = args.target_root.expanduser().resolve() / args.name
    source_manifest = runtime_manifest(source)

    if target.is_symlink() and target.resolve() != source.resolve():
        result = {
            "source": str(source),
            "target": str(target),
            "status": "conflict",
            "runtime_files": len(RUNTIME_FILES),
            "message": "target is a symlink; refusing to replace or mutate its destination",
            "agents_md_touched": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["message"])
        raise SystemExit(1)

    if source.resolve() == target.resolve():
        status = "source-is-target"
    elif not target.exists():
        status = "would-install" if args.dry_run else "installed"
    else:
        try:
            current_manifest = installed_manifest(target)
        except (OSError, ValueError) as exc:
            result = {
                "source": str(source),
                "target": str(target),
                "status": "conflict",
                "runtime_files": len(RUNTIME_FILES),
                "message": f"unsafe or unreadable target bundle: {exc}",
                "agents_md_touched": False,
            }
            print(
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else result["message"]
            )
            raise SystemExit(1)
        if current_manifest == source_manifest:
            status = "already-installed"
        elif not args.force:
            result = {
                "source": str(source),
                "target": str(target),
                "status": "conflict",
                "runtime_files": len(RUNTIME_FILES),
                "message": "target exists and differs; re-run with --force to replace it",
                "agents_md_touched": False,
            }
            print(
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else result["message"]
            )
            raise SystemExit(1)
        else:
            status = "would-replace" if args.dry_run else "replaced"

    if not args.dry_run and status in {"installed", "replaced"}:
        replace_from_staging(source, target)
        if installed_manifest(target) != source_manifest:
            raise SystemExit("installed runtime manifest does not match source")

    result = {
        "source": str(source),
        "target": str(target),
        "status": status,
        "runtime_files": len(RUNTIME_FILES),
        "manifest": source_manifest,
        "agents_md_touched": False,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{status}: {target}")


if __name__ == "__main__":
    main()
