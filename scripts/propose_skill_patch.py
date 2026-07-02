#!/usr/bin/env python3
import sys
from pathlib import Path
from datetime import datetime

def main():
    if len(sys.argv) < 3:
        print("Usage: propose_skill_patch.py <problem> <proposal>")
        sys.exit(2)

    problem = sys.argv[1]
    proposal = sys.argv[2]
    out_dir = Path("PATCH_PROPOSALS")
    out_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"PATCH-{ts}.md"
    path.write_text(
        f"# PATCH_PROPOSAL {ts}\n\n"
        f"## Problem\n\n{problem}\n\n"
        f"## Proposal\n\n{proposal}\n\n"
        f"## Checks\n\n```bash\nbash scripts/check_structure.sh .\n```\n",
        encoding="utf-8"
    )
    print(f"OK: {path}")

if __name__ == "__main__":
    main()
