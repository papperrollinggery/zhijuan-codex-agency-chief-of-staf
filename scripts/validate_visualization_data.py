#!/usr/bin/env python3
"""Fail closed unless compact visualization input is grounded in real task data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "assets" / "visualizations" / "data-contract.json"


def fail(message: str) -> None:
    raise ValueError(message)


def load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        fail(f"{label} must be a regular file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def require_text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(f"{field} must be a non-empty string")
    return value


def require_items(data: dict[str, Any], field: str, minimum: int, maximum: int) -> list[dict[str, Any]]:
    value = data.get(field)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail(f"{field} must contain {minimum}-{maximum} items")
    if any(not isinstance(item, dict) for item in value):
        fail(f"{field} items must be objects")
    return value


def validate_task_stage(data: dict[str, Any]) -> None:
    require_text(data, "title")
    require_text(data, "goal")
    require_text(data, "next_step")
    stages = require_items(data, "stages", 3, 12)
    states: list[str] = []
    for stage in stages:
        require_text(stage, "label")
        state = require_text(stage, "state")
        if state not in {"completed", "current", "pending"}:
            fail("stage state must be completed, current, or pending")
        states.append(state)
    if states.count("current") != 1:
        fail("task-stage must identify exactly one current stage")


def validate_decision(data: dict[str, Any]) -> None:
    require_text(data, "title")
    require_text(data, "summary")
    choices = require_items(data, "choices", 2, 3)
    for choice in choices:
        require_text(choice, "label")
        require_text(choice, "tradeoff")
    recommended = data.get("recommended_index")
    if type(recommended) is not int or not 0 <= recommended < len(choices):
        fail("recommended_index must identify one supplied choice")


def validate_impact(data: dict[str, Any]) -> None:
    require_text(data, "title")
    require_text(data, "changed_item")
    require_text(data, "next_review")
    downstream_items = require_items(data, "downstream_items", 3, 12)
    dispositions: set[str] = set()
    for item in downstream_items:
        require_text(item, "item")
        disposition = require_text(item, "disposition")
        if disposition not in {"preserved", "revisit"}:
            fail("impact disposition must be preserved or revisit")
        dispositions.add(disposition)
        require_text(item, "impact")
    if "preserved" not in dispositions or "revisit" not in dispositions:
        fail("impact must identify both preserved and revisit downstream items")


def validate_evidence_list(data: dict[str, Any]) -> None:
    require_text(data, "title")
    for item in require_items(data, "items", 5, 12):
        require_text(item, "item")
        require_text(item, "status")
        require_text(item, "meaning")


def validate_numeric_trend(data: dict[str, Any]) -> None:
    require_text(data, "title")
    require_text(data, "source_definition")
    observations = require_items(data, "observations", 1, 120)
    for observation in observations:
        require_text(observation, "name")
        value = observation.get("value")
        if type(value) not in {int, float} or not math.isfinite(value):
            fail("numeric-trend value must be finite")
        require_text(observation, "unit")
        require_text(observation, "dimension")


def validate_image_review(data: dict[str, Any]) -> None:
    require_text(data, "title")
    image_path = Path(require_text(data, "image_path"))
    if not image_path.is_absolute() or image_path.is_symlink() or not image_path.is_file():
        fail("image_path must be a verified current regular absolute file")
    image_bytes = image_path.read_bytes()
    if not (
        image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or image_bytes.startswith(b"\xff\xd8\xff")
        or image_bytes.startswith((b"GIF87a", b"GIF89a"))
        or (image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP")
    ):
        fail("image_path must contain a supported image signature")
    observed_hash = require_text(data, "image_sha256")
    actual_hash = hashlib.sha256(image_bytes).hexdigest()
    if observed_hash != actual_hash:
        fail("image_sha256 must match the observed image bytes")
    require_text(data, "alt_text")
    require_text(data, "review_target")
    for finding in require_items(data, "region_findings", 1, 32):
        require_text(finding, "region")
        require_text(finding, "finding")


VALIDATORS = {
    "task-stage": validate_task_stage,
    "decision": validate_decision,
    "impact": validate_impact,
    "evidence-list": validate_evidence_list,
    "numeric-trend": validate_numeric_trend,
    "image-review": validate_image_review,
}


def validate_payload(payload: dict[str, Any], *, require_mount_readback: bool = False) -> str:
    contract = load_object(CONTRACT_PATH, "visualization data contract")
    surfaces = contract.get("surfaces")
    if contract.get("schema_version") != "1.0" or not isinstance(surfaces, dict):
        fail("visualization data contract is invalid")
    surface = payload.get("surface")
    data = payload.get("data")
    if not isinstance(surface, str) or surface not in VALIDATORS or surface not in surfaces:
        fail("surface is unsupported")
    if not isinstance(data, dict):
        fail("data must be an object")
    VALIDATORS[surface](data)

    mount_readback = payload.get("mount_readback")
    if require_mount_readback or mount_readback is not None or surface == "image-review":
        if not isinstance(mount_readback, dict):
            fail("mount_readback is required when host mount evidence is expected")
        if mount_readback.get("surface") != surface:
            fail("mount_readback surface must match visualization surface")
        if not isinstance(mount_readback.get("mount_id"), str) or not mount_readback["mount_id"]:
            fail("mount_readback mount_id is required")
        if mount_readback.get("rendered") is not True:
            fail("mount_readback must report rendered=true")
        if surface == "image-review":
            if not isinstance(mount_readback.get("image_path"), str):
                fail("image-review mount_readback image_path is required")
            if Path(mount_readback["image_path"]).expanduser().resolve() != Path(
                data["image_path"]
            ).expanduser().resolve():
                fail("image-review mount_readback image_path must match image_path")
            if mount_readback.get("image_sha256") != data["image_sha256"]:
                fail("image-review mount_readback image_sha256 must match image_sha256")
    return surface


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="JSON visualization payload")
    parser.add_argument(
        "--require-mount-readback",
        action="store_true",
        help="require a host-returned mount/readback record in the payload",
    )
    args = parser.parse_args()
    payload = load_object(args.data.expanduser(), "visualization payload")
    surface = validate_payload(payload, require_mount_readback=args.require_mount_readback)
    print(f"Visualization data valid: {surface}.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Visualization data invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
