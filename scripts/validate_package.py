#!/usr/bin/env python3
"""Validate the authored package and minimal runtime bundle with stdlib only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from install_skill import (
    INSTALL_NAMES,
    RUNTIME_FILES,
    render_runtime_bytes,
    rendered_runtime_manifest,
    runtime_manifest,
)


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

EXPECTED_CANONICAL_SKILL_NAME = "agency-chief-of-staff"
EXPECTED_LEGACY_SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
EXPECTED_INSTALL_NAMES = (
    EXPECTED_CANONICAL_SKILL_NAME,
    EXPECTED_LEGACY_SKILL_NAME,
)
EXPECTED_LEGACY_DIFFERENCES = {"SKILL.md", "agents/openai.yaml"}
EXPECTED_CANONICAL_ACTIVATION_SENTENCE = "本 Skill 在主会话被显式或隐式激活时"
EXPECTED_LEGACY_ACTIVATION_SENTENCE = (
    "本兼容 Skill 在主会话被用户通过旧 slug 显式激活时"
)
REQUIRED_COLD_CONTEXT_DISCLOSURE = "COLD_CONTEXT_ISOLATION: UNVERIFIED"
REQUIRED_REVIEWER_READ_DISCLOSURE = "reviewer-owned read 未验证"
PROHIBITED_LEGACY_COLD_CONTEXT_DISCLOSURE = "cold-context isolation 未验证"

PROHIBITED_ROUTING_MARKERS = (
    "AGENTS_ROUTING_SNIPPET",
    "--agents-routing",
    "upsert_agents_routing",
    f"BEGIN {EXPECTED_CANONICAL_SKILL_NAME} routing",
    f"BEGIN {EXPECTED_LEGACY_SKILL_NAME} routing",
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
    "examples/real-world-prompts.md",
    "LICENSE",
    "SECURITY.md",
    "Makefile",
    ".github/workflows/ci.yml",
    "scripts/model_smoke.sh",
    "scripts/trusted_gate_helpers.sh",
}
ALLOWED_ENTRYPOINTS = {"canonical", "legacy", "none"}
ALLOWED_GUARD_BUNDLES = {"none", "canonical", "legacy"}
ENTRYPOINT_MARKER_COUNTS = {
    "canonical": {
        "COS_BOOT_RECEIPT": 1,
        "入口：canonical": 1,
        "入口：legacy": 0,
    },
    "legacy": {
        "COS_BOOT_RECEIPT": 1,
        "入口：canonical": 0,
        "入口：legacy": 1,
    },
    "none": {
        "COS_BOOT_RECEIPT": 0,
        "入口：canonical": 0,
        "入口：legacy": 0,
    },
}
# These are SHA-256 hashes of the complete canonical JSON object for every reviewed
# behavior case, not a subset of selected fields. Any prompt, oracle, tool or
# collaboration requirement, artifact assertion, hidden review marker, or future
# field therefore changes the fingerprint and fails closed. When a reviewed case is
# intentionally changed, recompute its hash with canonical_case_fingerprint() and
# update this table in the same reviewed change.
REQUIRED_BEHAVIOR_CASE_SHA256 = {
    "explicit-small-direct": "98532229aad1f2f8e9e9f7aea1e8e69a58b4801fb9fe1516ad8c2d212451154c",
    "legacy-explicit-small-direct": "aed266d2ace59ab664a223f5fb87f948bebe8988aec95d0d92de39e2a41efcf2",
    "explicit-readonly-structured": "5e64d6567513aede95f8d4533eb3b9aa633ec8652a5fc9753a06cfcc5c8fac66",
    "delegated-worker-bypass": "8dbba83b118f898c7d87c6254e7d58c19fa264d582a0caeb2565c019002b5007",
    "legacy-delegated-worker-bypass": "3014ab7c1ea9537a3b60edb2a56d1fe392ded94556577bd488dc6e9f47468dcc",
    "invalid-worker-marker-main-session": "be922cd86578e629e4da27cc0d9b6fdfd698c57337723654ad4ffda19a4d9bba",
    "invalid-worker-packet-missing-field": "44ab2c657645b6e4ca3d2d157286aa1f5879316ee37c585ae9b74a3502668245",
    "invalid-worker-packet-duplicate-field": "b8aa3ea1833f0551acc89fa2332adc0f7d478405d6e00154c062838c9f869ebb",
    "invalid-worker-packet-out-of-order": "a61f4df6e25f47d6dba57e2783a34a2ded2c8523852464dbaf943d4bd0e58141",
    "invalid-worker-packet-empty-field": "afe302afad652ae211531308e2a607f71b1eeeb83a321bb3fde9188af329edf9",
    "explicit-write-execute": "d0a1e0945a66d48fde7a603059eef057ed032ac3e9d2409cf35fc562cdf04139",
    "implicit-chief-of-staff-read": "07765f04f0e10eaead0a7cf4ed496f919b70ff908de98914be79cad2ff99e13d",
    "dual-explicit-canonical-priority": "7ae4e9974165b0840ed512afad10e27cc4ec0acbe2d0b12e5418f21533cf4126",
    "legacy-slug-mentioned-negative": "66de2170859f8a71c003f114eb3d6f6e1676349f6e972082014774035490dba8",
    "explicit-full-cycle": "e6152822539b7d0354c0a3984707bd2791d596e70b247169ab0236efb1264f64",
    "explicit-goal": "bf47568b3d1c26d89c2e42a6f64d492f690267c1093c70f882e45f0f52740175",
    "parallel-research": "8a7e218a02aa63276e20cbdff99bfb8b8c7fea06986b0d9028689c7d6f47cca2",
    "explicit-real-task": "89d0a9543ab42f864f7fabcecdbf8ef8191548ce04052da673c645e6e382f919",
    "release-readiness": "1b2c4e0d59305cfcc33195feb1b443a53799e8a356ad6bb9cf7da7bb0c139b0c",
    "stuck-thread-audit": "cc47dbce085087e5d9d6ece462f90a6d533a75cfa75bbe35dbaff8aa9eb24ffe",
    "ordinary-small-answer": "dc4636b49217823f56bd3f7feeee5901594ed142836e8620807bf100d84a4c54",
    "ordinary-readiness-phrase": "d7627c14069dd0d4366767856290a3b83c24d7a393f1538a1dd953c127011afd",
    "ordinary-rescue-phrase": "21f619a75774f33318bd633b3548c9a574e26f2f4488e0fda0ac99f7aec700ff",
    "ordinary-focused-code-fix": "313879127fd99310cdd15d920035b2cfe5340533a65bb127428e376f7499f4e8",
    "ordinary-code-review": "aec766da157da48d694bf1e04ff65d3b678c54c145c7dfe1108cac92e35c9db8",
}
REQUIRED_MODEL_SMOKE_IDS = {
    "explicit-small-direct",
    "legacy-explicit-small-direct",
    "explicit-readonly-structured",
    "delegated-worker-bypass",
    "legacy-delegated-worker-bypass",
    "invalid-worker-marker-main-session",
    "invalid-worker-packet-missing-field",
    "invalid-worker-packet-duplicate-field",
    "invalid-worker-packet-out-of-order",
    "invalid-worker-packet-empty-field",
    "explicit-write-execute",
    "explicit-full-cycle",
    "implicit-chief-of-staff-read",
    "dual-explicit-canonical-priority",
    "legacy-slug-mentioned-negative",
    "ordinary-small-answer",
    "ordinary-readiness-phrase",
    "ordinary-rescue-phrase",
    "ordinary-focused-code-fix",
    "ordinary-code-review",
}

# Split distinctive prefixes across source literals so the validator does not
# match its own detection rules. These patterns intentionally favor precision:
# findings are release-blocking, so placeholders and short examples must not fire.
HIGH_CONFIDENCE_SECRET_PATTERNS = (
    (
        "OpenAI/compatible API token",
        re.compile(r"\bsk" + r"-(?:proj-|svcacct-|ant-)?[A-Za-z0-9_-]{24,}\b"),
    ),
    (
        "GitHub classic token",
        re.compile(r"\bgh" + r"[pousr]_[A-Za-z0-9]{20,255}\b"),
    ),
    (
        "GitHub fine-grained token",
        re.compile(r"\bgithub" + r"_pat_[A-Za-z0-9_]{22,255}\b"),
    ),
    (
        "Slack token",
        re.compile(r"\bxox" + r"[baprs]-[A-Za-z0-9-]{20,255}\b"),
    ),
    (
        "Stripe live secret key",
        re.compile(r"\bsk" + r"_live_[A-Za-z0-9]{16,255}\b"),
    ),
    (
        "AWS access key id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "Google API key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    (
        "GitLab personal access token",
        re.compile(r"\bglpat" + r"-[A-Za-z0-9_-]{20,255}\b"),
    ),
    (
        "private key material",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
)
FIXED_GIT_CANDIDATES = (
    Path("/usr/bin/git"),
    Path("/bin/git"),
    Path("/usr/local/bin/git"),
    Path("/opt/homebrew/bin/git"),
)


def fail(message: str) -> None:
    raise ValueError(message)


def parse_frontmatter_text(
    text: str, *, expected_name: str, label: str = "SKILL.md"
) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail(f"{label} must start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"{label} frontmatter is not closed") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            fail(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    if set(fields) != {"name", "description"}:
        fail(f"{label} frontmatter must contain only name and description")
    if fields["name"] != expected_name:
        fail(f"unexpected {label} skill name: {fields['name']}")
    if not fields["description"]:
        fail(f"{label} skill description must not be empty")
    description_line = next(line for line in lines[1:end] if line.startswith("description:"))
    raw_description = description_line.split(":", 1)[1].strip()
    if ": " in raw_description and not (
        raw_description.startswith('"') and raw_description.endswith('"')
    ):
        fail(f"{label} description containing a colon must be YAML-quoted")
    if raw_description.startswith('"'):
        try:
            json.loads(raw_description)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} description is not a valid quoted scalar") from exc
    return fields


def parse_frontmatter(
    skill_path: Path, *, expected_name: str = EXPECTED_CANONICAL_SKILL_NAME
) -> dict[str, str]:
    return parse_frontmatter_text(
        skill_path.read_text(encoding="utf-8"),
        expected_name=expected_name,
        label=str(skill_path.name),
    )


def validate_links(root: Path, text: str) -> None:
    paths = set(re.findall(r"\((references/[^)]+|assets/[^)]+)\)", text))
    for rel in paths:
        if not (root / rel).is_file():
            fail(f"SKILL.md references missing file: {rel}")


def parse_fixed_openai_yaml_text(
    text: str, *, label: str = "agents/openai.yaml"
) -> dict[str, dict[str, object]]:
    """Parse the deliberately tiny two-level YAML schema without a dependency."""
    result: dict[str, dict[str, object]] = {}
    section: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            if not re.fullmatch(r"[a-z_]+:", line):
                fail(f"{label} invalid top-level line {number}: {line!r}")
            section = line[:-1]
            if section in result:
                fail(f"{label} duplicate section: {section}")
            result[section] = {}
            continue
        if section is None or not line.startswith("  ") or line.startswith("   "):
            fail(f"{label} invalid indentation on line {number}")
        match = re.fullmatch(r"  ([a-z_]+): (.+)", line)
        if not match:
            fail(f"{label} invalid field line {number}: {line!r}")
        key, raw = match.groups()
        if key in result[section]:
            fail(f"{label} duplicate field: {section}.{key}")
        if raw in {"true", "false"}:
            value: object = raw == "true"
        elif raw.startswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{label} invalid quoted value on line {number}"
                ) from exc
        else:
            fail(f"{label} field must be quoted or boolean on line {number}")
        result[section][key] = value
    return result


def parse_fixed_openai_yaml(path: Path) -> dict[str, dict[str, object]]:
    return parse_fixed_openai_yaml_text(path.read_text(encoding="utf-8"))


def validate_openai_yaml_text(
    text: str, *, skill_name: str, allow_implicit: bool, label: str
) -> None:
    parsed = parse_fixed_openai_yaml_text(text, label=label)
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
    if f"${skill_name}" not in str(interface["default_prompt"]):
        fail(f"{label} default_prompt must explicitly reference ${skill_name}")
    if parsed["policy"]["allow_implicit_invocation"] is not allow_implicit:
        fail(f"{label} allow_implicit_invocation must be {str(allow_implicit).lower()}")


def validate_openai_yaml(path: Path) -> None:
    validate_openai_yaml_text(
        path.read_text(encoding="utf-8"),
        skill_name=EXPECTED_CANONICAL_SKILL_NAME,
        allow_implicit=True,
        label="canonical agents/openai.yaml",
    )


def validate_generated_bundles(root: Path) -> dict[str, dict[str, str]]:
    """Validate both installer outputs against a fixed, independent contract."""
    if tuple(INSTALL_NAMES) != EXPECTED_INSTALL_NAMES:
        fail("installer Skill names drifted from the independent package contract")

    expected_keys = set(EXPECTED_RUNTIME_FILES)
    rendered_bytes: dict[str, dict[str, bytes]] = {}
    manifests: dict[str, dict[str, str]] = {}
    for skill_name in EXPECTED_INSTALL_NAMES:
        bundle = {
            rel: render_runtime_bytes(root, rel, skill_name)
            for rel in EXPECTED_RUNTIME_FILES
        }
        rendered_bytes[skill_name] = bundle
        independent_manifest = {
            rel: hashlib.sha256(content).hexdigest()
            for rel, content in bundle.items()
        }
        reported_manifest = rendered_runtime_manifest(root, skill_name)
        if set(reported_manifest) != expected_keys:
            fail(f"generated {skill_name} manifest keys drifted")
        if reported_manifest != independent_manifest:
            fail(f"generated {skill_name} manifest does not match rendered bytes")
        manifests[skill_name] = independent_manifest

    canonical = EXPECTED_CANONICAL_SKILL_NAME
    legacy = EXPECTED_LEGACY_SKILL_NAME
    source_manifest = runtime_manifest(root)
    if set(source_manifest) != expected_keys:
        fail("canonical source manifest keys drifted")
    if manifests[canonical] != source_manifest:
        fail("canonical generated bundle must exactly match the authored source")
    for rel in EXPECTED_RUNTIME_FILES:
        if rendered_bytes[canonical][rel] != (root / rel).read_bytes():
            fail(f"canonical renderer changed authored runtime content: {rel}")

    if set(manifests[canonical]) != set(manifests[legacy]):
        fail("canonical and legacy generated bundles must have identical manifest keys")
    actual_differences = {
        rel
        for rel in EXPECTED_RUNTIME_FILES
        if manifests[canonical][rel] != manifests[legacy][rel]
    }
    if actual_differences != EXPECTED_LEGACY_DIFFERENCES:
        fail(
            "canonical/legacy bundle content may differ only in SKILL.md and "
            f"agents/openai.yaml; got {sorted(actual_differences)}"
        )

    canonical_skill = rendered_bytes[canonical]["SKILL.md"].decode("utf-8")
    legacy_skill = rendered_bytes[legacy]["SKILL.md"].decode("utf-8")
    canonical_fields = parse_frontmatter_text(
        canonical_skill,
        expected_name=canonical,
        label="generated canonical SKILL.md",
    )
    legacy_fields = parse_frontmatter_text(
        legacy_skill,
        expected_name=legacy,
        label="generated legacy SKILL.md",
    )
    if f"${canonical}" not in canonical_fields["description"]:
        fail("canonical description must explicitly reference its canonical slug")
    if not all(
        marker in canonical_fields["description"]
        for marker in (
            f"output exactly `我将使用 ${canonical}，遵照你的范围。`",
            "read only this bundle's SKILL.md in full",
            "before any other action or progress",
            "COS_BOOT_RECEIPT",
        )
    ):
        fail("canonical description must protect the verified boot-sequence contract")
    legacy_description = legacy_fields["description"]
    if (
        f"${legacy}" not in legacy_description
        or f"explicit ${legacy} invocation only" not in legacy_description.lower()
    ):
        fail("legacy description must be an explicit-only compatibility contract")
    if not all(
        marker in legacy_description
        for marker in (
            f"output exactly `我将使用 ${legacy}，遵照你的范围。`",
            "read only this bundle's SKILL.md in full",
            "before any other action or progress",
            "COS_BOOT_RECEIPT",
        )
    ):
        fail("legacy description must protect the verified boot-sequence contract")
    if canonical_skill.count("入口：canonical") != 1 or "入口：legacy" in canonical_skill:
        fail("canonical SKILL.md must expose exactly one canonical boot entrypoint")
    if legacy_skill.count("入口：legacy") != 1 or "入口：canonical" in legacy_skill:
        fail("legacy SKILL.md must expose exactly one legacy boot entrypoint")
    if (
        EXPECTED_LEGACY_ACTIVATION_SENTENCE not in legacy_skill
        or EXPECTED_CANONICAL_ACTIVATION_SENTENCE in legacy_skill
    ):
        fail("legacy SKILL.md must describe explicit-only main-session activation")

    validate_openai_yaml_text(
        rendered_bytes[canonical]["agents/openai.yaml"].decode("utf-8"),
        skill_name=canonical,
        allow_implicit=True,
        label="generated canonical agents/openai.yaml",
    )
    validate_openai_yaml_text(
        rendered_bytes[legacy]["agents/openai.yaml"].decode("utf-8"),
        skill_name=legacy,
        allow_implicit=False,
        label="generated legacy agents/openai.yaml",
    )

    rendered_runtime_text = "\n".join(
        content.decode("utf-8", errors="replace")
        for bundle in rendered_bytes.values()
        for content in bundle.values()
    )
    for marker in PROHIBITED_ROUTING_MARKERS:
        if marker in rendered_runtime_text:
            fail(f"generated bundle contains AGENTS routing injection marker: {marker}")
    return manifests


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
    lines = prompt.splitlines()
    first_index = next(
        (index for index, line in enumerate(lines) if line.strip()), None
    )
    if first_index is None or lines[first_index].strip() != "AGENCY_WORKER: true":
        return None
    required_labels = (
        "委派目标",
        "读取范围",
        "写入范围",
        "期望产物",
        "验证要求",
        "停止条件",
    )
    label_pattern = re.compile(
        r"^[ \t]*(" + "|".join(map(re.escape, required_labels)) + r")[ \t]*[：:](.*)$"
    )
    positions: list[tuple[str, int, str]] = []
    for index, line in enumerate(lines[first_index + 1 :], first_index + 1):
        match = label_pattern.match(line)
        if match:
            positions.append((match.group(1), index, match.group(2).strip()))
    if [label for label, _, _ in positions] != list(required_labels):
        return None
    fields: dict[str, str] = {}
    for offset, (label, line_index, inline) in enumerate(positions):
        end = positions[offset + 1][1] if offset + 1 < len(positions) else len(lines)
        continuation = "\n".join(lines[line_index + 1 : end]).strip()
        value = "\n".join(part for part in (inline, continuation) if part).strip()
        if not value:
            return None
        fields[label] = value
    return fields


def valid_worker_packet(prompt: str) -> bool:
    return worker_packet_fields(prompt) is not None


def embedded_exact_worker_packet(prompt: str) -> str | None:
    """Extract the single seven-line reviewer packet embedded in a main case."""
    lines = prompt.splitlines()
    starts = [index for index, line in enumerate(lines) if line == "AGENCY_WORKER: true"]
    if len(starts) != 1 or starts[0] + 7 > len(lines):
        return None
    packet = "\n".join(lines[starts[0] : starts[0] + 7])
    return packet if valid_worker_packet(packet) else None


def expected_strict_worker_packet(expected_file: str) -> str:
    fields = {
        "委派目标": f"独立复核 {expected_file} 修改。",
        "读取范围": f"{expected_file}。",
        "写入范围": "无。",
        "期望产物": "实际读回的第一行、完整目标行与四个证据字段。",
        "验证要求": (
            f"先在项目根目录绝对路径作为 workdir 运行唯一 artifact 命令 "
            f"/bin/cat {expected_file}，只原样读取完整 stdout；终态严格使用 "
            "REVIEW_EVIDENCE_FIRST_LINE、REVIEW_EVIDENCE_TARGET_LINE、"
            "REVIEW_FINDINGS_COUNT、REVIEW_VERDICT 四个字段，各字段填实际读取和审查结果；"
            "REVIEW_VERDICT 只能为 NO_BLOCKING_FINDINGS 或 BLOCKING_FINDINGS，禁止 PASS；"
            "如需 artifact 工具前进度，只能精确输出 REVIEW_PROGRESS: READING_ARTIFACT。"
        ),
        "停止条件": "完成一次 artifact 读取和唯一终态后停止，不输出启动行或继续派发。",
    }
    return "\n".join(
        ["AGENCY_WORKER: true"]
        + [f"{label}：{value}" for label, value in fields.items()]
    )


def explicit_skill_slug_mentions(prompt: str) -> list[str]:
    mentions: list[str] = []
    for name in EXPECTED_INSTALL_NAMES:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-])\${re.escape(name)}(?![A-Za-z0-9_-])"
        )
        if pattern.search(prompt):
            mentions.append(name)
    return mentions


def validate_public_prompt_examples(path: Path) -> None:
    """Keep copy-paste examples aligned with the canonical entrypoint contract."""
    text = path.read_text(encoding="utf-8")
    legacy_call = f"${EXPECTED_LEGACY_SKILL_NAME}"
    canonical_call = f"${EXPECTED_CANONICAL_SKILL_NAME}"
    if legacy_call in text:
        fail("public prompt examples must use the canonical Skill slug")
    if canonical_call not in text:
        fail("public prompt examples do not contain the canonical Skill slug")
    text_blocks = re.findall(r"```text[ \t]*\n(.*?)\n```", text, flags=re.DOTALL)
    worker_blocks = [block for block in text_blocks if "AGENCY_WORKER:" in block]
    if len(worker_blocks) != 1:
        fail("public prompt examples must contain exactly one worker bypass packet")
    if not valid_worker_packet(worker_blocks[0]):
        fail(
            "public worker bypass example must start with AGENCY_WORKER: true and "
            "contain the six ordered, unique, non-empty fields"
        )


def canonical_case_fingerprint(case: dict[str, object]) -> str:
    """Hash the complete case object with a stable, language-neutral encoding."""
    encoded = json.dumps(
        case,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        expected_entrypoint = case.get("expected_entrypoint")
        if case.get("model_smoke") and expected_entrypoint is None:
            fail(f"behavior case {case_id} model smoke needs expected_entrypoint")
        if expected_entrypoint is not None and expected_entrypoint not in ALLOWED_ENTRYPOINTS:
            fail(f"behavior case {case_id} has unsupported expected_entrypoint")
        allowed_guard_bundle = case.get("allowed_guard_bundle")
        if allowed_guard_bundle is not None:
            if allowed_guard_bundle not in ALLOWED_GUARD_BUNDLES:
                fail(f"behavior case {case_id} has unsupported allowed_guard_bundle")
            if not (
                case["activation"] == "worker"
                and case["should_trigger"] is False
                and case["collaboration"] == "none"
                and expected_entrypoint == "none"
                and valid_worker_packet(str(case["prompt"]))
            ):
                fail(
                    f"behavior case {case_id} guard bundle is only valid for a "
                    "complete packet in a non-triggering worker case"
                )
            expected_guard_name = {
                "canonical": EXPECTED_CANONICAL_SKILL_NAME,
                "legacy": EXPECTED_LEGACY_SKILL_NAME,
                "none": None,
            }[str(allowed_guard_bundle)]
            mentions = explicit_skill_slug_mentions(str(case["prompt"]))
            if expected_guard_name is None:
                if mentions:
                    fail(
                        f"behavior case {case_id} guard bundle none cannot "
                        "explicitly invoke a Skill"
                    )
            elif mentions != [expected_guard_name]:
                fail(
                    f"behavior case {case_id} guard bundle must uniquely match "
                    "its explicit $slug"
                )
        exact_marker_counts = case.get("exact_marker_counts")
        if case.get("model_smoke") and exact_marker_counts is None:
            fail(f"behavior case {case_id} model smoke needs exact_marker_counts")
        if exact_marker_counts is not None:
            if (
                not isinstance(exact_marker_counts, dict)
                or set(exact_marker_counts) != set(ENTRYPOINT_MARKER_COUNTS["none"])
                or any(type(count) is not int or count < 0 for count in exact_marker_counts.values())
            ):
                fail(f"behavior case {case_id} has invalid exact_marker_counts")
            if expected_entrypoint is None:
                fail(f"behavior case {case_id} marker counts need expected_entrypoint")
            if exact_marker_counts != ENTRYPOINT_MARKER_COUNTS[str(expected_entrypoint)]:
                fail(f"behavior case {case_id} weakens exact entrypoint marker counts")
        sandbox = case.get("sandbox", "read-only")
        if sandbox not in ALLOWED_SANDBOXES:
            fail(f"behavior case {case_id} has unsafe sandbox: {sandbox!r}")
        for key in (
            "require_tool_event",
            "require_no_tool_events",
            "require_collab_spawn",
            "require_collab_completion",
            "require_collab_event",
            "require_context_isolation",
            "allow_preload_announcement",
        ):
            if key in case and type(case[key]) is not bool:
                fail(f"behavior case {case_id} {key} must be boolean")
        review_evidence_tier = case.get("review_evidence_tier")
        if review_evidence_tier is not None and review_evidence_tier not in {
            "rc",
            "stable",
        }:
            fail(
                f"behavior case {case_id} has unsupported review_evidence_tier"
            )
        if case.get("require_tool_event") and case.get("require_no_tool_events"):
            fail(f"behavior case {case_id} cannot require both tool use and no tool use")
        if case.get("require_collab_spawn") and not (
            case.get("model_smoke")
            and case["should_trigger"] is True
            and case["collaboration"]
            in {"native_subagents", "native_subagents_optional"}
        ):
            fail(
                f"behavior case {case_id} collaboration spawn requires a "
                "positive native-subagent model smoke"
            )
        if case.get("require_collab_completion") and not (
            case.get("model_smoke")
            and case["should_trigger"] is True
            and case["collaboration"]
            in {"native_subagents", "native_subagents_optional"}
            and sandbox == "workspace-write"
            and not case.get("require_collab_spawn")
            and not case.get("require_collab_event")
        ):
            fail(
                f"behavior case {case_id} collaboration completion requires one "
                "positive workspace-write native-subagent smoke"
            )
        exact_final = case.get("exact_final")
        if exact_final is not None:
            if not isinstance(exact_final, str) or not exact_final:
                fail(f"behavior case {case_id} exact_final must be a non-empty string")
            if case["should_trigger"] or case["activation"] != "ordinary":
                fail(
                    f"behavior case {case_id} exact_final is only valid for an "
                    "ordinary negative activation"
                )
        if case.get("require_no_tool_events") and (
            case["should_trigger"]
            or case["activation"] != "ordinary"
            or case["collaboration"] != "none"
        ):
            fail(
                f"behavior case {case_id} no-tool oracle is only valid for an "
                "ordinary negative activation without collaboration"
            )
        if case.get("allow_preload_announcement") and not (
            case["activation"] in {"explicit", "implicit"}
            and case["should_trigger"] is True
        ):
            fail(
                f"behavior case {case_id} preload announcement is only valid for "
                "a positive main-session activation"
            )
        expected_boot_receipt = case.get("expected_boot_receipt")
        if expected_boot_receipt is not None and (
            not isinstance(expected_boot_receipt, str)
            or not re.fullmatch(
                r"COS_BOOT_RECEIPT：已接管；目标：[^；\n]{1,160}；"
                r"模式：结构化；协作：原生子代理；入口：canonical。",
                expected_boot_receipt,
            )
        ):
            fail(f"behavior case {case_id} has an invalid expected_boot_receipt")
        if (
            case.get("require_collab_event")
            or case.get("require_collab_completion")
        ) and not isinstance(expected_boot_receipt, str):
            fail(
                f"behavior case {case_id} collaboration evidence requires an exact boot receipt"
            )
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
            if case.get("require_collab_completion") and not isinstance(
                case.get("expected_file_content"), str
            ):
                fail(
                    f"behavior case {case_id} collaboration completion needs exact artifact content"
                )
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
            if marker.count("{runtime_nonce}") != 1:
                fail(
                    f"behavior case {case_id} review marker must contain one "
                    "runtime nonce slot"
                )
            if re.search(r"\[readback-[0-9a-f]{16,}\]", marker):
                fail(
                    f"behavior case {case_id} review marker must not contain a "
                    "reusable static nonce"
                )
            if marker in str(case["prompt"]):
                fail(f"behavior case {case_id} review marker must not be disclosed in prompt")
            if review_evidence_tier is None:
                fail(
                    f"behavior case {case_id} collaboration review needs "
                    "review_evidence_tier"
                )
        if case.get("require_collab_event") or case.get("require_collab_completion"):
            embedded_packet = embedded_exact_worker_packet(str(case["prompt"]))
            if embedded_packet is None:
                fail(
                    f"behavior case {case_id} collaboration prompt needs one exact reviewer packet"
                )
            if str(case["expected_text"]) in embedded_packet:
                fail(
                    f"behavior case {case_id} reviewer packet must not disclose expected artifact text"
                )
            marker = case.get("review_evidence_marker")
            if isinstance(marker, str) and marker in embedded_packet:
                fail(
                    f"behavior case {case_id} reviewer packet must not disclose review marker"
                )
            if case.get("require_collab_event") and embedded_packet != expected_strict_worker_packet(
                str(case["expected_file"])
            ):
                fail(
                    f"behavior case {case_id} strict reviewer packet must match the canonical contract"
                )
        elif review_evidence_tier is not None:
            fail(
                f"behavior case {case_id} review_evidence_tier requires a "
                "collaboration event"
            )
        if case.get("require_context_isolation") and not case.get("require_collab_event"):
            fail(
                f"behavior case {case_id} context isolation requires an observed "
                "cold-review event"
            )
        if case.get("require_context_isolation") and review_evidence_tier != "stable":
            fail(
                f"behavior case {case_id} context isolation is a stable-tier "
                "review requirement"
            )
        if case["activation"] == "worker" and case["should_trigger"] is not False:
            fail(f"behavior case {case_id} worker activation must bypass the skill")
        if case["activation"] == "worker" and not valid_worker_packet(str(case["prompt"])):
            fail(f"behavior case {case_id} worker activation needs a complete packet")

    cases_by_id = {str(case["id"]): case for case in cases}
    reviewed_ids = set(REQUIRED_BEHAVIOR_CASE_SHA256)
    if ids != reviewed_ids:
        missing = sorted(reviewed_ids - ids)
        unexpected = sorted(ids - reviewed_ids)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unexpected:
            details.append(f"unexpected={','.join(unexpected)}")
        fail(
            "behavior suite must be exactly the 25 reviewed cases: "
            + "; ".join(details)
        )
    for case_id, expected_fingerprint in REQUIRED_BEHAVIOR_CASE_SHA256.items():
        actual_fingerprint = canonical_case_fingerprint(cases_by_id[case_id])
        if actual_fingerprint != expected_fingerprint:
            fail(
                f"behavior case {case_id} full semantic contract drifted; "
                "review the complete case and update its canonical SHA-256 only after approval"
            )

    smoke = [case for case in cases if case.get("model_smoke")]
    smoke_by_id = {str(case["id"]): case for case in smoke}
    smoke_ids = set(smoke_by_id)
    if smoke_ids != REQUIRED_MODEL_SMOKE_IDS:
        missing_smoke = sorted(REQUIRED_MODEL_SMOKE_IDS - smoke_ids)
        unexpected_smoke = sorted(smoke_ids - REQUIRED_MODEL_SMOKE_IDS)
        details: list[str] = []
        if missing_smoke:
            details.append(f"missing={','.join(missing_smoke)}")
        if unexpected_smoke:
            details.append(f"unexpected={','.join(unexpected_smoke)}")
        fail("behavior model-smoke suite must be exactly the 20 reviewed cases: " + "; ".join(details))
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
    if not any(
        case.get("model_smoke") and case.get("require_collab_completion")
        for case in cases
    ):
        fail("behavior cases need a natural collaboration completion/adoption event")
    return len(cases)


def trusted_git_executable(explicit: Path | None) -> Path:
    """Resolve Git without consulting ambient PATH."""
    candidates = (explicit,) if explicit is not None else FIXED_GIT_CANDIDATES
    errors: list[str] = []
    for candidate in candidates:
        expanded = candidate.expanduser()
        if not expanded.is_absolute():
            errors.append("path is not absolute")
            continue
        try:
            resolved = expanded.resolve(strict=True)
            metadata = resolved.stat()
        except OSError:
            errors.append("path is unavailable")
            continue
        fixed_resolved = {
            path.resolve(strict=False) for path in FIXED_GIT_CANDIDATES
        }
        if expanded not in FIXED_GIT_CANDIDATES and resolved not in fixed_resolved:
            errors.append("path is outside fixed trusted locations")
            continue
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            errors.append("path is not an executable regular file")
            continue
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            errors.append("path is group/world writable")
            continue
        if hasattr(os, "geteuid") and metadata.st_uid not in {0, os.geteuid()}:
            errors.append("path has an unexpected owner")
            continue
        return resolved
    detail = errors[0] if explicit is not None and errors else "no fixed candidate passed"
    fail(f"trusted absolute git helper is unavailable: {detail}")


def git_tracked_relatives(root: Path, git_executable: Path) -> set[str] | None:
    """Return tracked publication paths, or None outside a Git worktree."""
    env = {
        "PATH": os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
    }
    probe = subprocess.run(
        [str(git_executable), "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        env=env,
    )
    if probe.returncode != 0:
        git_marker = root / ".git"
        if git_marker.exists() or git_marker.is_symlink():
            fail("package Git metadata exists but tracked publication paths are unreadable")
        return None
    if probe.stdout.strip() != b"true":
        fail("package root is not inside a Git worktree")
    result = subprocess.run(
        [str(git_executable), "-C", str(root), "ls-files", "-z", "--cached", "--", "."],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        fail("tracked publication paths could not be enumerated")
    relatives: set[str] = set()
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        value = raw.decode("utf-8", errors="surrogateescape")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(
            part in {"", ".", "..", ".git"} for part in relative.parts
        ):
            fail("Git reported an unsafe tracked publication path")
        relatives.add(relative.as_posix())
    return relatives


def authored_text_files(root: Path, tracked_relatives: set[str]) -> list[Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        if (
            relative.parts[:2] == ("validation", "current")
            and relative_text not in tracked_relatives
        ):
            continue
        if path.is_symlink():
            fail(f"public package contains a symlink: {relative}")
        if path.is_file() and path.suffix != ".pyc":
            files[relative_text] = path
    for relative_text in sorted(tracked_relatives):
        relative = PurePosixPath(relative_text)
        path = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                fail(f"tracked public package path traverses a symlink: {relative_text}")
        if not path.exists():
            fail(f"tracked public package file is missing: {relative_text}")
        if not path.is_file():
            fail(f"tracked public package entry is not a regular file: {relative_text}")
        files[relative_text] = path
    return [files[key] for key in sorted(files)]


def validate_no_high_confidence_secrets(root: Path, files: list[Path]) -> None:
    """Fail closed on high-confidence credential material without echoing it."""
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            relative = path.relative_to(root)
            line_number = text.count("\n", 0, match.start()) + 1
            fail(
                "high-confidence secret detected in package source: "
                f"{relative}:{line_number} ({label})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the skill package contract.")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--git-executable",
        type=Path,
        default=None,
        help="Absolute trusted Git helper. Ambient PATH is never consulted.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    git_executable = trusted_git_executable(args.git_executable)

    if tuple(RUNTIME_FILES) != EXPECTED_RUNTIME_FILES:
        fail("installer runtime manifest drifted from the independent package contract")

    fields = parse_frontmatter(root / "SKILL.md")
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    line_count = len(skill_text.splitlines())
    if line_count > 500:
        fail(f"SKILL.md exceeds 500 lines: {line_count}")
    validate_links(root, skill_text)
    validate_openai_yaml(root / "agents" / "openai.yaml")
    validate_public_prompt_examples(root / "examples" / "real-world-prompts.md")
    manifest = runtime_manifest(root)
    generated_manifests = validate_generated_bundles(root)

    tracked_relatives = git_tracked_relatives(root, git_executable)
    authored_files = authored_text_files(root, tracked_relatives or set())
    validate_no_high_confidence_secrets(root, authored_files)
    authored_relatives = {str(path.relative_to(root)) for path in authored_files}
    missing_public = sorted(REQUIRED_PUBLIC_FILES - authored_relatives)
    if missing_public:
        fail(f"public package missing required files: {', '.join(missing_public)}")
    if tracked_relatives is not None:
        missing_tracked_public = sorted(REQUIRED_PUBLIC_FILES - tracked_relatives)
        if missing_tracked_public:
            fail(
                "Git worktree has required public files that are not tracked: "
                + ", ".join(missing_tracked_public)
            )
    authored_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in authored_files
    )
    runtime_text = "\n".join(
        (root / rel).read_text(encoding="utf-8", errors="replace")
        for rel in RUNTIME_FILES
        if (root / rel).suffix in {".md", ".yaml", ".py"}
    )
    delivery_review_text = (root / "references" / "delivery-review.md").read_text(
        encoding="utf-8"
    )
    for label, text in (
        ("SKILL.md", skill_text),
        ("references/delivery-review.md", delivery_review_text),
    ):
        for required_disclosure in (
            REQUIRED_COLD_CONTEXT_DISCLOSURE,
            REQUIRED_REVIEWER_READ_DISCLOSURE,
        ):
            if required_disclosure not in text:
                fail(
                    f"{label} lacks the canonical review disclosure: "
                    f"{required_disclosure}"
                )
    if PROHIBITED_LEGACY_COLD_CONTEXT_DISCLOSURE in runtime_text:
        fail("runtime contains the obsolete cold-context disclosure wording")
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
        "generated_bundles": len(generated_manifests),
        "behavior_contract_cases": case_count,
        "model_behavior_verified": False,
        "note": "Offline package/contract validation does not prove model behavior.",
    }
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else (
            f"Package contract valid: {line_count} SKILL lines, {len(manifest)} runtime files, "
            f"{len(generated_manifests)} generated bundles, {case_count} behavior cases. "
            "Model behavior not claimed."
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Package contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
