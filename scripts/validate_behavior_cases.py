#!/usr/bin/env python3
"""Validate behavior-case schema without pretending the model was executed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_package import validate_behavior_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate behavior contract case coverage.")
    parser.add_argument("cases", nargs="?", default="evals/behavior_cases.json", type=Path)
    args = parser.parse_args()
    count = validate_behavior_cases(args.cases)
    print(f"Behavior contract schema valid: {count} cases. No model run was performed.")


if __name__ == "__main__":
    main()
