"""Strict parsers for worker, Execution Root, and reviewer protocols."""

from __future__ import annotations

import json
import re
from pathlib import Path


CONTRACT_PATH = Path(__file__).resolve().parents[1] / "assets" / "WORKER_PROTOCOL_CONTRACT.json"
_CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
WORKER_HEADER = _CONTRACT["worker"]["header"]
WORKER_FIELDS = tuple(_CONTRACT["worker"]["fields"])
WORKER_STOP_CONDITION = _CONTRACT["worker"]["stop_condition"]
WORKER_OUTPUT_SCHEMAS = frozenset(
    tuple(schema) for schema in _CONTRACT["worker"]["output_schemas"]
)
REVIEW_FIELDS = tuple(_CONTRACT["reviewer"]["fields"])
REVIEW_VERDICTS = frozenset(_CONTRACT["reviewer"]["verdicts"])
SELF_SKILL_SLUG_RE = re.compile(
    r"\$(?:agency-chief-of-staff|zhijuan-codex-agency-chief-of-staf)(?![a-z0-9-])"
)
REVIEW_OUTCOME_RE = re.compile(
    r"(?:\b(?:expected|predicted)\s+(?:outcome|verdict)\s*(?:is|=|:)\s*"
    r"(?:NO-?GO|GO|PASS|FAIL)\b|(?:预期|预判)(?:结论|判定)\s*(?:是|为|=|：|:)?\s*"
    r"(?:NO-?GO|GO|PASS|FAIL|通过|失败)|\bREVIEW_VERDICT\s*[:=]\s*(?:NO-?GO|GO|PASS|FAIL)\b|"
    r"返回(?:通过|失败)(?:结论|判定)|(?:^|[：:])\s*(?:NO-?GO|GO|PASS|FAIL)\s*[。.]?$)",
    re.IGNORECASE | re.MULTILINE,
)
PACKET_VALUE_LEAK_RE = re.compile(
    r"(?:\b(?:REVIEW_TARGET|REVIEW_READBACK|REVIEW_VERDICT)\s*[:=]\s*\S+|"
    r"\b(?:expected|hidden)\s+(?:target|marker|verdict|value)\s*(?:is|=|:)\s*\S+|"
    r"(?:预期|隐藏)\s*(?:目标|标记|marker|结论|判定|值)\s*(?:是|为|=|：|:)\s*\S+)",
    re.IGNORECASE,
)
WORKER_PACKET_FORBIDDEN_TERMS = (
    "启动幕僚长",
    "激活本技能",
    "激活此技能",
    "使用本 skill",
    "guard-read",
    "guard read",
)
EXECUTION_SESSION_HEADER = "AGENCY_EXECUTION_SESSION: true"
EXECUTION_SESSION_SKILL = "$agency-chief-of-staff"
EXECUTION_SESSION_FIELDS = (
    "执行 Skill",
    "任务 ID",
    "编排深度",
    "项目根目录",
    "任务清单",
    "团队计划",
    "进度文件",
    "执行模型请求",
    "推理强度请求",
    "执行职责",
    "停止条件",
)
EXECUTION_SESSION_DUTY = "作为本任务 Execution Root，按清单执行、调度、验证并更新进度。"
EXECUTION_SESSION_STOP = "全部完成标准有当前证据，或记录真实阻塞；不得创建新的 Chief-of-Staff 根任务。"
CODEX_DELEGATION_HEADER = "<codex_delegation>"
CODEX_DELEGATION_FOOTER = "</codex_delegation>"
CODEX_DELEGATION_SOURCE_RE = re.compile(
    r"  <source_thread_id>([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})"
    r"</source_thread_id>"
)
CODEX_DELEGATION_INPUT_PREFIX = "  <input>"
CODEX_DELEGATION_INPUT_SUFFIX = "</input>"


