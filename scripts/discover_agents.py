#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from toml_compat import loads as toml_loads

DEFAULT_PATHS = [
    Path.cwd() / ".codex" / "agents",
    Path.home() / ".codex" / "agents",
]


def parse_agent(path: Path, root: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    data = toml_loads(text)
    return {
        "path": str(path),
        "root": str(root),
        "name": str(data.get("name", "")),
        "description": str(data.get("description", "")),
    }


def discover(paths: list[Path], query: str) -> list[dict]:
    seen = set()
    results = []
    terms = [term.lower() for term in query.split() if term.strip()]

    for root in paths:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.toml")):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            item = parse_agent(path, root)
            haystack = " ".join(
                [item["path"], item["name"], item["description"]]
            ).lower()
            if terms and not all(term in haystack for term in terms):
                continue
            results.append(item)
    return results


def print_text(items: list[dict]) -> None:
    print("# AGENT INVENTORY\n")
    for item in items:
        print(f"- path: {item['path']}")
        print(f"  name = {item['name']!r}")
        print(f"  description = {item['description']!r}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover local Codex agent TOML files."
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        help="Agent directory to scan. May be repeated. Defaults to project then user agents.",
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
