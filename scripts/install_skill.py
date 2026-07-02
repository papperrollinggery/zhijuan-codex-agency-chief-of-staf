#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
from pathlib import Path

SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
EXCLUDED_DIRS = {".git", ".codex", "__pycache__", ".pytest_cache", "agency-thread-pilot"}
EXCLUDED_FILES = {".DS_Store"}


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts) or path.name in EXCLUDED_FILES


def iter_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not should_skip(path.relative_to(root))
    )


def digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): digest(path)
        for path in iter_files(root)
    }


def copy_skill(src: Path, dst: Path) -> None:
    for path in iter_files(src):
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install this skill bundle into a Codex user skills directory."
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="Directory containing user skills. Defaults to ~/.agents/skills.",
    )
    parser.add_argument("--name", default=SKILL_NAME, help="Installed skill folder name.")
    parser.add_argument("--force", action="store_true", help="Overwrite a differing install.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without copying.")
    parser.add_argument("--json", action="store_true", help="Emit JSON result.")
    args = parser.parse_args()

    src = Path(__file__).resolve().parents[1]
    dst = (args.target_root / args.name).expanduser().resolve()
    src_real = src.resolve()
    result = {
        "source": str(src_real),
        "target": str(dst),
        "status": "",
        "files": len(iter_files(src_real)),
    }

    if src_real == dst:
        result["status"] = "source-is-target"
    elif dst.exists():
        src_manifest = manifest(src_real)
        dst_manifest = manifest(dst)
        if src_manifest != dst_manifest:
            if not args.force:
                result["status"] = "conflict"
                result["message"] = "target exists and differs; re-run with --force to overwrite"
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print(result["message"])
                raise SystemExit(1)
            result["status"] = "overwritten"
        else:
            result["status"] = "already-installed"
    else:
        result["status"] = "would-install" if args.dry_run else "installed"

    if not args.dry_run and result["status"] in {"installed", "overwritten"}:
        if dst.exists():
            shutil.rmtree(dst)
        dst.mkdir(parents=True, exist_ok=True)
        copy_skill(src_real, dst)
    elif not args.dry_run and result["status"] == "source-is-target":
        pass

    if dst.exists():
        result["installed_files"] = len(iter_files(dst))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {dst}")


if __name__ == "__main__":
    main()
