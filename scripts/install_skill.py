#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
from pathlib import Path

SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
EXCLUDED_DIRS = {".git", ".codex", "__pycache__", ".pytest_cache", "agency-thread-pilot"}
EXCLUDED_FILES = {".DS_Store"}
BEGIN_ROUTING_MARKER = f"<!-- BEGIN {SKILL_NAME} routing -->"
END_ROUTING_MARKER = f"<!-- END {SKILL_NAME} routing -->"


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


def routing_snippet(src: Path) -> str:
    text = (src / "references" / "AGENTS_ROUTING_SNIPPET.md").read_text(
        encoding="utf-8"
    )
    start = text.find("```markdown")
    if start == -1:
        raise SystemExit("AGENTS routing snippet missing markdown fence")
    start = text.find("\n", start)
    end = text.find("```", start + 1)
    if start == -1 or end == -1:
        raise SystemExit("AGENTS routing snippet fence is malformed")
    snippet = text[start + 1 : end].strip()
    if "COS_BOOT_RECEIPT" not in snippet or SKILL_NAME not in snippet:
        raise SystemExit("AGENTS routing snippet is missing required routing terms")
    return f"{BEGIN_ROUTING_MARKER}\n{snippet}\n{END_ROUTING_MARKER}\n"


def upsert_agents_routing(path: Path, block: str, dry_run: bool) -> dict[str, str]:
    result = {"path": str(path), "status": ""}
    exists = path.exists()
    text = path.read_text(encoding="utf-8") if exists else ""

    has_begin = BEGIN_ROUTING_MARKER in text
    has_end = END_ROUTING_MARKER in text
    if has_begin != has_end:
        result["status"] = "conflict"
        result["message"] = "AGENTS routing markers are incomplete"
        return result

    if has_begin and has_end:
        before, rest = text.split(BEGIN_ROUTING_MARKER, 1)
        current, after = rest.split(END_ROUTING_MARKER, 1)
        current_block = f"{BEGIN_ROUTING_MARKER}{current}{END_ROUTING_MARKER}"
        if current_block.strip() == block.strip():
            result["status"] = "unchanged"
            return result
        new_text = (
            (before.rstrip() + "\n\n" if before.strip() else "")
            + block
            + ("\n" + after.lstrip() if after.strip() else "")
        )
        result["status"] = "would-update" if dry_run else "updated"
    elif block.strip() in text:
        result["status"] = "unchanged"
        return result
    elif exists:
        new_text = text.rstrip() + "\n\n" + block
        result["status"] = "would-append" if dry_run else "appended"
    else:
        new_text = block
        result["status"] = "would-create" if dry_run else "created"

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
    return result


def agents_routing_targets(scope: str, project_root: Path) -> list[Path]:
    targets = []
    if scope in {"project", "both"}:
        targets.append(project_root.expanduser().resolve() / "AGENTS.md")
    if scope in {"global", "both"}:
        targets.append(Path.home() / ".codex" / "AGENTS.md")
    return targets


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
    parser.add_argument(
        "--agents-routing",
        choices=("none", "project", "global", "both"),
        default="none",
        help=(
            "Optionally install the AGENTS.md routing snippet. Defaults to none. "
            "Use project for ./AGENTS.md, global for ~/.codex/AGENTS.md, or both."
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root used with --agents-routing project/both. Defaults to cwd.",
    )
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

    if args.agents_routing != "none":
        block = routing_snippet(src_real)
        result["agents_routing"] = [
            upsert_agents_routing(target, block, args.dry_run)
            for target in agents_routing_targets(args.agents_routing, args.project_root)
        ]
        conflicts = [
            item for item in result["agents_routing"] if item["status"] == "conflict"
        ]
        if conflicts:
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for item in conflicts:
                    print(f"conflict: {item['path']}: {item['message']}")
            raise SystemExit(1)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {dst}")
        for item in result.get("agents_routing", []):
            print(f"agents-routing {item['status']}: {item['path']}")


if __name__ == "__main__":
    main()
