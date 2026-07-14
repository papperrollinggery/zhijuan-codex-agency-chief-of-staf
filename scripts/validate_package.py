#!/usr/bin/env python3
"""Validate the authored package and minimal runtime bundle with stdlib only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from install_skill import LEGACY_SKILL_NAME, RUNTIME_FILES, SKILL_NAME, runtime_manifest
from validate_agent_profiles import PROFILE_NAMES, validate_profile_set


# Keep this list independent from install_skill.py. A mutation of the installer
# manifest must fail validation instead of changing both the action and its proof.
EXPECTED_RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/real-threads.md",
    "references/delivery-review.md",
    "references/long-running-work.md",
    "references/history-audit.md",
    "references/software-development.md",
    "references/user-experience.md",
    "references/model-routing-and-budget.md",
    "assets/WORK_RECEIPT_TEMPLATE.yaml",
    "assets/DELIVERY_EVIDENCE_TEMPLATE.yaml",
    "assets/agent-routing.json",
    "assets/role-model-policy.json",
    "assets/visualizations/surface-registry.json",
    "assets/visualizations/task-surface.html",
    "assets/visualizations/decision-surface.html",
    "assets/codex_agents/codebase-researcher.toml",
    "assets/codex_agents/technical-architect.toml",
    "assets/codex_agents/developer.toml",
    "assets/codex_agents/reviewer.toml",
    "assets/codex_agents/test-debugger.toml",
    "scripts/audit_historical_threads.py",
    "scripts/install_agent_profiles.py",
    "scripts/run_profile_compat.py",
    "scripts/resolve_role_route.py",
    "scripts/validate_agent_profiles.py",
)

PROHIBITED_ROUTING_MARKERS = (
    "AGENTS_ROUTING_SNIPPET",
    "--agents-routing",
    "upsert_agents_routing",
    f"BEGIN {SKILL_NAME} routing",
    f"BEGIN {LEGACY_SKILL_NAME} routing",
    "AGENTS routing shim",
)
CASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
SKILL_SLUG_RE = re.compile(r"\$(?:[a-z][a-z0-9]*)(?:-[a-z0-9]+)+")
SELF_SKILL_SLUG_RE = re.compile(
    rf"\$(?:{re.escape(SKILL_NAME)}|{re.escape(LEGACY_SKILL_NAME)})(?![a-z0-9-])"
)
REVIEW_OUTCOME_RE = re.compile(
    r"(?:\b(?:NO-?GO|GO|PASS|FAIL)\b|预期结论|预判结论|预期判定|预判判定|通过|失败)",
    re.IGNORECASE,
)
PACKET_VALUE_LEAK_RE = re.compile(
    r"(?:[\x60#=]|(?:\b(?:expected|hidden)\b)|(?:\b(?:target|marker|verdict)\s+(?:is|value)\b)|"
    r"(?:目标值|隐藏(?:标记|marker)|(?:标记|marker)(?:是|为)|(?:结论|判定)(?:是|为)|"
    r"(?:是|为|等于|包含)\s*(?:[\x60#]|[A-Za-z0-9_-]{4,})))",
    re.IGNORECASE,
)
OUTPUT_SCHEMA_RE = re.compile(
    r"^[A-Z][A-Z0-9_]*(?:、[A-Z][A-Z0-9_]*)*(?:，(?:均填)?实际读回值)?[。.]?$"
)
WORKER_PACKET_LABELS = (
    "委派目标",
    "读取范围",
    "写入范围",
    "期望产物",
    "验证要求",
    "停止条件",
)
WORKER_PACKET_FORBIDDEN_TERMS = (
    "启动幕僚长",
    "激活本技能",
    "激活此技能",
    "使用本 skill",
    "guard-read",
    "guard read",
)
SAFE_STOP_CONDITION = "返回唯一终态；不启动、不派发。"


def safe_worker_packet_value(label: str, value: str) -> bool:
    """Reject packet values that can smuggle an expected readback or verdict."""
    if PACKET_VALUE_LEAK_RE.search(value):
        return False
    if label == "期望产物":
        return "实际读回" in value or OUTPUT_SCHEMA_RE.fullmatch(value) is not None
    if label == "验证要求":
        return "读" in value and ("回" in value or "当前" in value)
    if label == "停止条件":
        return value == SAFE_STOP_CONDITION
    return True
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
    "role-model-balanced-budget",
    "role-model-route-unavailable",
}
REQUIRED_VISUAL_SURFACES = {
    "task-stage",
    "decision",
    "impact",
    "evidence-list",
    "numeric-trend",
    "image-review",
}
REQUIRED_VISUAL_BEHAVIOR_CASES = {
    "visualized-dependent-stages",
    "visualized-numeric-boundary",
    "visualized-image-boundary",
    "visualization-fallback",
}
FORBIDDEN_VISIBLE_UI_TERMS = (
    "COS_BOOT_RECEIPT",
    "thread_id",
    "sha256",
    "TOOL_BLOCKED",
    "exit code",
    "JSON",
    "YAML",
    "回值",
)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"style", "script"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


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


def validate_visualization_assets(root: Path) -> None:
    registry_path = root / "assets" / "visualizations" / "surface-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("registry_version") != "1.0":
        fail("visualization registry must use version 1.0")
    surfaces = registry.get("surfaces")
    if not isinstance(surfaces, list):
        fail("visualization registry surfaces must be a list")
    kinds = {
        item.get("kind")
        for item in surfaces
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    if kinds != REQUIRED_VISUAL_SURFACES:
        fail("visualization registry does not match the supported surface set")
    for item in surfaces:
        if not isinstance(item, dict):
            fail("visualization registry surface must be an object")
        for key in ("kind", "use_when", "preferred_visual", "required_visible", "fallback", "forbidden"):
            if key not in item or not item[key]:
                fail(f"visualization surface {item.get('kind')!r} missing {key}")

    templates = {
        "task": root / "assets" / "visualizations" / "task-surface.html",
        "decision": root / "assets" / "visualizations" / "decision-surface.html",
    }
    for name, template_path in templates.items():
        html = template_path.read_text(encoding="utf-8")
        for marker in ("<meta name=\"viewport\"", "width:min(720px,100%)", "@media (max-width:", "prefers-reduced-motion"):
            if marker not in html:
                fail(f"{name} visualization template missing responsive/accessibility marker: {marker}")
        if re.search(r"<(?:script|link|img|iframe|video|audio|source)[^>]+(?:src|href)=", html, re.IGNORECASE):
            fail(f"{name} visualization template must not load external resources")
        if re.search(r"(?:url\s*\(|@import|fetch\s*\(|WebSocket\s*\()", html, re.IGNORECASE):
            fail(f"{name} visualization template must not use network-capable resources")
        if ":hover" in html:
            fail(f"compact {name} visualization must not add hover-only styling")
        if "@keyframes" in html or re.search(r"(?:animation|transition)\s*:(?!\s*none)", html, re.IGNORECASE):
            fail(f"compact {name} visualization must not animate or transition")
        parser = VisibleTextParser()
        parser.feed(html)
        visible = " ".join(parser.parts)
        for term in FORBIDDEN_VISIBLE_UI_TERMS:
            if term.lower() in visible.lower():
                fail(f"{name} visualization template exposes backstage term: {term}")
    task_html = templates["task"].read_text(encoding="utf-8")
    if "aria-current=\"step\"" not in task_html:
        fail("task visualization template must identify the current step")
    decision_html = templates["decision"].read_text(encoding="utf-8")
    for marker in ("aria-pressed=\"true\"", "min-height:44px", "window.openai.sendFollowUpMessage"):
        if marker not in decision_html:
            fail(f"decision visualization template missing interaction marker: {marker}")


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


def worker_packet_fields(prompt: str) -> dict[str, str] | None:
    lines = [line.strip() for line in prompt.splitlines() if line.strip()]
    if not lines or lines[0] != "AGENCY_WORKER: true":
        return None
    lowered = prompt.lower()
    if (
        SELF_SKILL_SLUG_RE.search(prompt)
        or REVIEW_OUTCOME_RE.search(prompt)
        or any(term in lowered for term in WORKER_PACKET_FORBIDDEN_TERMS)
    ):
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        matched = next(
            (
                label
                for label in WORKER_PACKET_LABELS
                if line.startswith(f"{label}：") or line.startswith(f"{label}:")
            ),
            None,
        )
        if matched is None or matched in fields:
            return None
        value = line.split("：", 1)[1] if "：" in line else line.split(":", 1)[1]
        if not value.strip() or not safe_worker_packet_value(matched, value.strip()):
            return None
        fields[matched] = value.strip()
    return fields if tuple(fields) == WORKER_PACKET_LABELS else None


def valid_worker_packet(prompt: str) -> bool:
    return worker_packet_fields(prompt) is not None


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
        if "visualization" in case:
            visual = case["visualization"]
            if not isinstance(visual, dict) or set(visual) != {"surface", "fallback", "must_not_claim", "must_contain_any", "must_not_contain"}:
                fail(f"behavior case {case_id} visualization contract is invalid")
            if not isinstance(visual["surface"], str) or visual["surface"] not in REQUIRED_VISUAL_SURFACES:
                fail(f"behavior case {case_id} visualization surface is unsupported")
            if not isinstance(visual["fallback"], str) or not visual["fallback"]:
                fail(f"behavior case {case_id} visualization fallback is required")
            if not isinstance(visual["must_not_claim"], list) or not visual["must_not_claim"] or any(
                not isinstance(item, str) or not item for item in visual["must_not_claim"]
            ):
                fail(f"behavior case {case_id} visualization must_not_claim is invalid")
            for visual_key in ("must_contain_any", "must_not_contain"):
                if not isinstance(visual[visual_key], list) or not visual[visual_key] or any(
                    not isinstance(item, str) or not item for item in visual[visual_key]
                ):
                    fail(f"behavior case {case_id} visualization {visual_key} is invalid")
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
            if str(case["expected_text"]) in str(case["prompt"]):
                fail(f"behavior case {case_id} review target must not be disclosed in prompt")
            if REVIEW_OUTCOME_RE.search(str(case["prompt"])):
                fail(f"behavior case {case_id} review verdict must not be disclosed in prompt")
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
    missing_visual = sorted(REQUIRED_VISUAL_BEHAVIOR_CASES - ids)
    if missing_visual:
        fail(f"behavior cases missing visualization coverage: {', '.join(missing_visual)}")
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
    validate_visualization_assets(root)
    agent_profiles = validate_profile_set(root)
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
        "custom_agent_profiles": len(PROFILE_NAMES),
        "custom_agent_template_parity": agent_profiles["project_template_parity"],
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
