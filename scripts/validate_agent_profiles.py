#!/usr/bin/env python3
"""Validate the bounded custom-agent templates without third-party packages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROFILE_NAMES = (
    "codebase-researcher",
    "technical-architect",
    "developer",
    "reviewer",
    "test-debugger",
)
EXPECTED_SANDBOXES = {
    "codebase-researcher": "read-only",
    "technical-architect": "read-only",
    "developer": "workspace-write",
    "reviewer": "read-only",
    "test-debugger": "read-only",
}
SELF_SKILL_NAMES = {
    "agency-chief-of-staff",
    "zhijuan-codex-agency-chief-of-staf",
}
SIMPLE_FIELD_RE = re.compile(r"([a-z_]+)\s*=\s*(.+)\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def decode_string(raw: str, label: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be a quoted TOML basic string") from exc
    if not isinstance(value, str) or not value:
        fail(f"{label} must be a non-empty string")
    return value


def parse_profile(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        fail(f"agent profile must be a regular file: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    fields: dict[str, object] = {}
    skills: list[dict[str, object]] = []
    index = 0
    active_skill: dict[str, object] | None = None
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        index += 1
        if not line or line.startswith("#"):
            continue
        if line == "[[skills.config]]":
            active_skill = {}
            skills.append(active_skill)
            continue
        match = SIMPLE_FIELD_RE.fullmatch(line)
        if not match:
            fail(f"unsupported TOML line in {path.name}: {raw_line!r}")
        key, raw = match.groups()
        target = active_skill if active_skill is not None else fields
        if key in target:
            fail(f"duplicate field in {path.name}: {key}")
        if raw == '"""':
            if active_skill is not None:
                fail(f"multiline strings are not allowed in skills.config: {path.name}")
            body: list[str] = []
            while index < len(lines) and lines[index].strip() != '"""':
                body.append(lines[index])
                index += 1
            if index >= len(lines):
                fail(f"unterminated multiline string in {path.name}: {key}")
            index += 1
            value = "\n".join(body).strip()
            if not value:
                fail(f"empty multiline string in {path.name}: {key}")
            target[key] = value
        elif raw in {"true", "false"}:
            target[key] = raw == "true"
        else:
            target[key] = decode_string(raw, f"{path.name}:{key}")
    fields["skills.config"] = skills
    return fields


