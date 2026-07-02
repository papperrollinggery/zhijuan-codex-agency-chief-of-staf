#!/usr/bin/env python3
import sys
from pathlib import Path

def score(text: str, query: str) -> int:
    q = [x.lower() for x in query.split() if x.strip()]
    t = text.lower()
    return sum(10 for x in q if x in t)

def main():
    if len(sys.argv) < 3:
        print("Usage: score_capabilities.py <inventory-file> <query>")
        sys.exit(2)

    inv = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
    query = " ".join(sys.argv[2:])
    blocks = inv.split("\n- name:")
    scored = []
    for block in blocks:
        if block.strip():
            scored.append((score(block, query), block.strip()))
    for s, b in sorted(scored, reverse=True)[:10]:
        print(f"SCORE: {s}")
        print(b)
        print()

if __name__ == "__main__":
    main()
