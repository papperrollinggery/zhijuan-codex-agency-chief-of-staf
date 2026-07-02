#!/usr/bin/env python3
import re
from pathlib import Path

PATHS = [
    Path.home() / ".agents" / "skills",
    Path.cwd() / ".agents" / "skills",
    Path("/etc/codex/skills"),
]

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.S)

def parse_skill(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm = FRONTMATTER.search(text)
    data = {"path": str(path), "name": "", "description": ""}
    if fm:
        for line in fm.group(1).splitlines():
            if line.startswith("name:"):
                data["name"] = line.split(":", 1)[1].strip().strip('"')
            if line.startswith("description:"):
                data["description"] = line.split(":", 1)[1].strip().strip('"')
    return data

def main():
    seen = set()
    print("# SKILL INVENTORY\n")
    for root in PATHS:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            if skill_md in seen:
                continue
            seen.add(skill_md)
            item = parse_skill(skill_md)
            print(f"- name: {item['name']}")
            print(f"  path: {item['path']}")
            print(f"  description: {item['description']}\n")

if __name__ == "__main__":
    main()