class InvalidAgencyPacket(ValueError):
    """A reserved Agency marker was present but its packet was invalid."""

    def __init__(self, packet_kind: str, detail: str) -> None:
        super().__init__(f"INVALID_PACKET ({packet_kind}): {detail}")
        self.packet_kind = packet_kind
        self.detail = detail


def _strict_lines(text: str, *, expected_count: int, label: str) -> list[str]:
    lines = text.splitlines()
    if len(lines) != expected_count or any(not line or line != line.strip() for line in lines):
        count = "five" if expected_count == 5 else str(expected_count)
        raise ValueError(f"{label} must contain exactly {count} non-empty trimmed lines")
    return lines


def parse_output_schema(value: str) -> tuple[str, ...]:
    normalized = value.removesuffix("。").removesuffix(".")
    suffix = "，均填实际读回值"
    if normalized.endswith(suffix):
        normalized = normalized[: -len(suffix)]
    fields = tuple(normalized.split("、"))
    if fields not in WORKER_OUTPUT_SCHEMAS:
        raise ValueError("worker packet expected output schema is not allowlisted")
    return fields


def parse_worker_packet(text: str) -> dict[str, str]:
    lines = _strict_lines(text, expected_count=len(WORKER_FIELDS) + 1, label="worker packet")
    if lines[0] != WORKER_HEADER:
        raise ValueError(f"worker packet must start with {WORKER_HEADER}")
    result: dict[str, str] = {}
    for line, label in zip(lines[1:], WORKER_FIELDS, strict=True):
        prefixes = (f"{label}：", f"{label}:")
        prefix = next((item for item in prefixes if line.startswith(item)), None)
        if prefix is None:
            raise ValueError(f"worker packet field order mismatch: {label}")
        value = line[len(prefix) :]
        if not value or value != value.strip():
            raise ValueError(f"worker packet field is empty or padded: {label}")
        result[label] = value
    if result["停止条件"] != WORKER_STOP_CONDITION:
        raise ValueError("worker packet stop condition is not exact")
    lowered = text.lower()
    if SELF_SKILL_SLUG_RE.search(text):
        raise ValueError("worker packet must not recursively invoke the Chief-of-Staff skill")
    if REVIEW_OUTCOME_RE.search(text):
        raise ValueError("worker packet must not disclose a predicted outcome")
    if any(term in lowered for term in WORKER_PACKET_FORBIDDEN_TERMS):
        raise ValueError("worker packet must not include activation or guard-read instructions")
    for label, value in result.items():
        if PACKET_VALUE_LEAK_RE.search(value):
            raise ValueError(f"worker packet field leaks an expected value: {label}")
        if label == "期望产物":
            parse_output_schema(value)
        if label == "验证要求" and not (
            "读" in value and ("回" in value or "当前" in value)
        ):
            raise ValueError("worker packet verification must require a current readback")
    return result


