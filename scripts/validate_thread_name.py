#!/usr/bin/env python3
import re
import sys

PATTERN = re.compile(
    r"^\[P\d{2}-TH\d{2}-R\d{2}\] .+-[A-Z]{2,3}｜.+｜TASK-\d{3}｜OUT-[A-Z0-9]{3,8}$"
)

def main():
    if len(sys.argv) < 2:
        print("Usage: validate_thread_name.py '<thread_name>'")
        sys.exit(2)

    name = sys.argv[1]
    if PATTERN.match(name):
        print("OK")
        return

    print("INVALID THREAD NAME")
    print("Expected: [P01-TH00-R00] 幕僚长-COS｜主控沟通｜TASK-000｜OUT-000")
    sys.exit(1)

if __name__ == "__main__":
    main()
