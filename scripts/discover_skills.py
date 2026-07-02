#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

DEFAULT_PATHS = [
    Path.home() / ".agents" / "skills",
    Path.cwd() / ".agents" / "skills",
    Path("/etc/codex/skills"),
]

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.S)


def parse_skill(path: Path, root: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = FRONTMATTER.search(text)
    data = {"path": str(path), "root": str(root), "name": "", "description": ""}
    if fm:
        for line in fm.group(1).splitlines():
            if line.startswith("name:"):
                data["name"] = line.split(":", 1)[1].strip().strip('"')
            if line.startswith("description:"):
                data["description"] = line.split(":", 1)[1].strip().strip('"')
    return data


def discover(paths: list[Path], query: str) -> list[dict]:
    seen = set()
    results = []
    terms = [term.lower() for term in query.split() if term.strip()]

    for root in paths:
        if not root.exists():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            real = skill_md.resolve()
            if real in seen:
                continue
            seen.add(real)
            item = parse_skill(skill_md, root)
            haystack = " ".join(
                [item["path"], item["name"], item["description"]]
            ).lower()
            if terms and not all(term in haystack for term in terms):
                continue
            results.append(item)
    return results


def print_text(items: list[dict]) -> None:
    print("# SKILL INVENTORY\n")
    for item in items:
        print(f"- name: {item['name']}")
        print(f"  path: {item['path']}")
        print(f"  description: {item['description']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover local Codex skills.")
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        help="Skill root to scan. May be repeated. Defaults to user, project, and /etc roots.",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Whitespace terms that must appear in path, name, or description.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum results.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    paths = args.root if args.root else DEFAULT_PATHS
    items = discover(paths, args.query)
    if args.limit >= 0:
        items = items[: args.limit]

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print_text(items)


if __name__ == "__main__":
    main()