def skill_name_from_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.name != "SKILL.md":
        fail(f"skill binding must reference a regular SKILL.md: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        fail(f"skill binding has no YAML frontmatter: {path}")
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.startswith("name:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw.startswith('"'):
            match = re.fullmatch(r'("(?:[^"\\]|\\.)*")(?:\s+#.*)?', raw)
            if not match:
                break
            name = decode_string(match.group(1), f"{path}:name")
        elif raw.startswith("'"):
            match = re.fullmatch(r"'((?:[^']|'')*)'(?:\s+#.*)?", raw)
            if not match:
                break
            name = match.group(1).replace("''", "'")
        else:
            name = raw.split(" #", 1)[0].strip()
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
            return name
        break
    fail(f"skill binding has no frontmatter name: {path}")
    raise AssertionError("unreachable")


def validate_profile(path: Path, expected_name: str, allow_bindings: bool) -> dict[str, object]:
    parsed = parse_profile(path)
    allowed = {"name", "description", "developer_instructions", "sandbox_mode", "skills.config"}
    if set(parsed) != allowed:
        fail(f"{path.name} fields must be exactly {sorted(allowed)}")
    if parsed["name"] != expected_name:
        fail(f"{path.name} name mismatch: {parsed['name']!r}")
    if parsed["sandbox_mode"] != EXPECTED_SANDBOXES[expected_name]:
        fail(f"{path.name} sandbox mismatch")
    instructions = str(parsed["developer_instructions"])
    for marker in ("Do not spawn another agent", "Never activate agency-chief-of-staff"):
        if marker not in instructions:
            fail(f"{path.name} missing bounded-worker marker: {marker}")
    if re.search(r"^model(?:_reasoning_effort)?\s*=", path.read_text(encoding="utf-8"), re.MULTILINE):
        fail(f"{path.name} must inherit the host model and reasoning configuration")
    if "luna" in path.read_text(encoding="utf-8").lower():
        fail(f"{path.name} must not select Luna")
    skills = parsed["skills.config"]
    assert isinstance(skills, list)
    if skills and not allow_bindings:
        fail(f"source template must not embed machine-specific skill bindings: {path.name}")
    for entry in skills:
        if set(entry) != {"path", "enabled"} or entry["enabled"] is not True:
            fail(f"invalid skills.config entry in {path.name}")
        skill_path = Path(str(entry["path"])).expanduser()
        skill_name = skill_name_from_file(skill_path)
        if skill_name in SELF_SKILL_NAMES:
            fail(f"recursive self-skill binding is forbidden: {skill_name}")
    return parsed


def validate_routing(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2:
        fail("agent-routing.json schema_version must be 2")
    if set(data.get("self_skill_names", [])) != SELF_SKILL_NAMES:
        fail("agent-routing.json self-skill denylist mismatch")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(PROFILE_NAMES):
        fail("agent-routing.json profile set mismatch")
    for name, expected_sandbox in EXPECTED_SANDBOXES.items():
        profile = profiles[name]
        if not isinstance(profile, dict) or profile.get("sandbox") != expected_sandbox:
            fail(f"agent-routing.json sandbox mismatch: {name}")
        if profile.get("domain_skill_policy") != "explicit-selected-only":
            fail(f"agent-routing.json domain skill policy mismatch: {name}")
        expected_execution = (
            "main-or-isolated-worktree" if name == "developer" else "cli-profile-compat"
        )
        if profile.get("compat_execution") != expected_execution:
            fail(f"agent-routing.json compatibility execution mismatch: {name}")
    modes = data.get("execution_modes")
    if not isinstance(modes, dict) or set(modes) != {
        "native-custom-agent",
        "cli-profile-compat",
        "main-or-isolated-worktree",
    }:
        fail("agent-routing.json execution mode set mismatch")
    native = modes["native-custom-agent"]
    if not isinstance(native, dict) or native.get("status") != "optional-enhancement":
        fail("native custom-agent mode must remain an optional enhancement")
    if native.get("requires_named_profile_selection_readback") is not True:
        fail("native custom-agent mode must require named-profile readback")
    compat = modes["cli-profile-compat"]
    if (
        not isinstance(compat, dict)
        or compat.get("status") != "permanent-fallback"
        or compat.get("runner") != "scripts/run_profile_compat.py"
        or compat.get("supported_sandboxes") != ["read-only"]
        or compat.get("native_role_claim") is not False
        or compat.get("archive_required") is not True
        or compat.get("bounded_timeout") is not True
        or compat.get("sanitized_process_environment") is not True
        or compat.get("tool_shell_path") != "/usr/bin:/bin:/usr/sbin:/sbin"
        or compat.get("git_diff_receipt_profiles")
        != ["codebase-researcher", "reviewer"]
        or compat.get("structured_tool_result_required") is not True
        or compat.get("cold_context_isolation") != "unverified"
    ):
        fail("cli-profile-compat execution contract mismatch")
    write_path = modes["main-or-isolated-worktree"]
    if (
        not isinstance(write_path, dict)
        or write_path.get("status") != "write-path"
        or write_path.get("profiles") != ["developer"]
        or write_path.get("prompt_only_sandbox_claim") is not False
    ):
        fail("main-or-isolated-worktree execution contract mismatch")
    return data


def validate_profile_set(root: Path) -> dict[str, object]:
    templates = root / "assets" / "codex_agents"
    project_profiles = root / ".codex" / "agents"
    for name in PROFILE_NAMES:
        template = templates / f"{name}.toml"
        project = project_profiles / f"{name}.toml"
        validate_profile(template, name, allow_bindings=False)
        validate_profile(project, name, allow_bindings=False)
        if template.read_bytes() != project.read_bytes():
            fail(f"project profile drifted from distributable template: {name}")
    validate_routing(root / "assets" / "agent-routing.json")
    return {
        "status": "valid",
        "profiles": list(PROFILE_NAMES),
        "project_template_parity": True,
        "fixed_model": False,
        "self_skill_binding": False,
        "native_custom_agent_required": False,
        "compat_fallback": "cli-profile-compat",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate custom-agent templates and routing.")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_profile_set(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "Agent profiles valid: 5 bounded profiles; project/template parity verified.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Agent profiles invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
