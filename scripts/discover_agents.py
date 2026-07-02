#!/usr/bin/env python3
from pathlib import Path

PATHS = [
    Path.home() / ".codex" / "agents",
    Path.cwd() / ".codex" / "agents",
]

def main():
    print("# AGENT INVENTORY\n")
    for root in PATHS:
        if not root.exists():
            continue
        for f in root.glob("*.toml"):
            print(f"- path: {f}")
            text = f.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if line.startswith("name") or line.startswith("description"):
                    print(f"  {line}")
            print()

if __name__ == "__main__":
    main()
