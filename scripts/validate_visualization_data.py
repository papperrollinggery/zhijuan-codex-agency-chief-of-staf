#!/usr/bin/env python3
"""Fail closed unless compact visualization input is grounded in real task data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "assets" / "visualizations" / "data-contract.json"
TEXT_FIELD_LIMITS = {
    "title": 120,
    "goal": 600,
    "next_step": 280,
    "blocker": 280,
    "label": 80,
    "state": 16,
    "summary": 480,
    "tradeoff": 280,
    "downstream_effect": 280,
    "changed_item": 200,
    "next_review": 280,
    "item": 160,
    "disposition": 16,
    "impact": 360,
    "status": 64,
    "meaning": 360,
    "next_action": 280,
    "source_definition": 600,
    "missing_values": 480,
    "missing_reason": 280,
    "name": 120,
    "unit": 32,
    "dimension": 64,
    "image_path": 4096,
    "image_sha256": 64,
    "alt_text": 600,
    "review_target": 280,
    "revision_effect": 480,
    "region": 120,
    "finding": 600,
}
TOKEN_TEXT_FIELDS = {"state", "disposition", "image_path", "image_sha256"}
COLLAPSIBLE_C0_WHITESPACE = {"\t", "\n", "\r"}
MAX_IMAGE_BYTES = 64 * 1024 * 1024
IMAGE_READ_CHUNK_BYTES = 1024 * 1024


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
    if not isinstance(value, str):
        fail(f"{field} must be a non-empty string")
    maximum = TEXT_FIELD_LIMITS.get(field)
    if maximum is None:
        fail(f"text policy is missing for field: {field}")
    if "\x00" in value:
        fail(f"{field} must not contain NUL")
    collapsible = field not in TOKEN_TEXT_FIELDS
    for character in value:
        codepoint = ord(character)
        if codepoint < 0x20:
            if not collapsible or character not in COLLAPSIBLE_C0_WHITESPACE:
                fail(f"{field} must not contain C0 control characters")
        elif 0x7F <= codepoint <= 0x9F:
            fail(f"{field} must not contain control characters")
    if len(value) > maximum:
        fail(f"{field} must contain at most {maximum} Unicode code points")
    normalized = " ".join(value.split()) if collapsible else value.strip()
    if not normalized:
        fail(f"{field} must be a non-empty string")
    if len(normalized) > maximum:
        fail(f"{field} must contain at most {maximum} Unicode code points")
    return normalized


def require_items(data: dict[str, Any], field: str, minimum: int, maximum: int) -> list[dict[str, Any]]:
    value = data.get(field)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail(f"{field} must contain {minimum}-{maximum} items")
    if any(not isinstance(item, dict) for item in value):
        fail(f"{field} items must be objects")
    return value


def image_extension(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "webp"
    fail("image_path must contain a supported image signature")


def read_verified_image_bytes(image_path: Path) -> bytes:
    if not image_path.is_absolute():
        fail("image_path must be a verified current regular absolute file")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        fail("this platform cannot verify image_path without following symlinks")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(image_path, flags)
    except OSError:
        fail("image_path must be opened without following symlinks")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail("image_path must be a single-link regular file")
        if before.st_size > MAX_IMAGE_BYTES:
            fail(f"image_path must be at most {MAX_IMAGE_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, IMAGE_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                fail(f"image_path must be at most {MAX_IMAGE_BYTES} bytes")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            path_after = os.stat(image_path, follow_symlinks=False)
        except OSError:
            fail("image_path changed during verified read")
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or identity(before) != identity(after)
            or identity(after) != identity(path_after)
        ):
            fail("image_path changed during verified read")
        image_bytes = b"".join(chunks)
        image_extension(image_bytes)
        return image_bytes
    finally:
        os.close(descriptor)


def validate_task_stage(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    goal = require_text(data, "goal")
    next_step = require_text(data, "next_step")
    stages = require_items(data, "stages", 3, 12)
    states: list[str] = []
    normalized_stages: list[dict[str, str]] = []
    for stage in stages:
        label = require_text(stage, "label")
        state = require_text(stage, "state")
        if state not in {"completed", "current", "pending"}:
            fail("stage state must be completed, current, or pending")
        states.append(state)
        normalized_stages.append({"label": label, "state": state})
    if states.count("current") != 1:
        fail("task-stage must identify exactly one current stage")
    current_index = states.index("current")
    if any(state != "completed" for state in states[:current_index]) or any(
        state != "pending" for state in states[current_index + 1 :]
    ):
        fail("task-stage states must be ordered completed, current, then pending")
    normalized = {
        "title": title,
        "goal": goal,
        "stages": normalized_stages,
        "next_step": next_step,
    }
    if data.get("blocker") is not None:
        normalized["blocker"] = require_text(data, "blocker")
    return normalized


def validate_decision(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    summary = require_text(data, "summary")
    choices = require_items(data, "choices", 2, 3)
    normalized_choices = [
        {
            "id": f"choice-{index + 1}",
            "label": require_text(choice, "label"),
            "tradeoff": require_text(choice, "tradeoff"),
            "downstream_effect": require_text(choice, "downstream_effect"),
        }
        for index, choice in enumerate(choices)
    ]
    recommended = data.get("recommended_index")
    if type(recommended) is not int or not 0 <= recommended < len(choices):
        fail("recommended_index must identify one supplied choice")
    return {
        "title": title,
        "summary": summary,
        "choices": normalized_choices,
        "recommended_index": recommended,
    }


def validate_impact(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    changed_item = require_text(data, "changed_item")
    next_review = require_text(data, "next_review")
    downstream_items = require_items(data, "downstream_items", 3, 12)
    dispositions: set[str] = set()
    normalized_items: list[dict[str, str]] = []
    for item in downstream_items:
        item_name = require_text(item, "item")
        disposition = require_text(item, "disposition")
        if disposition not in {"preserved", "revisit"}:
            fail("impact disposition must be preserved or revisit")
        dispositions.add(disposition)
        impact = require_text(item, "impact")
        normalized_items.append(
            {"item": item_name, "disposition": disposition, "impact": impact}
        )
    if "preserved" not in dispositions or "revisit" not in dispositions:
        fail("impact must identify both preserved and revisit downstream items")
    return {
        "title": title,
        "changed_item": changed_item,
        "downstream_items": normalized_items,
        "next_review": next_review,
    }


def validate_evidence_list(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    items: list[dict[str, str]] = []
    for item in require_items(data, "items", 5, 12):
        normalized = {
            "item": require_text(item, "item"),
            "status": require_text(item, "status"),
            "meaning": require_text(item, "meaning"),
        }
        if item.get("next_action") is not None:
            normalized["next_action"] = require_text(item, "next_action")
        items.append(normalized)
    return {"title": title, "items": items}


def validate_numeric_trend(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    summary = require_text(data, "summary")
    missing_values = require_text(data, "missing_values")
    source_definition = require_text(data, "source_definition")
    observations = require_items(data, "observations", 1, 120)
    normalized_observations: list[dict[str, Any]] = []
    finite_count = 0
    for observation in observations:
        name = require_text(observation, "name")
        value = observation.get("value")
        if value is None:
            missing_reason = require_text(observation, "missing_reason")
        elif type(value) not in {int, float} or not math.isfinite(value):
            fail("numeric-trend value must be finite")
        else:
            finite_count += 1
            if observation.get("missing_reason") is not None:
                fail("numeric-trend finite value must not include missing_reason")
        unit = require_text(observation, "unit")
        dimension = require_text(observation, "dimension")
        normalized = {"name": name, "value": value, "unit": unit, "dimension": dimension}
        if value is None:
            normalized["missing_reason"] = missing_reason
        normalized_observations.append(normalized)
    if finite_count == 0:
        fail("numeric-trend requires at least one finite observation")
    return {
        "title": title,
        "summary": summary,
        "observations": normalized_observations,
        "missing_values": missing_values,
        "source_definition": source_definition,
    }


def validate_image_review(data: dict[str, Any]) -> dict[str, Any]:
    title = require_text(data, "title")
    image_path = Path(require_text(data, "image_path"))
    image_bytes = read_verified_image_bytes(image_path)
    observed_hash = require_text(data, "image_sha256")
    actual_hash = hashlib.sha256(image_bytes).hexdigest()
    if observed_hash != actual_hash:
        fail("image_sha256 must match the observed image bytes")
    alt_text = require_text(data, "alt_text")
    review_target = require_text(data, "review_target")
    revision_effect = require_text(data, "revision_effect")
    region_findings = [
        {
            "region": require_text(finding, "region"),
            "finding": require_text(finding, "finding"),
        }
        for finding in require_items(data, "region_findings", 1, 32)
    ]
    return {
        "title": title,
        "image_path": str(image_path),
        "image_sha256": observed_hash,
        "alt_text": alt_text,
        "review_target": review_target,
        "region_findings": region_findings,
        "revision_effect": revision_effect,
    }


VALIDATORS = {
    "task-stage": validate_task_stage,
    "decision": validate_decision,
    "impact": validate_impact,
    "evidence-list": validate_evidence_list,
    "numeric-trend": validate_numeric_trend,
    "image-review": validate_image_review,
}


MOUNT_PROOF_FIELDS = {"host_mount", "mount_id", "mount_readback", "rendered"}


def reject_payload_mount_claims(value: object, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in MOUNT_PROOF_FIELDS:
                fail(
                    "payload-provided mount/readback fields are not trusted: "
                    f"{child_path}"
                )
            reject_payload_mount_claims(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_payload_mount_claims(child, f"{path}[{index}]")


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reject_payload_mount_claims(payload)
    unexpected = sorted(set(payload) - {"surface", "data"})
    if unexpected:
        fail(f"visualization payload contains unsupported fields: {', '.join(unexpected)}")
    if set(payload) != {"surface", "data"}:
        fail("visualization payload must contain only surface and data")

    contract = load_object(CONTRACT_PATH, "visualization data contract")
    surfaces = contract.get("surfaces")
    if contract.get("schema_version") != "2.0" or not isinstance(surfaces, dict):
        fail("visualization data contract is invalid")
    surface = payload.get("surface")
    data = payload.get("data")
    if not isinstance(surface, str) or surface not in VALIDATORS or surface not in surfaces:
        fail("surface is unsupported")
    if not isinstance(data, dict):
        fail("data must be an object")
    return {"surface": surface, "data": VALIDATORS[surface](data)}


def validate_payload(payload: dict[str, Any], *, require_mount_readback: bool = False) -> str:
    if require_mount_readback:
        fail(
            "host mount/readback cannot be validated from a visualization payload"
        )
    return str(normalize_payload(payload)["surface"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="JSON visualization payload")
    parser.add_argument(
        "--require-mount-readback",
        action="store_true",
        help="fail closed: host mount/readback cannot be proven by payload data",
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
