#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

from toml_compat import TOMLDecodeError, loads as toml_loads

TOKEN = re.compile(r"[\w:-]+", re.UNICODE)
FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.S)

DEFAULT_SKILL_ROOTS = [
    Path.home() / ".agents" / "skills",
    Path.cwd() / ".agents" / "skills",
    Path("/etc/codex/skills"),
]
DEFAULT_AGENT_ROOTS = [
    Path.cwd() / ".codex" / "agents",
    Path.cwd() / "assets" / "codex_agents",
    Path.home() / ".codex" / "agents",
]


def terms(text: str) -> list[str]:
    return [item.lower() for item in TOKEN.findall(text)]


def score(text: str, query: str) -> int:
    query_terms = terms(query)
    if not query_terms:
        return 0

    lower = text.lower()
    text_terms = set(terms(text))
    total = 0
    for term in query_terms:
        if term in text_terms:
            total += 10
        elif term in lower:
            total += 4
    return total


def split_inventory(text: str) -> list[str]:
    blocks = []
    current = []
    for line in text.splitlines():
        if line.startswith("- name:") or line.startswith("- path:"):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def frontmatter_value(text: str, key: str) -> str:
    fm = FRONTMATTER.search(text)
    if not fm:
        return ""
    prefix = f"{key}:"
    for line in fm.group(1).splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def generated_inventory() -> str:
    blocks = []
    seen = set()

    for root in DEFAULT_SKILL_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("SKILL.md")):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            text = path.read_text(encoding="utf-8", errors="ignore")
            blocks.append(
                "\n".join(
                    [
                        f"- name: {frontmatter_value(text, 'name')}",
                        f"  path: {path}",
                        f"  description: {frontmatter_value(text, 'description')}",
                    ]
                )
            )

    for root in DEFAULT_AGENT_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.toml")):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            try:
                data = toml_loads(path.read_text(encoding="utf-8"))
            except TOMLDecodeError:
                continue
            blocks.append(
                "\n".join(
                    [
                        f"- name: {data.get('name', '')}",
                        f"  path: {path}",
                        f"  description: {data.get('description', '')}",
                    ]
                )
            )

    return "\n\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score skill or agent inventory blocks against a query."
    )
    parser.add_argument(
        "inventory_file",
        nargs="?",
        type=Path,
        help="Inventory text file. If omitted, scan default local skill and agent roots.",
    )
    parser.add_argument("query_words", nargs="*", help="Query terms.")
    parser.add_argument("--query", default="", help="Query string.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum results.")
    parser.add_argument(
        "--min-score", type=int, default=1, help="Minimum score to print."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    query = args.query or " ".join(args.query_words)
    if args.inventory_file:
        inventory = args.inventory_file.read_text(encoding="utf-8", errors="ignore")
    elif not sys.stdin.isatty():
        inventory = sys.stdin.read()
        if not inventory.strip():
            inventory = generated_inventory()
    else:
        inventory = generated_inventory()
    scored = [
        {"score": score(block, query), "block": block}
        for block in split_inventory(inventory)
    ]
    scored = [item for item in scored if item["score"] >= args.min_score]
    scored.sort(key=lambda item: (-item["score"], item["block"]))
    if args.limit >= 0:
        scored = scored[: args.limit]

    if args.json:
        print(json.dumps(scored, ensure_ascii=False, indent=2))
        return

    for item in scored:
        print(f"SCORE: {item['score']}")
        print(item["block"])
        print()


if __name__ == "__main__":
    main()