def parse_execution_session_packet(text: str) -> dict[str, str]:
    """Parse the root execution-session packet independently from worker packets."""
    lines = _strict_lines(
        text,
        expected_count=len(EXECUTION_SESSION_FIELDS) + 1,
        label="execution session packet",
    )
    if lines[0] != EXECUTION_SESSION_HEADER:
        raise ValueError(f"execution session packet must start with {EXECUTION_SESSION_HEADER}")
    result: dict[str, str] = {}
    for line, label in zip(lines[1:], EXECUTION_SESSION_FIELDS, strict=True):
        prefixes = (f"{label}：", f"{label}:")
        prefix = next((item for item in prefixes if line.startswith(item)), None)
        if prefix is None:
            raise ValueError(f"execution session field order mismatch: {label}")
        value = line[len(prefix) :]
        if not value or value != value.strip():
            raise ValueError(f"execution session field is empty or padded: {label}")
        result[label] = value
    if result["执行 Skill"] != EXECUTION_SESSION_SKILL:
        raise ValueError("execution session must explicitly invoke the canonical Skill")
    task_id = result["任务 ID"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,95}", task_id):
        raise ValueError("execution session task id is unsafe")
    if result["编排深度"] != "0":
        raise ValueError("execution session orchestration depth must be exactly 0")
    project_root = Path(result["项目根目录"])
    if not project_root.is_absolute() or ".." in project_root.parts:
        raise ValueError("execution session project root must be absolute")
    for label in ("任务清单", "团队计划", "进度文件"):
        path = Path(result[label])
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"execution session {label} must be a safe project-relative path")
    base = f".agency/tasks/active/{task_id}"
    expected_paths = {
        "任务清单": f"{base}/task-plan.json",
        "团队计划": f"{base}/TEAM_PLAN.json",
        "进度文件": f"{base}/PROGRESS.md",
    }
    for label, expected in expected_paths.items():
        if result[label] != expected:
            raise ValueError(
                f"execution session {label} is not bound to task {task_id}"
            )
    if result["执行模型请求"] != "GPT-5.6 Sol":
        raise ValueError("execution session model request must be GPT-5.6 Sol")
    if result["推理强度请求"] != "ultra":
        raise ValueError("execution session reasoning request must be ultra")
    if result["执行职责"] != EXECUTION_SESSION_DUTY:
        raise ValueError("execution session duty is not exact")
    if result["停止条件"] != EXECUTION_SESSION_STOP:
        raise ValueError("execution session stop condition is not exact")
    return result


