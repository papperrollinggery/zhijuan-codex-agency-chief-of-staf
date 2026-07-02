#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def main():
    if len(sys.argv) < 3:
        print("Usage: append_event.py AGENCY_LOG.jsonl '{\"event_type\":\"...\"}'")
        sys.exit(2)

    path = Path(sys.argv[1])
    event = json.loads(sys.argv[2])
    event.setdefault("time", datetime.now(timezone.utc).isoformat())

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    print(f"OK: appended to {path}")

if __name__ == "__main__":
    main()
