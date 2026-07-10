#!/usr/bin/env python3
"""Validate the authored package and minimal runtime bundle with stdlib only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

from install_skill import RUNTIME_FILES, SKILL_NAME, runtime_manifest


# Keep this list independent from install_skill.py. A mutation of the installer
# manifest must fail validation instead of changing both the action and its proof.
EXPECTED_RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/real-threads.md",
    "references/delivery-review.md",
    "references/long-running-work.md",
    "references/history-audit.md",
    "assets/WORK_RECEIPT_TEMPLATE.yaml",
    "assets/DELIVERY_EVIDENCE_TEMPLATE.yaml",
    "scripts/audit_historical_threads.py",
)

PROHIBITED_ROUTING_MARKERS = (
    "AGENTS_ROUTING_SNIPPET",
    "--agents-routing",
    "upsert_agents_routing",
    f"BEGIN {SKILL_NAME} routing",
    "AGENTS routing shim",
)
CASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
ALLOWED_MODES = {"direct", "structured", "goal", "worker"}
ALLOWED_COLLABORATION = {
    "none",
    "native_subagents",
    "native_subagents_optional",
    "real_task",
}
ALLOWED_ACTIVATION = {"explicit", "implicit", "ordinary", "worker"}
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
REQUIRED_PUBLIC_FILES = {
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "SECURITY.md",
    "Makefile",
    ".github/workflows/ci.yml",
}
REQUIRED_MODEL_SMOKE_IDS = {
    "explicit-small-direct",
    "explicit-readonly-structured",
    "delegated-worker-bypass",
    "invalid-worker-marker-main-session",
    "explicit-write-execute",
    "implicit-chief-of-staff-read",
    "ordinary-small-answer",
    "ordinary-readiness-phrase",
    "ordinary-rescue-phrase",
}


def fail(message: str) -> None:
    raise ValueError(message)


def parse_frontmatter(skill_path: Path) -> dict[str, str]:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        fail("SKILL.md must start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            fail(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    if set(fields) != {"name", "description"}:
        fail("SKILL.md frontmatter must contain only name and description")
    if fields["name"] != SKILL_NAME:
        fail(f"unexpected skill name: {fields['name']}")
    if not fields["description"]:
        fail("skill description must not be empty")
    description_line = next(line for line in lines[1:end] if line.startswith("description:"))
    raw_description = description_line.split(":", 1)[1].strip()
    if ": " in raw_description and not (
        raw_description.startswith('"') and raw_description.endswith('"')
    ):
        fail("description containing a colon must be YAML-quoted")
    if raw_description.startswith('"'):
        try:
            json.loads(raw_description)
        except json.JSONDecodeError as exc:
            raise ValueError("SKILL.md description is not a valid quoted scalar") from exc
    return fields


def validate_links(root: Path, text: str) -> None:
    paths = set(re.findall(r"\((references/[^)]+|assets/[^)]+)\)", text))
    for rel in paths:
        if not (root / rel).is_file():
            fail(f"SKILL.md references missing file: {rel}")


def parse_fixed_openai_yaml(path: Path) -> dict[str, dict[str, object]]:
    """Parse the deliberately tiny two-level YAML schema without a dependency."""
    result: dict[str, dict[str, object]] = {}
    section: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            if not re.fullmatch(r"[a-z_]+:", line):
                fail(f"agents/openai.yaml invalid top-level line {number}: {line!r}")
            section = line[:-1]
            if section in result:
                fail(f"agents/openai.yaml duplicate section: {section}")
            result[section] = {}
            continue
        if section is None or not line.startswith("  ") or line.startswith("   "):
            fail(f"agents/openai.yaml invalid indentation on line {number}")
        match = re.fullmatch(r"  ([a-z_]+): (.+)", line)
        if not match:
            fail(f"agents/openai.yaml invalid field line {number}: {line!r}")
        key, raw = match.groups()
        if key in result[section]:
            fail(f"agents/openai.yaml duplicate field: {section}.{key}")
        if raw in {"true", "false"}:
            value: object = raw == "true"
        elif raw.startswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"agents/openai.yaml invalid quoted value on line {number}"
                ) from exc
        else:
            fail(f"agents/openai.yaml field must be quoted or boolean on line {number}")
        result[section][key] = value
    return result


def validate_openai_yaml(path: Path) -> None:
    parsed = parse_fixed_openai_yaml(path)
    if set(parsed) != {"interface", "policy"}:
        fail("agents/openai.yaml must contain exactly interface and policy")
    interface = parsed["interface"]
    if set(interface) != {"display_name", "short_description", "default_prompt"}:
        fail("agents/openai.yaml interface fields do not match the supported schema")
    if set(parsed["policy"]) != {"allow_implicit_invocation"}:
        fail("agents/openai.yaml policy fields do not match the supported schema")
    for key in ("display_name", "short_description", "default_prompt"):
        if not isinstance(interface[key], str) or not interface[key]:
            fail(f"agents/openai.yaml interface.{key} must be a non-empty string")
    short_description = str(interface["short_description"])
    if not 25 <= len(short_description) <= 64:
        fail("short_description must contain 25-64 characters")
    if f"${SKILL_NAME}" not in str(interface["default_prompt"]):
        fail("agents/openai.yaml default_prompt must explicitly reference this skill")
    if parsed["policy"]["allow_implicit_invocation"] is not True:
        fail("agents/openai.yaml must allow implicit invocation")


def validate_relative_artifact_path(value: object, case_id: str) -> None:
    if not isinstance(value, str) or not value:
        fail(f"behavior case {case_id} expected_file must be a non-empty string")
    if "\\" in value:
        fail(f"behavior case {case_id} expected_file must use a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        fail(f"behavior case {case_id} expected_file must stay inside the fixture")


def validate_string_list(case: dict[str, object], key: str, case_id: str) -> None:
    if key not in case:
        return
    value = case[key]
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        fail(f"behavior case {case_id} {key} must be a list of non-empty strings")


def valid_worker_packet(prompt: str) -> bool:
    first_nonempty = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    required_labels = (
        "委派目标",
        "读取范围",
        "写入范围",
        "期望产物",
        "验证要求",
        "停止条件",
    )
    return first_nonempty == "AGENCY_WORKER: true" and all(
        label in prompt for label in required_labels
    )


def validate_behavior_cases(path: Path) -> int:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) < 10:
        fail("behavior_cases.json must contain at least 10 cases")
    required = {"id", "prompt", "should_trigger", "mode", "collaboration", "activation"}
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            fail(f"invalid behavior case: {case!r}")
        case_id = case["id"]
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            fail(f"unsafe behavior case id: {case_id!r}")
        if case_id in ids:
            fail(f"duplicate behavior case id: {case_id}")
        ids.add(case_id)
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            fail(f"behavior case {case_id} prompt must be a non-empty string")
        if type(case["should_trigger"]) is not bool:
            fail(f"behavior case {case_id} should_trigger must be boolean")
        if case["mode"] not in ALLOWED_MODES:
            fail(f"behavior case {case_id} has unsupported mode: {case['mode']!r}")
        if case["collaboration"] not in ALLOWED_COLLABORATION:
            fail(
                f"behavior case {case_id} has unsupported collaboration: "
                f"{case['collaboration']!r}"
            )
        if case["activation"] not in ALLOWED_ACTIVATION:
            fail(f"behavior case {case_id} has unsupported activation: {case['activation']!r}")
        if "model_smoke" in case and type(case["model_smoke"]) is not bool:
            fail(f"behavior case {case_id} model_smoke must be boolean")
        sandbox = case.get("sandbox", "read-only")
        if sandbox not in ALLOWED_SANDBOXES:
            fail(f"behavior case {case_id} has unsafe sandbox: {sandbox!r}")
        for key in ("require_tool_event", "require_collab_event"):
            if key in case and type(case[key]) is not bool:
                fail(f"behavior case {case_id} {key} must be boolean")
        for key in ("must_contain", "must_not_contain", "forbidden_file_texts"):
            validate_string_list(case, key, case_id)
        has_file = "expected_file" in case
        has_text = "expected_text" in case
        if has_file != has_text:
            fail(f"behavior case {case_id} must pair expected_file with expected_text")
        if has_file:
            validate_relative_artifact_path(case["expected_file"], case_id)
            if not isinstance(case["expected_text"], str) or not case["expected_text"]:
                fail(f"behavior case {case_id} expected_text must be non-empty")
            if "expected_file_content" in case and (
                not isinstance(case["expected_file_content"], str)
                or not case["expected_file_content"]
            ):
                fail(f"behavior case {case_id} expected_file_content must be non-empty")
            if "review_evidence_marker" in case and (
                not isinstance(case["review_evidence_marker"], str)
                or not case["review_evidence_marker"]
            ):
                fail(f"behavior case {case_id} review_evidence_marker must be non-empty")
        elif (
            "expected_file_content" in case
            or "forbidden_file_texts" in case
            or "review_evidence_marker" in case
        ):
            fail(f"behavior case {case_id} file assertions need expected_file")
        if case.get("require_collab_event"):
            if not case.get("model_smoke") or case["collaboration"] != "native_subagents":
                fail(
                    f"behavior case {case_id} cold review must be a model smoke with "
                    "native_subagents"
                )
            if not has_file:
                fail(f"behavior case {case_id} cold review needs an expected artifact")
            if "expected_file_content" not in case:
                fail(f"behavior case {case_id} cold review needs exact artifact content")
            if "review_evidence_marker" not in case:
                fail(f"behavior case {case_id} cold review needs hidden readback evidence")
            marker = str(case["review_evidence_marker"])
            if marker not in str(case["expected_file_content"]):
                fail(f"behavior case {case_id} review marker must exist in expected artifact")
            if marker in str(case["prompt"]):
                fail(f"behavior case {case_id} review marker must not be disclosed in prompt")
        if case["activation"] == "worker" and case["should_trigger"] is not False:
            fail(f"behavior case {case_id} worker activation must bypass the skill")
        if case["activation"] == "worker" and not valid_worker_packet(str(case["prompt"])):
            fail(f"behavior case {case_id} worker activation needs a complete packet")

    smoke = [case for case in cases if case.get("model_smoke")]
    smoke_ids = {str(case["id"]) for case in smoke}
    missing_smoke = sorted(REQUIRED_MODEL_SMOKE_IDS - smoke_ids)
    if missing_smoke:
        fail(f"behavior cases missing required model smoke: {', '.join(missing_smoke)}")
    if not any(case["activation"] == "implicit" and case["should_trigger"] for case in smoke):
        fail("model smoke needs a positive implicit-invocation case")
    if not any(case["activation"] == "ordinary" and not case["should_trigger"] for case in smoke):
        fail("model smoke needs an ordinary negative-invocation case")
    if not any(case["activation"] == "worker" and not case["should_trigger"] for case in smoke):
        fail("model smoke needs a delegated-worker bypass case")
    if not any(case["collaboration"] == "real_task" for case in cases):
        fail("behavior cases need real task/thread contract coverage")
    if not any(
        case.get("model_smoke") and case.get("sandbox", "read-only") == "workspace-write"
        for case in cases
    ):
        fail("behavior cases need a real write-and-verify model smoke")
    if not any(case.get("model_smoke") and case.get("require_collab_event") for case in cases):
        fail("behavior cases need an independently observed cold-review event")
    return len(cases)


def authored_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if relative.parts[:2] == ("validation", "current"):
            continue
        if path.is_symlink():
            fail(f"public package contains a symlink: {relative}")
        if path.is_file() and path.suffix != ".pyc":
            files.append(path)
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the skill package contract.")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    if tuple(RUNTIME_FILES) != EXPECTED_RUNTIME_FILES:
        fail("installer runtime manifest drifted from the independent package contract")

    fields = parse_frontmatter(root / "SKILL.md")
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    line_count = len(skill_text.splitlines())
    if line_count > 500:
        fail(f"SKILL.md exceeds 500 lines: {line_count}")
    validate_links(root, skill_text)
    validate_openai_yaml(root / "agents" / "openai.yaml")
    manifest = runtime_manifest(root)

    authored_files = authored_text_files(root)
    authored_relatives = {str(path.relative_to(root)) for path in authored_files}
    missing_public = sorted(REQUIRED_PUBLIC_FILES - authored_relatives)
    if missing_public:
        fail(f"public package missing required files: {', '.join(missing_public)}")
    authored_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in authored_files
    )
    runtime_text = "\n".join(
        (root / rel).read_text(encoding="utf-8", errors="replace")
        for rel in RUNTIME_FILES
        if (root / rel).suffix in {".md", ".yaml", ".py"}
    )
    installer_text = (root / "scripts" / "install_skill.py").read_text(encoding="utf-8")
    for marker in PROHIBITED_ROUTING_MARKERS:
        if marker in runtime_text or marker in installer_text:
            fail(f"active package still contains AGENTS routing injection marker: {marker}")
    root_agents = root / "AGENTS.md"
    if root_agents.exists():
        agents_text = root_agents.read_text(encoding="utf-8", errors="replace")
        for marker in PROHIBITED_ROUTING_MARKERS:
            if marker in agents_text:
                fail(f"root AGENTS.md contains prohibited routing marker: {marker}")
    machine_markers = ("/" + "Users/", "\\" + "Users\\", "jin" + "jungao")
    for marker in machine_markers:
        if marker in authored_text:
            fail(f"active package contains a machine-specific path marker: {marker}")

    forbidden_runtime_prefixes = ("README", "AGENTS", ".github/", "validation/", "evals/")
    for rel in RUNTIME_FILES:
        if rel.startswith(forbidden_runtime_prefixes):
            fail(f"non-runtime file included in installer manifest: {rel}")

    case_count = validate_behavior_cases(root / "evals" / "behavior_cases.json")
    result = {
        "status": "valid",
        "skill": fields["name"],
        "skill_lines": line_count,
        "runtime_files": len(manifest),
        "behavior_contract_cases": case_count,
        "model_behavior_verified": False,
        "note": "Offline package/contract validation does not prove model behavior.",
    }
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else (
            f"Package contract valid: {line_count} SKILL lines, {len(manifest)} runtime files, "
            f"{case_count} behavior cases. Model behavior not claimed."
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Package contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