def unwrap_codex_delegation(text: str) -> tuple[str, str]:
    """Unwrap the exact transport envelope emitted by Codex ``create_thread``.

    The envelope is transport metadata, not a second activation syntax. Keeping
    this parser strict prevents arbitrary XML-shaped text from moving a worker
    or an ordinary prompt into the Execution Root path.
    """

    if any(separator in text for separator in "\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
        raise ValueError("Codex delegation envelope must use LF line endings")
    lines = text.splitlines()
    if len(lines) < 5 or lines[0] != CODEX_DELEGATION_HEADER:
        raise ValueError("Codex delegation envelope header is not exact")
    if lines[-1] != CODEX_DELEGATION_FOOTER:
        raise ValueError("Codex delegation envelope footer is not exact")
    source_match = CODEX_DELEGATION_SOURCE_RE.fullmatch(lines[1])
    if source_match is None:
        raise ValueError("Codex delegation source task id is invalid")
    if not lines[2].startswith(CODEX_DELEGATION_INPUT_PREFIX):
        raise ValueError("Codex delegation input opening tag is not exact")
    if not lines[-2].endswith(CODEX_DELEGATION_INPUT_SUFFIX):
        raise ValueError("Codex delegation input closing tag is not exact")
    input_lines = lines[2:-1]
    input_lines[0] = input_lines[0][len(CODEX_DELEGATION_INPUT_PREFIX) :]
    input_lines[-1] = input_lines[-1][: -len(CODEX_DELEGATION_INPUT_SUFFIX)]
    packet = "\n".join(input_lines)
    if not packet:
        raise ValueError("Codex delegation input is empty")
    forbidden_tags = (
        CODEX_DELEGATION_HEADER,
        CODEX_DELEGATION_FOOTER,
        CODEX_DELEGATION_INPUT_PREFIX.strip(),
        CODEX_DELEGATION_INPUT_SUFFIX,
        "<source_thread_id>",
        "</source_thread_id>",
    )
    if any(tag in packet for tag in forbidden_tags):
        raise ValueError("Codex delegation input contains a nested transport tag")
    return packet, source_match.group(1)


def parse_execution_session_transport(text: str) -> dict[str, object]:
    """Parse a raw packet or the strict host envelope that carries one."""

    lines = text.splitlines()
    if lines and lines[0] == CODEX_DELEGATION_HEADER:
        packet, source_thread_id = unwrap_codex_delegation(text)
        transport = "codex_delegation"
    else:
        packet = text
        source_thread_id = None
        transport = "raw"
    fields = parse_execution_session_packet(packet)
    return {
        "packet": packet.removesuffix("\n"),
        "fields": fields,
        "prompt_transport": transport,
        "source_thread_id": source_thread_id,
    }


def match_execution_session_transport(observed: object, expected: str) -> dict[str, object] | None:
    """Return transport proof only when the observed prompt is the exact packet."""

    if not isinstance(observed, str):
        return None
    try:
        expected_transport = parse_execution_session_transport(expected)
        observed_transport = parse_execution_session_transport(observed)
    except ValueError:
        return None
    if expected_transport["prompt_transport"] != "raw":
        return None
    if observed_transport["packet"] != expected_transport["packet"]:
        return None
    return {
        "prompt_transport": observed_transport["prompt_transport"],
        "source_thread_id": observed_transport["source_thread_id"],
    }


def classify_agency_packet(text: str) -> tuple[str, dict[str, str] | None]:
    """Classify one prompt without letting malformed reserved packets become roots.

    Ordinary text is returned unchanged as ``ordinary``. Once a reserved marker
    is the first line, parser failure is terminal and represented by
    :class:`InvalidAgencyPacket`; callers must not route it through normal
    implicit activation.
    """

    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    reserved_pattern = re.compile(
        r"^\s*\ufeff?\s*AGENCY_(WORKER|EXECUTION_SESSION)\s*:\s*true\s*$",
        re.IGNORECASE,
    )
    delegation_marker_pattern = re.compile(
        r"^\s*\ufeff?\s*<\s*/?\s*codex_delegation\b.*$",
        re.IGNORECASE,
    )
    first_reserved = reserved_pattern.fullmatch(first_line)
    if first_line == CODEX_DELEGATION_HEADER:
        try:
            transport = parse_execution_session_transport(text)
            fields = transport["fields"]
            if not isinstance(fields, dict):  # pragma: no cover - internal invariant
                raise ValueError("execution session transport has no parsed fields")
            return "execution_session", fields
        except ValueError as exc:
            raise InvalidAgencyPacket("execution_session", str(exc)) from exc
    if first_reserved and first_reserved.group(1).casefold() == "worker":
        try:
            return "worker", parse_worker_packet(text)
        except ValueError as exc:
            raise InvalidAgencyPacket("worker", str(exc)) from exc
    if first_reserved:
        try:
            return "execution_session", parse_execution_session_packet(text)
        except ValueError as exc:
            raise InvalidAgencyPacket("execution_session", str(exc)) from exc
    reserved_lines = [match for line in lines if (match := reserved_pattern.fullmatch(line))]
    if reserved_lines:
        kind = (
            "worker"
            if any(match.group(1).casefold() == "worker" for match in reserved_lines)
            else "execution_session"
        )
        raise InvalidAgencyPacket(kind, "reserved marker must be the exact first line")
    if any(delegation_marker_pattern.fullmatch(line) for line in lines):
        raise InvalidAgencyPacket(
            "execution_session",
            "Codex delegation envelope must use the exact first-line transport form",
        )
    return "ordinary", None


def parse_reviewer_terminal(text: str) -> dict[str, str]:
    lines = _strict_lines(text, expected_count=len(REVIEW_FIELDS), label="reviewer final")
    result: dict[str, str] = {}
    for line, label in zip(lines, REVIEW_FIELDS, strict=True):
        prefix = f"{label}: "
        if not line.startswith(prefix):
            raise ValueError(f"reviewer final field order mismatch: {prefix}")
        value = line[len(prefix) :]
        if not value or value != value.strip():
            raise ValueError(f"reviewer final field is empty or padded: {label}")
        result[label] = value
    if result["REVIEW_VERDICT"] not in REVIEW_VERDICTS:
        raise ValueError("reviewer verdict must be exactly PASS or FAIL")
    return result
