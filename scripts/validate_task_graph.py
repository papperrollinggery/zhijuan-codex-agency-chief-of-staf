#!/usr/bin/env python3
import sys
from pathlib import Path

REQUIRED = [
    "任务ID",
    "标题",
    "类型",
    "复杂度",
    "状态策略",
    "负责人线程",
    "Goal",
    "Skill",
    "Agent",
    "Reviewer",
    "Gate",
    "输出",
]

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "TASK_GRAPH.md")
    if not path.exists():
        print("MISSING TASK_GRAPH.md")
        sys.exit(1)

    text = path.read_text(encoding="utf-8", errors="ignore")
    missing = [x for x in REQUIRED if x not in text]

    if missing:
        print("TASK_GRAPH missing:", ", ".join(missing))
        sys.exit(1)

    print("OK: task graph valid")

if __name__ == "__main__":
    main()
