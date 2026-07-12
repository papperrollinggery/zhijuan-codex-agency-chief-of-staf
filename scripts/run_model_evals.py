#!/usr/bin/env python3
"""Run real Codex smoke cases in an isolated project/config fixture.

This is not a credential-security boundary. The evaluated process runs as the
current OS user and can theoretically read its temporary auth file. Use only a
reviewed checkout and a dedicated low-privilege evaluation credential, ideally
inside a disposable OS user or container.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import pwd
except ImportError:  # pragma: no cover - unavailable on Windows
    pwd = None  # type: ignore[assignment]


def _load_bound_installer_source() -> tuple[types.ModuleType, Path, bytes]:
    """Compile the exact sibling source bytes; never execute ambient bytecode."""
    path = Path(__file__).with_name("install_skill.py")
    if path.is_symlink() or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("installer helper source cannot be opened without following links")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024 * 1024:
            raise RuntimeError("installer helper source is not a bounded regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise RuntimeError("installer helper source changed while loading")
    finally:
        os.close(descriptor)
    source_bytes = b"".join(chunks)
    module = types.ModuleType("_agency_bound_install_skill")
    module.__file__ = str(path)
    module.__package__ = ""
    exec(compile(source_bytes, str(path), "exec"), module.__dict__)
    return module, path, source_bytes


installer_module, BOUND_INSTALLER_PATH, BOUND_INSTALLER_BYTES = (
    _load_bound_installer_source()
)
INSTALL_NAMES = installer_module.INSTALL_NAMES
LEGACY_SKILL_NAME = installer_module.LEGACY_SKILL_NAME
SEALED_DIRECTORY_MODE = installer_module.SEALED_DIRECTORY_MODE
SEALED_ROOT_MODE = installer_module.SEALED_ROOT_MODE
SEALED_TREE_POLICY = installer_module.SEALED_TREE_POLICY
SKILL_NAME = installer_module.SKILL_NAME
copy_runtime = installer_module.copy_runtime
existing_transaction_artifacts = installer_module.existing_transaction_artifacts
installed_manifest = installer_module.installed_manifest
paths_overlap = installer_module.paths_overlap
rendered_runtime_manifest = installer_module.rendered_runtime_manifest
runtime_directory_paths = installer_module.runtime_directory_paths
runtime_file_mode = installer_module.runtime_file_mode
runtime_manifest = installer_module.runtime_manifest


TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "computer_use",
}
ASSISTANT_ITEM_TYPES = {"agent_message", "assistant_message"}
CASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
REASONING_EFFORT_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
EXECUTION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
CLI_VERSION_VALUE_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}\Z")
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
ALLOWED_MODES = {"direct", "structured", "goal", "worker"}
ALLOWED_COLLABORATION = {
    "none",
    "native_subagents",
    "native_subagents_optional",
    "real_task",
}
ALLOWED_ACTIVATION = {"explicit", "implicit", "ordinary", "worker"}
ALLOWED_ENTRYPOINTS = {"canonical", "legacy", "none"}
ALLOWED_GUARD_BUNDLES = {"none", "canonical", "legacy"}
LOCKED_MODEL_PROVIDER = "openai"
STABLE_RELEASE_SUPPORTED = False
REVIEW_NO_BLOCKERS_VERDICT = "REVIEW_VERDICT: NO_BLOCKING_FINDINGS"
REVIEW_FINDINGS_COUNT_ZERO = "REVIEW_FINDINGS_COUNT: 0"
REVIEW_EVIDENCE_FIRST_LINE_PREFIX = "REVIEW_EVIDENCE_FIRST_LINE: "
REVIEW_EVIDENCE_TARGET_LINE_PREFIX = "REVIEW_EVIDENCE_TARGET_LINE: "
MAIN_REVIEW_ADOPTION_ACCEPTED = "MAIN_REVIEW_ADOPTION: ACCEPTED"
COLD_CONTEXT_ISOLATION_UNVERIFIED = "COLD_CONTEXT_ISOLATION: UNVERIFIED"
REVIEWER_OWNED_READ_UNVERIFIED = "reviewer-owned read 未验证"
NATURAL_REVIEW_FILE_PREFIX = "NATURAL_REVIEW_FILE: "
NATURAL_REVIEW_TARGET_PREFIX = "NATURAL_REVIEW_TARGET: "
CANONICAL_PRELOAD_ANNOUNCEMENT = (
    "我将使用 $agency-chief-of-staff，遵照你的范围。"
)
MAIN_PROGRESS_SEQUENCE = (
    "MAIN_PROGRESS: INSPECT",
    "MAIN_PROGRESS: PLAN",
    "MAIN_PROGRESS: EDIT",
    "MAIN_PROGRESS: VERIFY",
    "MAIN_PROGRESS: REVIEW_DISPATCH",
    "MAIN_PROGRESS: REVIEW_WAIT",
)
STRICT_REVIEW_PROGRESS = "REVIEW_PROGRESS: READING_ARTIFACT"
NATURAL_REVIEW_PROGRESS = "REVIEW_PROGRESS: CHECKING_ARTIFACT"
OPENAI_APPLE_TEAM_ID = "2DC432GLL2"
OPENAI_CODEX_IDENTIFIER = "codex"
OPENAI_CODE_MODE_HOST_IDENTIFIER = "codex-code-mode-host"
MAX_PRELOAD_MESSAGES = 2
RECOVERABLE_TRANSPORT_FAILURE_PATTERNS = (
    re.compile(r"error: Reconnecting\.\.\. [1-5]/5 \(request timed out\)\Z"),
    re.compile(
        r"error: Reconnecting\.\.\. [1-5]/5 "
        r"\(stream disconnected before completion: error sending request for url "
        r"\(https://chatgpt\.com/backend-api/codex/responses\)\)\Z"
    ),
    re.compile(
        r"error: Falling back from WebSockets to HTTPS transport\. request timed out\Z"
    ),
)
PRELOAD_BUSINESS_MARKERS = (
    "结论：",
    "结论是",
    "结果：",
    "结果是",
    "当前实现",
    "严重",
    "缺陷",
    "可发布",
    "不可发布",
    "通过",
    "失败",
    "存在风险",
    "发现风险",
    "已发现",
    "发现了",
    "证据显示",
    "已读取",
    "已检查",
    "已验证",
    "已修改",
    "已经修改",
    "测试通过",
    "测试失败",
    "先检查文件",
    "然后修改",
    "运行测试",
    "接下来先做",
    "三步排查",
    "repository name",
    "agency-model-eval-fixture",
    "conclusion:",
    "conclusion is",
    "result:",
    "result is",
    "has passed",
    "tests passed",
    "has failed",
    "tests failed",
    "ready for release",
    "not ready for release",
    "has been verified",
    "is verified",
    "has been fixed",
    "is fixed",
)
PRELOAD_RESULT_RE = re.compile(
    r"(?:审核|审计|核查|核验|验证|任务|工作|处理)(?:已|已经)?完成"
)
PROMPT_NEGATION_PREFIXES = (
    "不要",
    "不得",
    "禁止",
    "不可",
    "无需",
    "无须",
    "不",
    "别",
    "donot",
    "dont",
    "mustnot",
    "never",
)
PRELOAD_ANNOUNCEMENT_META_VOCABULARY = (
    "因为你已显式指定",
    "你已显式指定",
    "用户显式指定的",
    "用户指定的",
    "你指定的",
    "你显式指定的",
    "显式指定的",
    "这是用户显式指定",
    "用户给定的",
    "用户给定",
    "任务范围限定为",
    "限制为",
    "限定为",
    "当前选定的",
    "按其规则停用",
    "不会双启动",
    "遵照你的范围",
    "不执行任务",
    "chief of staff",
    "for this task",
    "cold review",
    "agency-chief-of-staff",
    "zhijuan-codex-agency-chief-of-staf",
    "我将",
    "我会",
    "现在",
    "使用",
    "启用",
    "启动",
    "采用",
    "执行",
    "幕僚长",
    "技能",
    "skill",
    "bundle",
    "legacy",
    "规范",
    "兼容",
    "入口",
    "显式",
    "选择",
    "规则",
    "停用",
    "双启动",
    "双入口",
    "操作",
    "仅",
    "双",
    "严格",
    "保持",
    "遵守",
    "遵照",
    "范围",
    "方法",
    "方式",
    "流程",
    "闭环",
    "审计",
    "审核",
    "核查",
    "核验",
    "验证",
    "依赖",
    "新鲜",
    "最小",
    "行数",
    "完成",
    "任务",
    "识别",
    "处理",
    "查询",
    "只读取",
    "只读",
    "不修改任何文件",
    "不修改文件",
    "全程",
    "并且",
    "并",
    "且",
    "与",
    "的",
    "按",
    "其",
    "对",
    "来",
    "此",
    "这项",
    "这次",
    "你的",
    "i will",
    "i'll",
    "i am",
    "i'm",
    "using",
    "applying",
    "use",
    "apply",
    "the",
    "selected",
    "specified",
    "current",
)
PRELOAD_RECOVERY_VOCABULARY = (
    "技能路径首次定位失败",
    "会话提供的位置",
    "读取指令",
    "我会",
    "我将",
    "改用",
    "重试",
    "技能",
    "skill",
    "路径",
    "path",
    "位置",
    "location",
    "定位",
    "locate",
    "读取",
    "read",
    "失败",
    "failed",
    "retry",
    "provided",
    "instruction",
    "instructions",
    "use",
    "the",
    "i will",
    "i'll",
)
TRUSTED_RIPGREP_CANDIDATES = (
    Path("/opt/homebrew/bin/rg"),
    Path("/usr/local/bin/rg"),
    Path("/usr/bin/rg"),
)
REQUIRED_SMOKE_CONTRACT = {
    "explicit-small-direct": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "legacy-explicit-small-direct": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "legacy",
        "allow_preload_announcement": True,
    },
    "explicit-readonly-structured": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "delegated-worker-bypass": {
        "should_trigger": False,
        "mode": "worker",
        "collaboration": "none",
        "activation": "worker",
        "expected_entrypoint": "none",
        "allowed_guard_bundle": "canonical",
    },
    "legacy-delegated-worker-bypass": {
        "should_trigger": False,
        "mode": "worker",
        "collaboration": "none",
        "activation": "worker",
        "expected_entrypoint": "none",
        "allowed_guard_bundle": "legacy",
    },
    "invalid-worker-marker-main-session": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "invalid-worker-packet-missing-field": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "invalid-worker-packet-duplicate-field": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "invalid-worker-packet-out-of-order": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "invalid-worker-packet-empty-field": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "explicit-write-execute": {
        "should_trigger": True,
        "mode": "structured",
        "collaboration": "native_subagents",
        "activation": "explicit",
        "sandbox": "workspace-write",
        "require_collab_event": True,
        "review_evidence_tier": "rc",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "explicit-full-cycle": {
        "should_trigger": True,
        "mode": "structured",
        "collaboration": "native_subagents",
        "activation": "explicit",
        "sandbox": "workspace-write",
        "require_collab_completion": True,
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "implicit-chief-of-staff-read": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "implicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "dual-explicit-canonical-priority": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
        "expected_entrypoint": "canonical",
        "allow_preload_announcement": True,
    },
    "legacy-slug-mentioned-negative": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
        "must_contain": ["OK"],
        "exact_final": "OK",
        "require_no_tool_events": True,
    },
    "ordinary-small-answer": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
        "exact_final": "你好",
        "require_no_tool_events": True,
    },
    "ordinary-readiness-phrase": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
        "exact_final": "2",
        "require_no_tool_events": True,
    },
    "ordinary-rescue-phrase": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
        "exact_final": "6",
        "require_no_tool_events": True,
    },
    "ordinary-focused-code-fix": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
    },
    "ordinary-code-review": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
        "expected_entrypoint": "none",
    },
}
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
SAFE_ENV_KEYS = {
    "PATH",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "USER",
    "LOGNAME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NO_COLOR",
}
PROCESS_GROUP_TERM_GRACE_SECONDS = 2.0
PROCESS_GROUP_KILL_GRACE_SECONDS = 2.0
PROCESS_GROUP_POLL_SECONDS = 0.02
MAX_ROLLOUT_IDENTITY_FILE_BYTES = 64 * 1024 * 1024
MAX_ROLLOUT_TREE_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ROLLOUT_TREE_ENTRIES = 2048
MAX_ROLLOUT_TREE_DEPTH = 16
MAX_GIT_METADATA_TREE_ENTRIES = 32_768
MAX_GIT_METADATA_TREE_DEPTH = 64
MAX_GIT_METADATA_FILE_BYTES = 128 * 1024 * 1024
MAX_GIT_METADATA_TREE_BYTES = 512 * 1024 * 1024
INVALID_STAGING_SEAL = "INVALID_MODEL_SMOKE_RECEIPT"
AUTH_REDACTION_MARKER = "[REDACTED_EVAL_AUTH_VALUE]"
INVALID_JSONL_REDACTION_PREFIX = "!INVALID_JSONL_REDACTED!"


def receipt_error_code(_exc: BaseException, code: str) -> str:
    """Return a fixed receipt-safe code without serializing private exception data."""
    if re.fullmatch(r"E_[A-Z0-9_]+", code) is None:
        raise RuntimeError("E_INVALID_RECEIPT_ERROR_CODE")
    return code


def safe_error_text(exc: BaseException) -> str:
    text = str(exc)
    if re.fullmatch(r"E_[A-Z0-9_]+", text):
        return text
    return re.sub(
        r"(?<![A-Za-z0-9+.-])/(?:[^\s'\"<>|]+)",
        "<PRIVATE_PATH>",
        text,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_nofollow(path: Path) -> bytes:
    """Read one regular file without following a final-component symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeError("E_PRIVATE_FILE_OPEN") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("E_PRIVATE_FILE_NOT_REGULAR")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_regular_nofollow_limited(path: Path, max_bytes: int) -> bytes:
    """Read a regular file through O_NOFOLLOW with a hard size bound."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeError("E_PRIVATE_FILE_OPEN") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("E_PRIVATE_FILE_NOT_REGULAR")
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise RuntimeError("E_PRIVATE_FILE_TOO_LARGE")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total)):
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("E_PRIVATE_FILE_TOO_LARGE")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def native_executable_format(content: bytes) -> str | None:
    if content.startswith(b"\x7fELF"):
        return "elf"
    if content[:4] in {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }:
        return "mach-o"
    if content.startswith(b"MZ") and len(content) >= 64:
        pe_offset = int.from_bytes(content[60:64], "little")
        if pe_offset + 4 <= len(content) and content[pe_offset : pe_offset + 4] == b"PE\0\0":
            return "pe"
    return None


def probe_codex_executable(path: Path) -> dict[str, object]:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise RuntimeError("--codex-executable must be an absolute native binary path")
    if expanded.is_symlink():
        raise RuntimeError("--codex-executable must not be a symlink or wrapper")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError:
        raise RuntimeError("E_CODEX_BINARY_RESOLVE") from None
    if not resolved.is_file():
        raise RuntimeError("--codex-executable must be a regular file")
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        raise RuntimeError("--codex-executable must be executable")
    content = read_regular_nofollow(resolved)
    executable_format = native_executable_format(content)
    if executable_format is None:
        raise RuntimeError(
            "--codex-executable must be a native Mach-O, ELF, or PE binary; "
            "shell and Node launchers are rejected"
        )
    return {
        "path": str(resolved),
        "format": executable_format,
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
        "native_format_detected": True,
    }


def receipt_status(full_run: bool, results: list[dict[str, object]]) -> str:
    if not results or not all(item.get("status") == "passed" for item in results):
        return "failed"
    return "passed" if full_run else "passed_partial"


def configuration_requests_accepted(
    results: list[dict[str, object]], expected_count: int
) -> bool:
    return (
        bool(results)
        and len(results) == expected_count
        and all(
            result.get("configuration_request_accepted") is True
            for result in results
        )
    )


def release_eligibility(
    status: str,
    full_run: bool,
    explicit_model: bool,
    explicit_reasoning_effort: bool,
    credential_class: str,
    credential_provenance_verified: bool,
    execution_identity_verified: bool,
    installed_binding_verified: bool,
    installed_cleanup_verified: bool,
    untested_capabilities: list[str],
) -> tuple[bool, bool]:
    prerelease = (
        status == "passed"
        and full_run
        and explicit_model
        and explicit_reasoning_effort
        and credential_class == "dedicated"
        and credential_provenance_verified
        and execution_identity_verified
        and installed_binding_verified
        and installed_cleanup_verified
    )
    stable = prerelease and not untested_capabilities
    return prerelease, stable


def artifact_rc_evidence_eligibility(
    status: str,
    full_run: bool,
    explicit_model: bool,
    explicit_reasoning_effort: bool,
    execution_identity_verified: bool,
    installed_binding_verified: bool,
    installed_cleanup_verified: bool,
    auth_handling_integrity_verified: bool,
) -> bool:
    """Machine-checkable artifact behavior evidence, not source trust or isolation."""
    return (
        status == "passed"
        and full_run
        and explicit_model
        and explicit_reasoning_effort
        and execution_identity_verified
        and installed_binding_verified
        and installed_cleanup_verified
        and auth_handling_integrity_verified
    )


def verified_installed_release_binding(
    installed_binding_verified: bool,
    installed_pair_manifest_verified: bool,
    installed_tree_integrity_verified: bool,
    installed_drift_detected: bool,
    routing_context_verified: bool,
) -> bool:
    """Bind RC evidence to one unchanged sealed global pair and frozen snapshot."""
    return (
        installed_binding_verified
        and installed_pair_manifest_verified
        and installed_tree_integrity_verified
        and not installed_drift_detected
        and routing_context_verified
    )


def source_input_drift_detected(
    root: Path,
    source_manifest: dict[str, str],
    cases_path: Path,
    cases_bytes: bytes,
    runner_path: Path,
    runner_bytes: bytes,
    installer_path: Path,
    installer_bytes: bytes,
) -> bool:
    """Bind every local source that can affect model-smoke evidence."""
    try:
        return (
            runtime_manifest(root) != source_manifest
            or read_regular_nofollow(cases_path) != cases_bytes
            or read_regular_nofollow(runner_path) != runner_bytes
            or read_regular_nofollow(installer_path) != installer_bytes
        )
    except (OSError, ValueError, RuntimeError):
        return True


def release_tier_requirement_met(
    tier: str | None,
    rc_eligible: bool,
    stable_eligible: bool,
) -> bool:
    return {
        None: True,
        "rc": rc_eligible,
        "prerelease": rc_eligible,
        "stable": stable_eligible,
    }[tier]


def write_new_text(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def write_new_bytes(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def build_isolated_env(
    home: Path, codex_home: Path, source: dict[str, str] | None = None
) -> dict[str, str]:
    parent = os.environ if source is None else source
    env = {key: value for key, value in parent.items() if key in SAFE_ENV_KEYS}
    env["PATH"] = os.defpath
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def os_account_home() -> Path:
    """Resolve the current OS account home without trusting HOME."""
    if pwd is None:
        raise RuntimeError(
            "OS-account home lookup is unavailable on this platform; "
            "credential comparison cannot be anchored safely"
        )
    value = pwd.getpwuid(os.getuid()).pw_dir
    home = Path(value)
    if not home.is_absolute() or not home.is_dir():
        raise RuntimeError("OS account database returned an unusable home directory")
    return home.resolve()


def trusted_helper_executable(name: str) -> Path:
    """Resolve a runner helper only from the OS default path."""
    candidate = shutil.which(name, path=os.defpath)
    if candidate is None:
        raise RuntimeError(f"required trusted helper is unavailable in os.defpath: {name}")
    resolved = Path(candidate).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError(f"trusted helper is not an executable regular file: {name}")
    metadata = resolved.stat()
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(f"trusted helper is group/world writable: {resolved}")
    if os.name != "nt" and metadata.st_uid not in {0, os.getuid()}:
        raise RuntimeError(f"trusted helper has an unexpected owner: {resolved}")
    return resolved


def helper_subprocess_env() -> dict[str, str]:
    return {
        "HOME": str(os_account_home()),
        "PATH": os.defpath,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def freeze_codex_executable(
    source: Path, destination: Path, expected_probe: dict[str, object]
) -> dict[str, object]:
    """Copy the exact probed bytes to a private executable used for every case."""
    content = read_regular_nofollow(source)
    if (
        sha256_bytes(content) != expected_probe.get("sha256")
        or len(content) != expected_probe.get("size_bytes")
    ):
        raise RuntimeError("Codex executable changed before the private copy was frozen")
    write_new_bytes(destination, content)
    destination.chmod(0o700)
    frozen = probe_codex_executable(destination)
    for field in ("format", "sha256", "size_bytes", "native_format_detected"):
        if frozen.get(field) != expected_probe.get(field):
            raise RuntimeError("private Codex executable copy did not match the probed source")
    return frozen


def verify_codex_executable_provenance(
    path: Path,
    executable_format: object,
    expected_identifier: str = OPENAI_CODEX_IDENTIFIER,
) -> dict[str, object]:
    """Fail closed unless this platform can verify an OpenAI-signed Codex binary."""
    evidence: dict[str, object] = {
        "verified": False,
        "method": "unsupported_platform_or_format",
        "identifier": None,
        "team_id": None,
    }
    if sys.platform != "darwin" or executable_format != "mach-o":
        return evidence
    codesign = Path("/usr/bin/codesign")
    try:
        metadata = os.lstat(codesign)
    except OSError:
        evidence["method"] = "apple_codesign_unavailable"
        return evidence
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        evidence["method"] = "apple_codesign_untrusted_path"
        return evidence
    requirement = (
        f'anchor apple generic and identifier "{expected_identifier}" '
        f'and certificate leaf[subject.OU] = "{OPENAI_APPLE_TEAM_ID}"'
    )
    result = subprocess.run(
        [
            str(codesign),
            "--verify",
            "--strict",
            f"-R={requirement}",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=helper_subprocess_env(),
    )
    if result.returncode != 0:
        evidence["method"] = "apple_codesign_requirement_failed"
        return evidence
    evidence.update(
        {
            "verified": True,
            "method": "apple_codesign_designated_requirement",
            "identifier": expected_identifier,
            "team_id": OPENAI_APPLE_TEAM_ID,
        }
    )
    return evidence


def combined_codex_executable_provenance_verified(
    main_before: dict[str, object],
    main_after: dict[str, object] | None,
    code_mode_host_required: bool,
    code_mode_host_before: dict[str, object] | None,
    code_mode_host_after: dict[str, object] | None,
    private_drift_detected: bool,
) -> bool:
    """Require the signed code-mode host whenever macOS Mach-O RC does."""
    main_verified = (
        main_before.get("verified") is True and main_after == main_before
    )
    code_mode_host_verified = (
        not code_mode_host_required
        or (
            code_mode_host_before is not None
            and code_mode_host_before.get("verified") is True
            and code_mode_host_after == code_mode_host_before
        )
    )
    return main_verified and code_mode_host_verified and not private_drift_detected


def copy_verified_installed_bundle(
    source: Path, destination: Path, expected_manifest: dict[str, str]
) -> dict[str, str]:
    """Freeze one already manifest-verified installed bundle into a clean HOME."""
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("installed snapshot destination already exists")
    source_metadata = os.lstat(source)
    if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISDIR(
        source_metadata.st_mode
    ):
        raise RuntimeError("installed snapshot source was not a real directory")
    destination.mkdir(parents=True, mode=SEALED_ROOT_MODE)
    destination.chmod(SEALED_ROOT_MODE)
    for relative_text, expected_sha256 in sorted(expected_manifest.items()):
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise RuntimeError("installed manifest contained an unsafe relative path")
        source_file = source.joinpath(*relative.parts)
        current = source
        for part in relative.parts[:-1]:
            current = current / part
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("installed bundle contained an unsafe directory path")
        content = read_regular_nofollow(source_file)
        if sha256_bytes(content) != expected_sha256:
            raise RuntimeError("installed bundle changed while freezing the snapshot")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new_bytes(target, content)
        target.chmod(runtime_file_mode(relative_text))
    for relative_text in sorted(runtime_directory_paths(expected_manifest)):
        (destination / relative_text).chmod(SEALED_DIRECTORY_MODE)
    actual = installed_manifest(destination, expected_manifest)
    if actual != expected_manifest:
        raise RuntimeError("frozen installed snapshot did not match its source manifest")
    return actual


def receipt_path(path: Path, account_home: Path) -> str:
    resolved = path.expanduser().resolve(strict=False)
    if resolved == account_home:
        return "<OS_HOME>"
    if resolved.is_relative_to(account_home):
        return str(PurePosixPath("<OS_HOME>", *resolved.relative_to(account_home).parts))
    return str(PurePosixPath("<ABSOLUTE_PATH>", resolved.name))


def build_private_shell_tool_path(private_bin: Path) -> tuple[str, dict[str, object]]:
    """Build PATH from os.defpath plus a private, verified copy of ripgrep."""
    if private_bin.exists() or private_bin.is_symlink():
        raise RuntimeError(f"private tool directory already exists: {private_bin}")
    private_bin.mkdir(mode=0o700)
    ripgrep_source: Path | None = None
    ripgrep_bytes: bytes | None = None
    for candidate in TRUSTED_RIPGREP_CANDIDATES:
        if not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        resolved = candidate.resolve(strict=True)
        trusted_prefix = candidate.parent.parent.resolve(strict=False)
        if not resolved.is_relative_to(trusted_prefix):
            continue
        metadata = resolved.stat()
        if (
            not resolved.is_file()
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or (os.name != "nt" and metadata.st_uid not in {0, os.getuid()})
        ):
            continue
        content = read_regular_nofollow(resolved)
        if native_executable_format(content) is None:
            continue
        ripgrep_source = resolved
        ripgrep_bytes = content
        break
    if ripgrep_source is None or ripgrep_bytes is None:
        raise RuntimeError(
            "trusted native ripgrep was not found in an approved system/Homebrew location"
        )
    private_rg = private_bin / "rg"
    write_new_bytes(private_rg, ripgrep_bytes)
    private_rg.chmod(0o500)
    directories = [str(private_bin)]
    for value in os.defpath.split(os.pathsep):
        if not value:
            continue
        resolved = Path(value).resolve(strict=False)
        if resolved.is_dir():
            directories.append(str(resolved))
    unique = list(dict.fromkeys(directories))
    if any(os.pathsep in value or "\n" in value or "\r" in value for value in unique):
        raise RuntimeError("cannot construct a safe explicit shell tool PATH")
    return os.pathsep.join(unique), {
        "source_path": str(ripgrep_source),
        "private_copy_path": str(private_rg),
        "sha256": sha256_bytes(ripgrep_bytes),
        "native_format_detected": native_executable_format(ripgrep_bytes),
    }


def collect_auth_secrets(value: object, sensitive_context: bool = False) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_sensitive = sensitive_context or any(
                marker in str(key).lower()
                for marker in ("token", "secret", "password", "api_key", "cookie")
            )
            secrets.update(collect_auth_secrets(child, key_sensitive))
    elif isinstance(value, list):
        for child in value:
            secrets.update(collect_auth_secrets(child, sensitive_context))
    elif isinstance(value, str) and value and (sensitive_context or len(value) >= 16):
        secrets.add(value)
    return secrets


def redact_exact_auth_values(text: str, secrets: set[str]) -> tuple[str, bool]:
    matched = False
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        replacement = AUTH_REDACTION_MARKER if secret not in AUTH_REDACTION_MARKER else ""
        variants = {
            secret,
            json.dumps(secret, ensure_ascii=False)[1:-1],
            json.dumps(secret, ensure_ascii=True)[1:-1],
        }
        for variant in sorted((value for value in variants if value), key=len, reverse=True):
            if variant in redacted:
                matched = True
                redacted = redacted.replace(variant, replacement)
    return redacted, matched


def split_jsonl_records(text: str) -> list[str]:
    """Split JSONL only on LF; Unicode line separators are valid JSON data."""
    if not text:
        return []
    records = text.split("\n")
    if text.endswith("\n"):
        records.pop()
    return [record[:-1] if record.endswith("\r") else record for record in records]


def normalized_absolute_path(value: object) -> str | None:
    """Canonicalize an absolute path without retaining the raw input value."""
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    if not os.path.isabs(value):
        return None
    try:
        return os.path.realpath(value)
    except (OSError, ValueError):
        return None


def _open_directory_nofollow(path: str | Path, dir_fd: int | None = None) -> int:
    """Open one directory component without following a symlink."""
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("E_ROLLOUT_SECURE_OPEN_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, dir_fd=dir_fd)
    except OSError:
        raise RuntimeError("E_ROLLOUT_DIRECTORY_OPEN") from None
    try:
        metadata = os.fstat(descriptor)
    except OSError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise RuntimeError("E_ROLLOUT_DIRECTORY_STAT") from None
    if not stat.S_ISDIR(metadata.st_mode):
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise RuntimeError("E_ROLLOUT_DIRECTORY_TYPE")
    return descriptor


def stable_stat_signature(metadata: os.stat_result) -> tuple[int, ...]:
    """Return mutation-sensitive metadata without access-time noise."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def snapshot_isolated_rollouts(
    codex_home: Path,
    expected_root_identity: tuple[int, int] | None = None,
) -> tuple[dict[PurePosixPath, bytes], list[str]]:
    """Create a bounded snapshot stable across two root-anchored scans."""
    try:
        root_fd = _open_directory_nofollow(codex_home)
    except RuntimeError:
        return {}, ["isolated Codex home root could not be securely opened"]
    try:
        root_before = os.fstat(root_fd)
        root_identity = (root_before.st_dev, root_before.st_ino)
        if expected_root_identity is not None and root_identity != expected_root_identity:
            raise RuntimeError("E_ROLLOUT_ROOT_CHANGED")
        sessions_fd = _open_directory_nofollow("sessions", dir_fd=root_fd)
        try:
            sessions_before = os.fstat(sessions_fd)

            def read_file(
                directory_fd: int, name: str, expected: os.stat_result
            ) -> tuple[bytes, tuple[int, ...]]:
                flags = (
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                )
                try:
                    file_fd = os.open(name, flags, dir_fd=directory_fd)
                except OSError:
                    raise RuntimeError("E_ROLLOUT_FILE_OPEN") from None
                try:
                    before = os.fstat(file_fd)
                    if stable_stat_signature(before) != stable_stat_signature(expected):
                        raise RuntimeError("E_ROLLOUT_FILE_REBOUND")
                    if not stat.S_ISREG(before.st_mode):
                        raise RuntimeError("E_ROLLOUT_FILE_TYPE")
                    if (
                        before.st_size < 0
                        or before.st_size > MAX_ROLLOUT_IDENTITY_FILE_BYTES
                    ):
                        raise RuntimeError("E_ROLLOUT_FILE_TOO_LARGE")
                    chunks: list[bytes] = []
                    size = 0
                    while chunk := os.read(
                        file_fd,
                        min(
                            1024 * 1024,
                            MAX_ROLLOUT_IDENTITY_FILE_BYTES + 1 - size,
                        ),
                    ):
                        size += len(chunk)
                        if size > MAX_ROLLOUT_IDENTITY_FILE_BYTES:
                            raise RuntimeError("E_ROLLOUT_FILE_TOO_LARGE")
                        chunks.append(chunk)
                    after = os.fstat(file_fd)
                    if stable_stat_signature(before) != stable_stat_signature(
                        after
                    ) or size != after.st_size:
                        raise RuntimeError("E_ROLLOUT_FILE_CHANGED")
                    try:
                        rebound = os.stat(
                            name, dir_fd=directory_fd, follow_symlinks=False
                        )
                    except OSError:
                        raise RuntimeError("E_ROLLOUT_FILE_REBOUND") from None
                    if stable_stat_signature(rebound) != stable_stat_signature(after):
                        raise RuntimeError("E_ROLLOUT_FILE_REBOUND")
                    return b"".join(chunks), stable_stat_signature(after)
                finally:
                    os.close(file_fd)

            def scan_once() -> tuple[
                dict[PurePosixPath, bytes], dict[PurePosixPath, tuple[int, ...]]
            ]:
                snapshot: dict[PurePosixPath, bytes] = {}
                manifest: dict[PurePosixPath, tuple[int, ...]] = {}
                entry_count = 0
                total_bytes = 0

                def visit(
                    directory_fd: int, prefix: tuple[str, ...], depth: int
                ) -> None:
                    nonlocal entry_count, total_bytes
                    if depth > MAX_ROLLOUT_TREE_DEPTH:
                        raise RuntimeError("E_ROLLOUT_TREE_DEPTH")
                    directory_before = os.fstat(directory_fd)
                    try:
                        with os.scandir(directory_fd) as entries:
                            names = sorted(entry.name for entry in entries)
                    except OSError:
                        raise RuntimeError("E_ROLLOUT_TREE_ENUMERATION") from None
                    for name in names:
                        entry_count += 1
                        if entry_count > MAX_ROLLOUT_TREE_ENTRIES:
                            raise RuntimeError("E_ROLLOUT_TREE_ENTRIES")
                        if (
                            not name
                            or name in {".", ".."}
                            or "/" in name
                            or "\x00" in name
                        ):
                            raise RuntimeError("E_ROLLOUT_TREE_NAME")
                        try:
                            metadata = os.stat(
                                name, dir_fd=directory_fd, follow_symlinks=False
                            )
                        except OSError:
                            raise RuntimeError("E_ROLLOUT_TREE_STAT") from None
                        relative = PurePosixPath(*prefix, name)
                        if stat.S_ISLNK(metadata.st_mode):
                            raise RuntimeError("E_ROLLOUT_TREE_SYMLINK")
                        if stat.S_ISDIR(metadata.st_mode):
                            child_fd = _open_directory_nofollow(
                                name, dir_fd=directory_fd
                            )
                            try:
                                opened = os.fstat(child_fd)
                                if stable_stat_signature(opened) != stable_stat_signature(
                                    metadata
                                ):
                                    raise RuntimeError("E_ROLLOUT_DIRECTORY_CHANGED")
                                visit(child_fd, (*prefix, name), depth + 1)
                                child_after = os.fstat(child_fd)
                            finally:
                                os.close(child_fd)
                            try:
                                rebound = os.stat(
                                    name,
                                    dir_fd=directory_fd,
                                    follow_symlinks=False,
                                )
                            except OSError:
                                raise RuntimeError(
                                    "E_ROLLOUT_DIRECTORY_REBOUND"
                                ) from None
                            if stable_stat_signature(rebound) != stable_stat_signature(
                                child_after
                            ):
                                raise RuntimeError("E_ROLLOUT_DIRECTORY_REBOUND")
                            manifest[relative] = stable_stat_signature(child_after)
                            continue
                        if not stat.S_ISREG(metadata.st_mode):
                            raise RuntimeError("E_ROLLOUT_TREE_SPECIAL_FILE")
                        if name.endswith(".jsonl"):
                            content, file_signature = read_file(
                                directory_fd, name, metadata
                            )
                            total_bytes += len(content)
                            if total_bytes > MAX_ROLLOUT_TREE_TOTAL_BYTES:
                                raise RuntimeError("E_ROLLOUT_TREE_BYTES")
                            snapshot[relative] = content
                            manifest[relative] = file_signature + (
                                int.from_bytes(
                                    hashlib.sha256(content).digest()[:8], "big"
                                ),
                            )
                        else:
                            manifest[relative] = stable_stat_signature(metadata)
                    try:
                        with os.scandir(directory_fd) as entries:
                            names_after = sorted(entry.name for entry in entries)
                    except OSError:
                        raise RuntimeError("E_ROLLOUT_TREE_ENUMERATION") from None
                    directory_after = os.fstat(directory_fd)
                    if (
                        names_after != names
                        or stable_stat_signature(directory_after)
                        != stable_stat_signature(directory_before)
                    ):
                        raise RuntimeError("E_ROLLOUT_DIRECTORY_CHANGED")
                    manifest[PurePosixPath(*prefix, ".")] = stable_stat_signature(
                        directory_after
                    )

                visit(sessions_fd, (), 0)
                return snapshot, manifest

            snapshot, tree_manifest = scan_once()
            second_snapshot, second_manifest = scan_once()
            if snapshot != second_snapshot or tree_manifest != second_manifest:
                raise RuntimeError("E_ROLLOUT_TREE_UNSTABLE")
            sessions_after = os.fstat(sessions_fd)
            if stable_stat_signature(sessions_before) != stable_stat_signature(
                sessions_after
            ):
                raise RuntimeError("E_ROLLOUT_SESSIONS_CHANGED")
            try:
                sessions_name_after = os.stat(
                    "sessions", dir_fd=root_fd, follow_symlinks=False
                )
            except OSError:
                raise RuntimeError("E_ROLLOUT_SESSIONS_REBOUND") from None
            if (
                not stat.S_ISDIR(sessions_name_after.st_mode)
                or (sessions_name_after.st_dev, sessions_name_after.st_ino)
                != (sessions_before.st_dev, sessions_before.st_ino)
            ):
                raise RuntimeError("E_ROLLOUT_SESSIONS_REBOUND")
        finally:
            os.close(sessions_fd)
        root_after = os.fstat(root_fd)
        if stable_stat_signature(root_after) != stable_stat_signature(root_before):
            raise RuntimeError("E_ROLLOUT_ROOT_CHANGED")
        try:
            path_metadata = os.lstat(codex_home)
        except OSError:
            raise RuntimeError("E_ROLLOUT_ROOT_CHANGED") from None
        if (
            stat.S_ISLNK(path_metadata.st_mode)
            or stable_stat_signature(path_metadata)
            != stable_stat_signature(root_after)
        ):
            raise RuntimeError("E_ROLLOUT_ROOT_CHANGED")
    except (OSError, RuntimeError, ValueError):
        snapshot = {}
        failures = ["isolated Codex rollout tree changed or contained unsafe entries"]
    else:
        failures = []
    try:
        os.close(root_fd)
    except OSError:
        snapshot = {}
        failures = ["isolated Codex rollout tree changed or contained unsafe entries"]
    return snapshot, failures


def isolated_rollout_files(
    codex_home: Path,
) -> tuple[list[PurePosixPath], list[str]]:
    snapshot, failures = snapshot_isolated_rollouts(codex_home)
    return sorted(snapshot), failures


def read_isolated_rollout_limited(
    codex_home: Path, relative: PurePosixPath, max_bytes: int
) -> bytes:
    snapshot, failures = snapshot_isolated_rollouts(codex_home)
    if failures or relative not in snapshot or len(snapshot[relative]) > max_bytes:
        raise RuntimeError("E_ROLLOUT_SNAPSHOT_READ")
    return snapshot[relative]


def resolved_rollout_snapshot(
    source: Path | dict[PurePosixPath, bytes],
) -> tuple[dict[PurePosixPath, bytes], list[str]]:
    if isinstance(source, Path):
        return snapshot_isolated_rollouts(source)
    return dict(source), []


def rollout_tree_auth_evidence(
    rollout_source: Path | dict[PurePosixPath, bytes], auth_secrets: set[str]
) -> dict[str, object]:
    """Scan every bounded raw rollout for exact auth values without retaining text."""
    evidence: dict[str, object] = {
        "source": "all_isolated_rollout_raw_bytes",
        "scanned_file_count": 0,
        "scanned_total_bytes": 0,
        "auth_exact_value_leak_detected": False,
        "schema_failures": [],
    }
    failures = evidence["schema_failures"]
    assert isinstance(failures, list)
    snapshot, tree_failures = resolved_rollout_snapshot(rollout_source)
    if tree_failures:
        failures.extend(tree_failures)
        return evidence
    total = 0
    for relative, raw in sorted(snapshot.items()):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            failures.append("raw rollout auth scan could not securely read UTF-8 JSONL")
            return evidence
        total += len(raw)
        if total > MAX_ROLLOUT_TREE_TOTAL_BYTES:
            failures.append("raw rollout auth scan exceeded the aggregate byte limit")
            return evidence
        _redacted, semantic_leak = redact_jsonl_auth_values(text, auth_secrets)
        for line in split_jsonl_records(text):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                failures.append("raw rollout auth scan found malformed JSONL")
                return evidence
            if not isinstance(record, dict):
                failures.append("raw rollout auth scan found a non-object record")
                return evidence
        if semantic_leak:
            evidence["auth_exact_value_leak_detected"] = True
    evidence["scanned_file_count"] = len(snapshot)
    evidence["scanned_total_bytes"] = total
    return evidence


def rollout_identity_evidence(
    rollout_source: Path | dict[PurePosixPath, bytes],
    main_thread_id: str | None,
    fixture: Path,
    expected_model: str | None,
    expected_provider: str,
    expected_reasoning_effort: str | None,
    expected_cli_version: str,
) -> dict[str, object]:
    """Extract only CLI-owned identity fields from the isolated main rollout."""
    failures: list[str] = []
    evidence: dict[str, object] = {
        "source": "codex_rollout_session_meta_and_turn_context",
        "matching_rollout_count": 0,
        "session_meta_count": 0,
        "turn_context_count": 0,
        "observed_models": [],
        "observed_providers": [],
        "observed_reasoning_efforts": [],
        "observed_cli_versions": [],
        "observed_session_sources": [],
        "schema_failures": failures,
        "identity_record_sha256": None,
        "main_thread_id_sha256": (
            sha256_bytes(main_thread_id.encode())
            if isinstance(main_thread_id, str) and main_thread_id
            else None
        ),
    }
    if not isinstance(main_thread_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", main_thread_id
    ):
        failures.append("main thread id was unavailable or malformed for rollout binding")
        return evidence
    if not isinstance(expected_model, str) or not EXECUTION_ID_RE.fullmatch(
        expected_model
    ):
        failures.append("requested model was not a bounded safe identifier")
        return evidence
    if expected_provider != LOCKED_MODEL_PROVIDER:
        failures.append("requested provider was not the locked OpenAI provider")
        return evidence
    if not isinstance(expected_reasoning_effort, str) or not REASONING_EFFORT_RE.fullmatch(
        expected_reasoning_effort
    ):
        failures.append("requested reasoning effort was not a bounded safe identifier")
        return evidence
    if not CLI_VERSION_VALUE_RE.fullmatch(expected_cli_version):
        failures.append("probed CLI version was not a bounded safe identifier")
        return evidence

    rollout_snapshot, rollout_tree_failures = resolved_rollout_snapshot(
        rollout_source
    )
    rollout_files = sorted(rollout_snapshot)
    if rollout_tree_failures:
        failures.extend(rollout_tree_failures)
        return evidence
    candidates = [
        path
        for path in rollout_files
        if path.name.endswith(f"-{main_thread_id}.jsonl")
    ]
    evidence["matching_rollout_count"] = len(candidates)
    if len(candidates) != 1:
        failures.append("main thread did not map to exactly one isolated rollout file")
        return evidence

    try:
        raw = rollout_snapshot[candidates[0]]
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        failures.append("main rollout could not be read as bounded UTF-8 JSONL")
        return evidence

    session_ids: set[str] = set()
    providers: set[str] = set()
    cli_versions: set[str] = set()
    sources: set[str] = set()
    session_cwds: set[str] = set()
    models: set[str] = set()
    efforts: set[str] = set()
    turn_cwds: set[str] = set()
    turn_ids: set[str] = set()
    first_identity_event: str | None = None
    session_meta_count = 0
    turn_context_count = 0
    malformed_count = 0
    non_object_count = 0
    for line in split_jsonl_records(text):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_count += 1
            continue
        if not isinstance(record, dict):
            non_object_count += 1
            continue
        record_type = record.get("type")
        if record_type not in {"session_meta", "turn_context"}:
            continue
        if first_identity_event is None:
            first_identity_event = str(record_type)
        payload = record.get("payload")
        if not isinstance(payload, dict):
            failures.append(f"rollout {record_type} payload was not an object")
            continue
        if record_type == "session_meta":
            session_meta_count += 1
            session_id = payload.get("session_id")
            thread_id = payload.get("id")
            provider = payload.get("model_provider")
            cli_version = payload.get("cli_version")
            source = payload.get("source")
            cwd = payload.get("cwd")
            if not all(
                isinstance(value, str) and value
                for value in (
                    session_id,
                    thread_id,
                    provider,
                    cli_version,
                    source,
                    cwd,
                )
            ):
                failures.append("rollout session_meta omitted a required identity field")
                continue
            if session_id == main_thread_id and thread_id == main_thread_id:
                session_ids.add(main_thread_id)
            else:
                failures.append("rollout session ids did not match the exec thread id")
            if provider == expected_provider:
                providers.add(expected_provider)
            else:
                failures.append("rollout model provider did not match the requested provider")
            if cli_version == expected_cli_version:
                cli_versions.add(expected_cli_version)
            else:
                failures.append("rollout CLI version did not match the probed executable")
            if source == "exec":
                sources.add("exec")
            else:
                failures.append("rollout session source was not exec")
            normalized_cwd = normalized_absolute_path(cwd)
            if normalized_cwd is None:
                failures.append("rollout session_meta cwd was not a valid absolute path")
                continue
            session_cwds.add(normalized_cwd)
        else:
            turn_context_count += 1
            model = payload.get("model")
            effort = payload.get("effort")
            cwd = payload.get("cwd")
            turn_id = payload.get("turn_id")
            if not all(
                isinstance(value, str) and value
                for value in (model, effort, cwd, turn_id)
            ):
                failures.append("rollout turn_context omitted a required identity field")
                continue
            if isinstance(expected_model, str) and model == expected_model:
                models.add(expected_model)
            else:
                failures.append("rollout model did not match the explicitly requested model")
            if (
                isinstance(expected_reasoning_effort, str)
                and effort == expected_reasoning_effort
            ):
                efforts.add(expected_reasoning_effort)
            else:
                failures.append(
                    "rollout reasoning effort did not match the explicitly requested effort"
                )
            normalized_cwd = normalized_absolute_path(cwd)
            if normalized_cwd is None:
                failures.append("rollout turn_context cwd was not a valid absolute path")
                continue
            turn_cwds.add(normalized_cwd)
            if EXECUTION_ID_RE.fullmatch(str(turn_id)):
                turn_ids.add(str(turn_id))
            else:
                failures.append("rollout turn id was not a bounded safe identifier")

    evidence["session_meta_count"] = session_meta_count
    evidence["turn_context_count"] = turn_context_count
    evidence["observed_models"] = sorted(models)
    evidence["observed_providers"] = sorted(providers)
    evidence["observed_reasoning_efforts"] = sorted(efforts)
    evidence["observed_cli_versions"] = sorted(cli_versions)
    evidence["observed_session_sources"] = sorted(sources)
    if malformed_count:
        failures.append("main rollout contained malformed JSONL records")
    if non_object_count:
        failures.append("main rollout contained non-object JSON records")
    if first_identity_event != "session_meta":
        failures.append("main rollout identity did not begin with session_meta")
    if session_meta_count != 1:
        failures.append("main rollout did not contain exactly one session_meta")
    if turn_context_count != 1:
        failures.append("main rollout did not contain exactly one turn_context")
    if session_ids != {main_thread_id}:
        failures.append("main rollout session ids did not match the exec thread id")
    if sources != {"exec"}:
        failures.append("main rollout session source was not exec")
    expected_cwd = normalized_absolute_path(str(fixture.resolve()))
    if expected_cwd is None:
        failures.append("isolated fixture path could not be canonicalized")
    if session_cwds != {expected_cwd} or turn_cwds != {expected_cwd}:
        failures.append("main rollout cwd did not match the isolated fixture")
    identity_record = {
        "session_id_sha256": sha256_bytes(main_thread_id.encode()),
        "providers": sorted(providers),
        "cli_versions": sorted(cli_versions),
        "sources": sorted(sources),
        "models": sorted(models),
        "efforts": sorted(efforts),
        "turn_id_sha256": sorted(sha256_bytes(value.encode()) for value in turn_ids),
        "session_meta_count": session_meta_count,
        "turn_context_count": turn_context_count,
    }
    evidence["identity_record_sha256"] = sha256_bytes(
        json.dumps(
            identity_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    evidence["schema_failures"] = sorted(set(failures))
    return evidence


def redact_jsonl_auth_values(text: str, secrets: set[str]) -> tuple[str, bool]:
    """Redact exact auth values after JSON unescaping, then emit valid JSONL."""

    def redact_value(value: object) -> tuple[object, bool]:
        if isinstance(value, str):
            return redact_exact_auth_values(value, secrets)
        if isinstance(value, list):
            matched = False
            redacted_items: list[object] = []
            for item in value:
                redacted_item, item_matched = redact_value(item)
                redacted_items.append(redacted_item)
                matched = matched or item_matched
            return redacted_items, matched
        if isinstance(value, dict):
            matched = False
            redacted_mapping: dict[str, object] = {}
            for key, item in value.items():
                redacted_key, key_matched = redact_exact_auth_values(str(key), secrets)
                redacted_item, item_matched = redact_value(item)
                redacted_mapping[redacted_key] = redacted_item
                matched = matched or key_matched or item_matched
            return redacted_mapping, matched
        return value, False

    # First redact across the complete byte-decoded stream. This covers malformed
    # JSON that contains a literal newline inside a secret before JSONL framing.
    pre_redacted_text, matched = redact_exact_auth_values(text, secrets)
    output_lines: list[str] = []
    for line in split_jsonl_records(pre_redacted_text):
        if not line.strip():
            output_lines.append(line)
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            redacted_line, line_matched = redact_exact_auth_values(line, secrets)
            for secret in sorted(secrets, key=len, reverse=True):
                replacement = (
                    AUTH_REDACTION_MARKER
                    if secret not in AUTH_REDACTION_MARKER
                    else ""
                )
                replacement_json = json.dumps(replacement, ensure_ascii=False)[1:-1]
                for ensure_ascii in (False, True):
                    encoded = json.dumps(secret, ensure_ascii=ensure_ascii)[1:-1]
                    if encoded and encoded in redacted_line:
                        redacted_line = redacted_line.replace(encoded, replacement_json)
                        line_matched = True
            output_lines.append(INVALID_JSONL_REDACTION_PREFIX + redacted_line)
            matched = matched or line_matched
            continue
        redacted_value, line_matched = redact_value(value)
        output_lines.append(
            json.dumps(redacted_value, ensure_ascii=False, separators=(",", ":"))
        )
        matched = matched or line_matched
    suffix = "\n" if pre_redacted_text.endswith("\n") else ""
    return "\n".join(output_lines) + suffix, matched


def redact_local_paths(text: str, replacements: dict[str, str]) -> str:
    redacted = text
    for source, replacement in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if source:
            redacted = redacted.replace(source, replacement)
    return redacted


def build_local_path_replacements(
    entries: list[tuple[str, str]],
) -> dict[str, str]:
    """Map lexical and canonical absolute spellings to the same receipt token."""
    replacements: dict[str, str] = {}
    for source, replacement in entries:
        if not source:
            continue
        replacements[source] = replacement
        canonical = normalized_absolute_path(source)
        if canonical:
            replacements[canonical] = replacement
    return replacements


def decode_jwt_payload(token: object, label: str) -> dict[str, object]:
    if not isinstance(token, str) or token.count(".") != 2:
        raise RuntimeError(f"{label} must be a JWT for claim-consistency inspection")
    encoded = token.split(".", 2)[1]
    encoded += "=" * (-len(encoded) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot decode {label} identity claims") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} identity claims must be an object")
    return payload


def unverified_auth_account_claim(auth_data: object) -> str:
    """Return one internally consistent, explicitly unverified account claim."""
    if not isinstance(auth_data, dict) or not isinstance(auth_data.get("tokens"), dict):
        raise RuntimeError("credential claim inspection requires ChatGPT token auth")
    tokens = auth_data["tokens"]
    assert isinstance(tokens, dict)
    declared = tokens.get("account_id")
    if not isinstance(declared, str) or not declared:
        raise RuntimeError("auth tokens.account_id is missing")
    identities = [declared]
    for token_name in ("id_token", "access_token"):
        payload = decode_jwt_payload(tokens.get(token_name), f"tokens.{token_name}")
        auth_claim = payload.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            raise RuntimeError(f"tokens.{token_name} is missing the OpenAI auth claim")
        claimed = auth_claim.get("chatgpt_account_id")
        if not isinstance(claimed, str) or not claimed:
            raise RuntimeError(f"tokens.{token_name} is missing chatgpt_account_id")
        identities.append(claimed)
    if len(set(identities)) != 1:
        raise RuntimeError("auth account identity claims are inconsistent")
    return declared


def verify_credential_provenance(
    credential_class: str,
    eval_auth_data: object,
    primary_auth_path: Path,
) -> tuple[bool, str]:
    """Inspect claims, but never treat unsigned JWT payloads as trusted provenance."""
    if credential_class != "dedicated":
        return False, "declared_primary"
    primary_bytes = read_regular_nofollow(primary_auth_path.expanduser())
    primary_data = json.loads(primary_bytes)
    eval_identity = unverified_auth_account_claim(eval_auth_data)
    primary_identity = unverified_auth_account_claim(primary_data)
    if eval_identity == primary_identity:
        raise RuntimeError(
            "dedicated auth claims match the primary account; use a distinct eval account"
        )
    return False, "distinct_but_unverified_jwt_claims"


def installed_home_for_skills_root(installed_root: Path) -> Path:
    root = installed_root.expanduser().resolve()
    if root.name != "skills" or root.parent.name != ".agents":
        raise RuntimeError(
            "--installed-root must have the form <HOME>/.agents/skills so the "
            "validated and executed discovery roots are identical"
        )
    return root.parent.parent


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


def is_valid_worker_packet(prompt: str) -> bool:
    return worker_packet_fields(prompt) is not None


def embedded_exact_worker_packet(prompt: str) -> str | None:
    """Extract the single seven-line reviewer packet embedded in a main case."""
    lines = prompt.splitlines()
    starts = [index for index, line in enumerate(lines) if line == "AGENCY_WORKER: true"]
    if len(starts) != 1 or starts[0] + 7 > len(lines):
        return None
    packet = "\n".join(lines[starts[0] : starts[0] + 7])
    return packet if is_valid_worker_packet(packet) else None


def explicit_skill_slug_mentions(prompt: str) -> list[str]:
    mentions: list[str] = []
    for name in INSTALL_NAMES:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-])\${re.escape(name)}(?![A-Za-z0-9_-])"
        )
        if pattern.search(prompt):
            mentions.append(name)
    return mentions


def safe_relative_artifact(value: object, case_id: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"case {case_id} expected_file is not a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"case {case_id} expected_file escapes the fixture")
    return path


def isolated_case_paths(
    temp_root: Path, case_id: str
) -> tuple[Path, Path, Path, Path, Path]:
    if not CASE_ID_RE.fullmatch(case_id):
        raise RuntimeError(f"unsafe behavior case id: {case_id!r}")
    workspace_root = temp_root / "workspaces" / case_id
    private_state_root = temp_root / "private-case-state" / case_id
    fixture = workspace_root / "project"
    fixture_home = private_state_root / "home"
    isolated_codex_home = private_state_root / "codex"
    if paths_overlap(workspace_root, fixture_home) or paths_overlap(
        workspace_root, isolated_codex_home
    ):
        raise RuntimeError(
            f"private case state overlaps the project parent for {case_id}"
        )
    return (
        workspace_root,
        private_state_root,
        fixture,
        fixture_home,
        isolated_codex_home,
    )


def validate_runtime_case(case: object) -> dict[str, Any]:
    """Fail closed independently from the offline package validator."""
    if not isinstance(case, dict):
        raise RuntimeError("every behavior case must be an object")
    required = {"id", "prompt", "should_trigger", "mode", "collaboration", "activation"}
    if not required.issubset(case):
        raise RuntimeError(f"behavior case is missing required fields: {case!r}")
    case_id = case["id"]
    if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
        raise RuntimeError(f"unsafe behavior case id: {case_id!r}")
    if not isinstance(case["prompt"], str) or not case["prompt"].strip():
        raise RuntimeError(f"case {case_id} prompt must be a non-empty string")
    if type(case["should_trigger"]) is not bool:
        raise RuntimeError(f"case {case_id} should_trigger must be boolean")
    if case["mode"] not in ALLOWED_MODES:
        raise RuntimeError(f"case {case_id} has unsupported mode")
    if case["collaboration"] not in ALLOWED_COLLABORATION:
        raise RuntimeError(f"case {case_id} has unsupported collaboration")
    if case["activation"] not in ALLOWED_ACTIVATION:
        raise RuntimeError(f"case {case_id} has unsupported activation")
    expected_entrypoint = case.get("expected_entrypoint")
    if case.get("model_smoke") and expected_entrypoint is None:
        raise RuntimeError(f"case {case_id} model smoke needs expected_entrypoint")
    if expected_entrypoint is not None and expected_entrypoint not in ALLOWED_ENTRYPOINTS:
        raise RuntimeError(f"case {case_id} has unsupported expected_entrypoint")
    allowed_guard_bundle = case.get("allowed_guard_bundle")
    if allowed_guard_bundle is not None:
        if allowed_guard_bundle not in ALLOWED_GUARD_BUNDLES:
            raise RuntimeError(f"case {case_id} has unsupported allowed_guard_bundle")
        if not (
            case["activation"] == "worker"
            and case["should_trigger"] is False
            and case["collaboration"] == "none"
            and expected_entrypoint == "none"
            and is_valid_worker_packet(str(case["prompt"]))
        ):
            raise RuntimeError(
                f"case {case_id} guard bundle is only valid for a complete packet in a non-triggering worker case"
            )
        expected_guard_name = {
            "canonical": SKILL_NAME,
            "legacy": LEGACY_SKILL_NAME,
            "none": None,
        }[str(allowed_guard_bundle)]
        mentions = explicit_skill_slug_mentions(str(case["prompt"]))
        if expected_guard_name is None:
            if mentions:
                raise RuntimeError(
                    f"case {case_id} guard bundle none cannot explicitly invoke a Skill"
                )
        elif mentions != [expected_guard_name]:
            raise RuntimeError(
                f"case {case_id} guard bundle must uniquely match its explicit $slug"
            )
    exact_marker_counts = case.get("exact_marker_counts")
    if case.get("model_smoke") and not exact_marker_counts:
        raise RuntimeError(f"case {case_id} needs non-empty exact_marker_counts")
    if exact_marker_counts is not None and (
        not isinstance(exact_marker_counts, dict)
        or not exact_marker_counts
        or any(
        not isinstance(marker, str)
        or not marker
        or type(count) is not int
        or count < 0
        for marker, count in exact_marker_counts.items()
        )
    ):
        raise RuntimeError(f"case {case_id} has invalid exact_marker_counts")
    sandbox = case.get("sandbox", "read-only")
    if sandbox not in ALLOWED_SANDBOXES:
        raise RuntimeError(f"case {case_id} requests unsafe sandbox {sandbox!r}")
    if "model_smoke" in case and type(case["model_smoke"]) is not bool:
        raise RuntimeError(f"case {case_id} model_smoke must be boolean")
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
            raise RuntimeError(f"case {case_id} {key} must be boolean")
    review_evidence_tier = case.get("review_evidence_tier")
    if review_evidence_tier is not None and review_evidence_tier not in {"rc", "stable"}:
        raise RuntimeError(f"case {case_id} has unsupported review_evidence_tier")
    if case.get("allow_preload_announcement") and not (
        case["activation"] in {"explicit", "implicit"}
        and case["should_trigger"] is True
    ):
        raise RuntimeError(
            f"case {case_id} preload announcement is only valid for a positive main-session activation"
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
        raise RuntimeError(f"case {case_id} has an invalid expected_boot_receipt")
    for key in ("must_contain", "must_not_contain", "forbidden_file_texts"):
        if key in case and (
            not isinstance(case[key], list)
            or any(not isinstance(item, str) or not item for item in case[key])
        ):
            raise RuntimeError(f"case {case_id} {key} must contain non-empty strings")
    if "exact_final" in case and (
        not isinstance(case["exact_final"], str) or not case["exact_final"]
    ):
        raise RuntimeError(f"case {case_id} exact_final must be a non-empty string")
    if case.get("require_tool_event") and case.get("require_no_tool_events"):
        raise RuntimeError(f"case {case_id} cannot both require and forbid tool events")
    if case.get("require_collab_spawn") and not (
        case.get("model_smoke")
        and case["should_trigger"] is True
        and case["collaboration"] in {"native_subagents", "native_subagents_optional"}
    ):
        raise RuntimeError(
            f"case {case_id} collaboration spawn requires a positive native-subagent model smoke"
        )
    if case.get("require_collab_completion") and not (
        case.get("model_smoke")
        and case["should_trigger"] is True
        and case["collaboration"] in {"native_subagents", "native_subagents_optional"}
        and case.get("sandbox") == "workspace-write"
        and not case.get("require_collab_spawn")
        and not case.get("require_collab_event")
    ):
        raise RuntimeError(
            f"case {case_id} collaboration completion requires one positive workspace-write native-subagent smoke"
        )
    if (
        case.get("require_collab_event") or case.get("require_collab_completion")
    ) and not isinstance(expected_boot_receipt, str):
        raise RuntimeError(
            f"case {case_id} collaboration evidence requires an exact boot receipt"
        )
    has_file = "expected_file" in case
    has_text = "expected_text" in case
    if has_file != has_text:
        raise RuntimeError(f"case {case_id} must pair expected_file and expected_text")
    if has_file:
        safe_relative_artifact(case["expected_file"], case_id)
        if not isinstance(case["expected_text"], str) or not case["expected_text"]:
            raise RuntimeError(f"case {case_id} expected_text must be non-empty")
        if "expected_file_content" in case and (
            not isinstance(case["expected_file_content"], str)
            or not case["expected_file_content"]
        ):
            raise RuntimeError(f"case {case_id} expected_file_content must be non-empty")
        if "review_evidence_marker" in case and (
            not isinstance(case["review_evidence_marker"], str)
            or not case["review_evidence_marker"]
        ):
            raise RuntimeError(f"case {case_id} review_evidence_marker must be non-empty")
        if case.get("require_collab_completion") and not isinstance(
            case.get("expected_file_content"), str
        ):
            raise RuntimeError(
                f"case {case_id} collaboration completion needs exact artifact content"
            )
    elif (
        "expected_file_content" in case
        or "forbidden_file_texts" in case
        or "review_evidence_marker" in case
    ):
        raise RuntimeError(f"case {case_id} file assertions need expected_file")
    if case["activation"] == "worker" and not is_valid_worker_packet(str(case["prompt"])):
        raise RuntimeError(f"case {case_id} worker activation needs a complete first-line packet")
    if case.get("require_collab_event") and "review_evidence_marker" not in case:
        raise RuntimeError(f"case {case_id} cold review needs an undisclosed evidence marker")
    if case.get("require_collab_event") or case.get("require_collab_completion"):
        embedded_packet = embedded_exact_worker_packet(str(case["prompt"]))
        if embedded_packet is None:
            raise RuntimeError(
                f"case {case_id} collaboration prompt needs one exact reviewer packet"
            )
        if str(case["expected_text"]) in embedded_packet:
            raise RuntimeError(
                f"case {case_id} reviewer packet must not disclose expected artifact text"
            )
        marker = case.get("review_evidence_marker")
        if isinstance(marker, str) and marker in embedded_packet:
            raise RuntimeError(
                f"case {case_id} reviewer packet must not disclose review marker"
            )
        if case.get("require_collab_event") and embedded_packet != expected_strict_worker_packet(
            str(case["expected_file"])
        ):
            raise RuntimeError(
                f"case {case_id} strict reviewer packet must match the canonical contract"
            )
    if case.get("require_collab_event") and review_evidence_tier is None:
        raise RuntimeError(f"case {case_id} collaboration review needs review_evidence_tier")
    if review_evidence_tier is not None and not case.get("require_collab_event"):
        raise RuntimeError(
            f"case {case_id} review_evidence_tier requires a collaboration event"
        )
    if case.get("require_context_isolation") and not case.get("require_collab_event"):
        raise RuntimeError(
            f"case {case_id} context isolation requires a collaboration event"
        )
    if case.get("require_context_isolation") and review_evidence_tier != "stable":
        raise RuntimeError(
            f"case {case_id} context isolation is a stable-tier review requirement"
        )
    return case


def canonical_case_fingerprint(case: dict[str, object]) -> str:
    encoded = json.dumps(
        case,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def validate_smoke_suite(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases_by_id = {str(case["id"]): case for case in cases}
    reviewed_ids = set(REQUIRED_BEHAVIOR_CASE_SHA256)
    if set(cases_by_id) != reviewed_ids:
        missing = sorted(reviewed_ids - set(cases_by_id))
        unexpected = sorted(set(cases_by_id) - reviewed_ids)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unexpected:
            details.append(f"unexpected={','.join(unexpected)}")
        raise RuntimeError(
            "behavior suite must be exactly the 25 reviewed cases: "
            + "; ".join(details)
        )
    for case_id, expected_fingerprint in REQUIRED_BEHAVIOR_CASE_SHA256.items():
        actual_fingerprint = canonical_case_fingerprint(cases_by_id[case_id])
        if actual_fingerprint != expected_fingerprint:
            raise RuntimeError(
                f"behavior case {case_id} full semantic contract drifted"
            )

    smoke = {str(case["id"]): case for case in cases if case.get("model_smoke")}
    required_ids = set(REQUIRED_SMOKE_CONTRACT)
    if set(smoke) != required_ids:
        missing = sorted(required_ids - set(smoke))
        unexpected = sorted(set(smoke) - required_ids)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unexpected:
            details.append(f"unexpected={','.join(unexpected)}")
        raise RuntimeError(
            "model-smoke suite must be exactly the 20 reviewed cases: "
            + "; ".join(details)
        )
    for case_id, expected in REQUIRED_SMOKE_CONTRACT.items():
        case = smoke[case_id]
        for key, value in expected.items():
            actual = case.get(key, "read-only" if key == "sandbox" else None)
            if actual != value:
                raise RuntimeError(
                    f"model-smoke case {case_id} drifted: {key}={actual!r}, expected {value!r}"
                )
    write_case = smoke["explicit-write-execute"]
    marker = str(write_case.get("review_evidence_marker", ""))
    expected_content = str(write_case.get("expected_file_content", ""))
    if not marker or marker not in expected_content:
        raise RuntimeError("write smoke review marker must exist in exact expected artifact")
    if marker.count("{runtime_nonce}") != 1:
        raise RuntimeError("write smoke review marker must contain one runtime nonce slot")
    if re.search(r"\[readback-[0-9a-f]{16,}\]", marker):
        raise RuntimeError("write smoke review marker must not embed a reusable static nonce")
    if marker in str(write_case["prompt"]):
        raise RuntimeError("write smoke review marker must not be disclosed in the main prompt")
    for case_id, case in smoke.items():
        expected_entrypoint = str(case["expected_entrypoint"])
        counts = case["exact_marker_counts"]
        assert isinstance(counts, dict)
        expected_counts = {
            "canonical": {"COS_BOOT_RECEIPT": 1, "入口：canonical": 1, "入口：legacy": 0},
            "legacy": {"COS_BOOT_RECEIPT": 1, "入口：canonical": 0, "入口：legacy": 1},
            "none": {"COS_BOOT_RECEIPT": 0, "入口：canonical": 0, "入口：legacy": 0},
        }[expected_entrypoint]
        for marker_name, expected_count in expected_counts.items():
            if counts.get(marker_name) != expected_count:
                raise RuntimeError(
                    f"model-smoke case {case_id} weakens entrypoint count for {marker_name}"
                )
    return [case for case in cases if case.get("model_smoke")]


def structured_failure_text(event: dict[str, object]) -> str:
    values: list[str] = []
    for key in ("message", "error", "reason"):
        value = event.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for nested_key in ("message", "code", "type"):
                nested = value.get(nested_key)
                if isinstance(nested, str):
                    values.append(nested)
    detail = " | ".join(values)[:1000]
    return f"{event.get('type', 'unknown')}: {detail}".rstrip()


def structured_execution_identity(
    event: dict[str, object],
    main_thread_id: str | None,
) -> tuple[list[str], list[str]]:
    """Read identity only from CLI-owned structured lifecycle fields."""
    if event.get("type") not in {
        "thread.started",
        "turn.started",
        "session.configured",
        "execution.configured",
    }:
        return [], []
    containers = [event]
    for key in ("config", "configuration", "metadata"):
        value = event.get(key)
        if isinstance(value, dict):
            containers.append(value)
    attributed_thread_ids = {
        str(container["thread_id"])
        for container in containers
        if isinstance(container.get("thread_id"), str)
        and container.get("thread_id")
    }
    if main_thread_id is None or attributed_thread_ids != {main_thread_id}:
        return [], []
    models: list[str] = []
    providers: list[str] = []
    for container in containers:
        model = container.get("model")
        provider = container.get("model_provider", container.get("provider"))
        if isinstance(model, str) and EXECUTION_ID_RE.fullmatch(model):
            models.append(model)
        if isinstance(provider, str) and EXECUTION_ID_RE.fullmatch(provider):
            providers.append(provider)
    return models, providers


def execution_identity_failures(
    requested_model: str | None,
    observed_models: list[str],
    observed_providers: list[str],
    requested_reasoning_effort: str | None = None,
    observed_reasoning_efforts: list[str] | None = None,
    expected_cli_version: str | None = None,
    observed_cli_versions: list[str] | None = None,
    evidence_schema_failures: list[str] | None = None,
) -> list[str]:
    failures = [
        f"rollout identity evidence failed schema validation: {failure}"
        for failure in (evidence_schema_failures or [])
    ]
    if requested_model is not None and observed_models != [requested_model]:
        failures.append(
            "structured lifecycle did not expose the unique requested model "
            f"{requested_model!r} on the main thread"
        )
    if observed_providers != [LOCKED_MODEL_PROVIDER]:
        failures.append(
            "structured lifecycle did not expose the unique requested provider "
            f"{LOCKED_MODEL_PROVIDER!r} on the main thread"
        )
    if (
        requested_reasoning_effort is not None
        and (observed_reasoning_efforts or []) != [requested_reasoning_effort]
    ):
        failures.append(
            "structured rollout did not expose the unique requested reasoning effort "
            f"{requested_reasoning_effort!r} on the main thread"
        )
    if (
        expected_cli_version is not None
        and (observed_cli_versions or []) != [expected_cli_version]
    ):
        failures.append(
            "structured rollout did not bind the main thread to the probed Codex CLI version"
        )
    return failures


def is_safe_readonly_skill_command(command_text: str, expected_path: str) -> bool:
    """Recognize one tool attempt that only reads the expected complete SKILL.md."""
    if not command_text:
        return False
    try:
        outer = shlex.split(command_text)
    except ValueError:
        return False
    allowed_shells = {
        "sh",
        "bash",
        "zsh",
        "/bin/sh",
        "/bin/bash",
        "/bin/zsh",
        "/usr/bin/sh",
        "/usr/bin/bash",
        "/usr/bin/zsh",
    }
    if (
        len(outer) == 3
        and outer[0] in allowed_shells
        and outer[1] in {"-c", "-lc"}
    ):
        inner_text = outer[2]
    else:
        inner_text = command_text
    path_variants = {expected_path}
    canonical_expected_path = normalized_absolute_path(expected_path)
    if canonical_expected_path:
        path_variants.add(canonical_expected_path)
    sanitized_inner_text = inner_text
    for path_variant in sorted(path_variants, key=len, reverse=True):
        sanitized_inner_text = sanitized_inner_text.replace(
            path_variant, "__EXPECTED_SKILL__"
        )
    if re.search(
        r"(?:\|\||(?<!&)&(?!&)|[;|<>`]|\$\(|\r|\n)",
        sanitized_inner_text,
    ):
        return False
    segments = re.split(r"\s*&&\s*", inner_text)
    if not segments or len(segments) > 8 or any(not segment for segment in segments):
        return False
    if sanitized_inner_text.count("__EXPECTED_SKILL__") != len(segments):
        return False
    parsed_segments: list[list[str]] = []
    try:
        parsed_segments = [shlex.split(segment) for segment in segments]
    except ValueError:
        return False
    if len(parsed_segments) == 1:
        tokens = parsed_segments[0]
        executable = tokens[0] if tokens else ""
        if executable in {"cat", "/bin/cat", "/usr/bin/cat"}:
            return (
                len(tokens) == 2
                and normalized_absolute_path(tokens[1])
                == normalized_absolute_path(expected_path)
            )
    expected_start = 1
    for segment_index, tokens in enumerate(parsed_segments):
        executable = tokens[0] if tokens else ""
        if (
            executable not in {"sed", "/bin/sed", "/usr/bin/sed"}
            or len(tokens) != 4
            or tokens[1] != "-n"
            or normalized_absolute_path(tokens[3])
            != normalized_absolute_path(expected_path)
        ):
            return False
        match = re.fullmatch(r"([1-9][0-9]*),([1-9][0-9]*|\$)p", tokens[2])
        if match is None or int(match.group(1)) != expected_start:
            return False
        if match.group(2) == "$":
            return segment_index == len(parsed_segments) - 1
        end = int(match.group(2))
        if end < expected_start or end > 100_000:
            return False
        expected_start = end + 1
    return True


def single_readonly_skill_target(command_text: str) -> str | None:
    """Return the sole target of one simple read command, if unambiguous."""
    if not command_text:
        return None
    try:
        outer = shlex.split(command_text)
        if (
            len(outer) == 3
            and outer[0]
            in {
                "sh",
                "bash",
                "zsh",
                "/bin/sh",
                "/bin/bash",
                "/bin/zsh",
                "/usr/bin/sh",
                "/usr/bin/bash",
                "/usr/bin/zsh",
            }
            and outer[1] in {"-c", "-lc"}
        ):
            tokens = shlex.split(outer[2])
        else:
            tokens = outer
    except ValueError:
        return None
    executable = tokens[0] if tokens else ""
    if executable in {"cat", "/bin/cat", "/usr/bin/cat"} and len(tokens) == 2:
        return tokens[1]
    if (
        executable in {"sed", "/bin/sed", "/usr/bin/sed"}
        and len(tokens) == 4
        and tokens[1] == "-n"
        and re.fullmatch(r"[1-9][0-9]*,([1-9][0-9]*|\$)p", tokens[2])
    ):
        return tokens[3]
    return None


def tool_input_surface(item: dict[str, object]) -> str:
    """Serialize only tool inputs, never command output or tool results."""
    keys_by_type = {
        "command_execution": ("command",),
        "file_change": ("changes",),
        "mcp_tool_call": ("server", "tool", "arguments", "input"),
        "web_search": ("query",),
        "computer_use": ("action", "input"),
    }
    keys = keys_by_type.get(str(item.get("type")), ())
    inputs = {key: item[key] for key in keys if key in item}
    if item.get("type") == "command_execution" and isinstance(
        item.get("command"), str
    ):
        command = str(item["command"])
        try:
            outer = shlex.split(command)
            if (
                len(outer) == 3
                and outer[0]
                in {
                    "sh",
                    "bash",
                    "zsh",
                    "/bin/sh",
                    "/bin/bash",
                    "/bin/zsh",
                    "/usr/bin/sh",
                    "/usr/bin/bash",
                    "/usr/bin/zsh",
                }
                and outer[1] in {"-c", "-lc"}
            ):
                normalized_tokens = shlex.split(outer[2])
            else:
                normalized_tokens = outer
            inputs["normalized_command_tokens"] = normalized_tokens
        except ValueError:
            inputs["normalized_command_parse_failed"] = True
    return json.dumps(inputs, ensure_ascii=False, sort_keys=True)


def skill_touch_names(
    input_surface: str, expected_skill_paths: dict[str, str]
) -> set[str]:
    touched = {
        name
        for name, expected_path in expected_skill_paths.items()
        if (
            expected_path in input_surface
            or f"/{name}/SKILL.md" in input_surface
            or expected_path.rsplit("/", 1)[0] in input_surface
        )
    }
    lowered = input_surface.lower()
    if not touched and ".agents/skills" in lowered and "skill.md" in lowered:
        # A wildcard or variable-based access cannot prove a single guarded bundle.
        touched.update(expected_skill_paths)
    return touched


def classify_external_failure(
    top_level_failures: list[str], stderr_text: str
) -> str | None:
    evidence = "\n".join([*top_level_failures, stderr_text]).lower()
    if "you've hit your usage limit" in evidence and (
        "chatgpt.com/codex/settings/usage" in evidence
        or "purchase more credits" in evidence
    ):
        return "external_usage_limit"
    if "model is not supported when using codex with a chatgpt account" in evidence:
        return "external_model_unavailable"
    if "selected model is at capacity" in evidence:
        return "external_model_capacity"
    if "upgrade codex" in evidence or "newer version of codex" in evidence:
        return "external_client_incompatible"
    return None


def partition_top_level_failures(
    top_level_failures: list[str],
    terminal_events: list[str],
    returncode: int,
    timed_out: bool,
    top_level_failure_event_indexes: list[int] | None = None,
    terminal_event_indexes: list[int] | None = None,
) -> tuple[list[str], list[str]]:
    """Downgrade only an allowlisted transport retry after a clean completed turn."""
    if (
        timed_out
        or returncode != 0
        or terminal_events != ["turn.completed"]
        or len(terminal_event_indexes or []) != 1
        or len(top_level_failure_event_indexes or []) != len(top_level_failures)
    ):
        return [], list(top_level_failures)
    terminal_index = int((terminal_event_indexes or [])[0])
    recoverable: list[str] = []
    fatal: list[str] = []
    for failure, failure_index in zip(
        top_level_failures, top_level_failure_event_indexes or []
    ):
        if failure_index < terminal_index and any(
            pattern.fullmatch(failure)
            for pattern in RECOVERABLE_TRANSPORT_FAILURE_PATTERNS
        ):
            recoverable.append(failure)
        else:
            fatal.append(failure)
    return recoverable, fatal


def event_surface(
    events_text: str,
    final_text: str,
    expected_skill_texts: dict[str, str] | None = None,
    expected_skill_paths: dict[str, str] | None = None,
) -> dict[str, object]:
    messages: list[str] = []
    message_events: list[dict[str, object]] = []
    message_contract_attempts: list[dict[str, object]] = []
    tool_item_ids: set[str] = set()
    tool_attempt_ids: set[str] = set()
    tool_attempt_order: list[str] = []
    collab_attempt_ids: set[str] = set()
    collab_completed_ids: set[str] = set()
    spawns: dict[str, dict[str, object]] = {}
    waits: dict[str, dict[str, object]] = {}
    successful_tool_event_indexes: list[int] = []
    action_event_indexes: list[int] = []
    last_file_change_event_index = -1
    top_level_failures: list[str] = []
    top_level_failure_event_indexes: list[int] = []
    observed_models: set[str] = set()
    observed_providers: set[str] = set()
    terminal_events: list[str] = []
    terminal_event_indexes: list[int] = []
    post_terminal_event_count = 0
    invalid_json_line_count = 0
    non_object_json_record_count = 0
    collab_schema_failures: list[str] = []
    tool_schema_failures: list[str] = []
    tool_input_fingerprints: dict[str, str] = {}
    tool_lifecycle_states: dict[str, list[str]] = {}
    skills_context_budget_overflow_count = 0
    main_thread_id: str | None = None
    skill_load_events_by_name: dict[str, list[int]] = {
        name: [] for name in INSTALL_NAMES
    }
    skill_load_attempts_by_name: dict[str, list[int]] = {
        name: [] for name in INSTALL_NAMES
    }
    skill_preload_actions_by_name: dict[str, list[int]] = {
        name: [] for name in INSTALL_NAMES
    }
    skill_touch_attempt_ids_by_name: dict[str, set[str]] = {
        name: set() for name in INSTALL_NAMES
    }
    skill_touch_first_event_indexes_by_name: dict[str, dict[str, int]] = {
        name: {} for name in INSTALL_NAMES
    }
    skill_location_failure_attempt_ids_by_name: dict[str, set[str]] = {
        name: set() for name in INSTALL_NAMES
    }
    skill_location_failure_action_indexes_by_name: dict[str, set[int]] = {
        name: set() for name in INSTALL_NAMES
    }
    valid_skill_read_attempt_ids_by_name: dict[str, set[str]] = {
        name: set() for name in INSTALL_NAMES
    }
    event_lines = split_jsonl_records(events_text)
    for index, line in enumerate(event_lines):
        if terminal_event_indexes and line.strip():
            post_terminal_event_count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                invalid_json_line_count += 1
            continue
        if not isinstance(event, dict):
            non_object_json_record_count += 1
            continue
        event_type = event.get("type")
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            if main_thread_id is None:
                main_thread_id = str(event["thread_id"])
            elif main_thread_id != event["thread_id"]:
                collab_schema_failures.append("multiple main thread ids were observed")
        if event_type in {"turn.completed", "turn.failed"}:
            terminal_events.append(str(event_type))
            terminal_event_indexes.append(index)
        models, providers = structured_execution_identity(event, main_thread_id)
        observed_models.update(models)
        observed_providers.update(providers)
        if event_type in {"error", "turn.failed"}:
            top_level_failures.append(structured_failure_text(event))
            top_level_failure_event_indexes.append(index)
        if event_type not in {
            "item.started",
            "item.completed",
            "item.failed",
            "item.cancelled",
            "item.updated",
        }:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if (
            event_type == "item.completed"
            and item_type == "error"
            and isinstance(item.get("message"), str)
            and str(item["message"]).startswith("Exceeded skills context budget")
        ):
            skills_context_budget_overflow_count += 1
        if item_type == "collab_tool_call":
            if not isinstance(item.get("id"), str) or not item.get("id"):
                collab_schema_failures.append(
                    "collaboration lifecycle item lacked a stable id"
                )
            attempt_id = str(
                item.get("id")
                or "|".join(
                    (
                        str(item.get("tool", "")),
                        json.dumps(item.get("receiver_thread_ids", []), sort_keys=True),
                        str(item.get("prompt", "")),
                    )
                )
            )
            if attempt_id not in collab_attempt_ids:
                collab_attempt_ids.add(attempt_id)
                action_event_indexes.append(index)
            if event_type == "item.completed" and item.get("status") == "completed":
                collab_completed_ids.add(attempt_id)
        if item_type in TOOL_ITEM_TYPES:
            action_event_indexes.append(index)
            if not isinstance(item.get("id"), str) or not item.get("id"):
                tool_schema_failures.append("tool lifecycle item lacked a stable id")
            tool_attempt_id = str(item.get("id") or f"event-{index}")
            if tool_attempt_id not in tool_attempt_ids:
                tool_attempt_order.append(tool_attempt_id)
            tool_attempt_ids.add(tool_attempt_id)
            input_surface = tool_input_surface(item)
            if item_type == "command_execution":
                input_fingerprint = sha256_bytes(
                    f"{item_type}\0{input_surface}".encode()
                )
                previous_fingerprint = tool_input_fingerprints.setdefault(
                    tool_attempt_id, input_fingerprint
                )
                if previous_fingerprint != input_fingerprint:
                    tool_schema_failures.append(
                        "stable tool id was reused with different command input"
                    )
                states = tool_lifecycle_states.setdefault(tool_attempt_id, [])
                if event_type == "item.started" and states:
                    tool_schema_failures.append(
                        "command tool id had a duplicate or out-of-order start"
                    )
                if event_type == "item.completed" and any(
                    state in {"item.completed", "item.failed", "item.cancelled"}
                    for state in states
                ):
                    tool_schema_failures.append(
                        "command tool id had multiple terminal lifecycle events"
                    )
                if event_type in {"item.failed", "item.cancelled"} and any(
                    state in {"item.completed", "item.failed", "item.cancelled"}
                    for state in states
                ):
                    tool_schema_failures.append(
                        "command tool id had multiple terminal lifecycle events"
                    )
                states.append(str(event_type))
            command_text = (
                str(item["command"])
                if item_type == "command_execution"
                and isinstance(item.get("command"), str)
                else ""
            )
            expected_paths = {
                name: str(path)
                for name, path in (expected_skill_paths or {}).items()
                if isinstance(path, str)
            }
            for name in skill_touch_names(input_surface, expected_paths):
                skill_touch_attempt_ids_by_name[name].add(tool_attempt_id)
                skill_touch_first_event_indexes_by_name[name].setdefault(
                    tool_attempt_id, index
                )
            if (
                item_type == "command_execution"
                and event_type in {"item.completed", "item.failed", "item.cancelled"}
                and (
                    event_type != "item.completed"
                    or item.get("exit_code") not in {None, 0}
                    or item.get("status") in {"failed", "cancelled"}
                )
            ):
                failed_target = single_readonly_skill_target(command_text)
                for name, expected_path in expected_paths.items():
                    if (
                        failed_target is not None
                        and failed_target != expected_path
                        and failed_target.endswith(f"/{name}/SKILL.md")
                    ):
                        skill_location_failure_attempt_ids_by_name[name].add(
                            tool_attempt_id
                        )
                        first_index = skill_touch_first_event_indexes_by_name[
                            name
                        ].get(tool_attempt_id, index)
                        skill_location_failure_action_indexes_by_name[name].update(
                            {first_index, index}
                        )
            valid_read_names = {
                name
                for name in INSTALL_NAMES
                if isinstance((expected_skill_paths or {}).get(name), str)
                and is_safe_readonly_skill_command(
                    command_text, str((expected_skill_paths or {})[name])
                )
            }
            for name in valid_read_names:
                skill_preload_actions_by_name[name].append(index)
            if event_type == "item.completed":
                for name in valid_read_names:
                    skill_load_attempts_by_name[name].append(index)
                status = item.get("status")
                exit_code = item.get("exit_code")
                command_ok = item_type != "command_execution" or exit_code in {None, 0}
                status_ok = status not in {"failed", "cancelled"}
                if command_ok and status_ok:
                    tool_item_ids.add(str(item.get("id", f"event-{index}")))
                    successful_tool_event_indexes.append(index)
                    if item_type == "file_change":
                        last_file_change_event_index = index
                    if isinstance(item.get("aggregated_output"), str):
                        output = str(item["aggregated_output"])
                        for name in valid_read_names:
                            expected_text = (expected_skill_texts or {}).get(name)
                            if (
                                expected_text is not None
                                and output.rstrip("\n") == expected_text.rstrip("\n")
                            ):
                                skill_load_events_by_name[name].append(index)
                                valid_skill_read_attempt_ids_by_name[name].add(
                                    tool_attempt_id
                                )
        if event_type != "item.completed":
            continue
        if item_type in ASSISTANT_ITEM_TYPES:
            visible_keys = [
                key for key in ("text", "content", "message") if key in item
            ]
            value = (
                item.get(visible_keys[0]) if len(visible_keys) == 1 else None
            )
            valid_value = (
                value
                if isinstance(value, str) and bool(value)
                else None
            )
            message_contract_attempts.append(
                {"event_index": index, "text": valid_value}
            )
            if valid_value is not None:
                messages.append(valid_value)
                message_events.append(
                    {"event_index": index, "text": valid_value}
                )
        if item_type != "collab_tool_call" or item.get("status") != "completed":
            continue
        sender_thread_id = item.get("sender_thread_id")
        if (
            main_thread_id is None
            or not isinstance(sender_thread_id, str)
            or sender_thread_id != main_thread_id
        ):
            collab_schema_failures.append(
                "completed collaboration item was not attributable to the main thread"
            )
            continue
        receiver_ids = item.get("receiver_thread_ids")
        if not isinstance(receiver_ids, list):
            receiver_ids = []
        if item.get("tool") == "spawn_agent":
            for receiver_id in receiver_ids:
                if isinstance(receiver_id, str) and receiver_id:
                    spawns[receiver_id] = {
                        "spawn_event_index": index,
                        "prompt": item.get("prompt")
                        if isinstance(item.get("prompt"), str)
                        else "",
                        "sender_thread_id": sender_thread_id,
                        "context_isolation_requested": (
                            item.get("fork_turns") == "none"
                            or item.get("context_mode") in {"none", "isolated"}
                        ),
                        # A requested mode is not authoritative proof that the
                        # child received no inherited context.
                        "context_isolation_verified": False,
                        # The current documented JSONL surface does not expose
                        # receiver-owned child tool events. Do not infer a file
                        # read from reviewer prose or a hidden marker alone.
                        "reviewer_owned_file_read_verified": False,
                    }
        if item.get("tool") == "wait":
            states = item.get("agents_states")
            if not isinstance(states, dict):
                continue
            for receiver_id, state in states.items():
                if not isinstance(receiver_id, str) or not isinstance(state, dict):
                    continue
                message = state.get("message")
                if (
                    state.get("status") == "completed"
                    and isinstance(message, str)
                    and message.strip()
                ):
                    waits[receiver_id] = {
                        "wait_event_index": index,
                        "message": message,
                        "sender_thread_id": sender_thread_id,
                    }

    completed_reviews = {
        receiver_id: {**spawns[receiver_id], **waits[receiver_id]}
        for receiver_id in sorted(set(spawns) & set(waits))
        if waits[receiver_id]["wait_event_index"]
        > spawns[receiver_id]["spawn_event_index"]
        and waits[receiver_id]["sender_thread_id"]
        == spawns[receiver_id]["sender_thread_id"]
    }
    if final_text and final_text not in messages:
        messages.append(final_text)
        message_events.append({"event_index": len(event_lines), "text": final_text})
    return {
        "surface": "\n".join(messages),
        "assistant_messages": messages,
        "assistant_message_events": message_events,
        "assistant_message_contract_attempts": message_contract_attempts,
        "skill_load_events_by_name": skill_load_events_by_name,
        "skill_load_attempts_by_name": skill_load_attempts_by_name,
        "skill_preload_actions_by_name": skill_preload_actions_by_name,
        "skill_touch_attempt_ids_by_name": {
            name: sorted(values)
            for name, values in skill_touch_attempt_ids_by_name.items()
        },
        "skill_touch_first_event_indexes_by_name": {
            name: sorted(values.values())
            for name, values in skill_touch_first_event_indexes_by_name.items()
        },
        "valid_skill_read_attempt_ids_by_name": {
            name: sorted(values)
            for name, values in valid_skill_read_attempt_ids_by_name.items()
        },
        "skill_location_failure_attempt_ids_by_name": {
            name: sorted(values)
            for name, values in skill_location_failure_attempt_ids_by_name.items()
        },
        "skill_location_failure_action_indexes_by_name": {
            name: sorted(values)
            for name, values in skill_location_failure_action_indexes_by_name.items()
        },
        "tool_events": len(tool_item_ids),
        "tool_attempts": len(tool_attempt_ids),
        "tool_attempt_order": tool_attempt_order,
        "collab_tool_attempts": len(collab_attempt_ids),
        "collab_tool_events": len(collab_completed_ids),
        "collab_tool_events_completed": len(collab_completed_ids),
        "spawn_completed": spawns,
        "reviews_completed": completed_reviews,
        "successful_tool_event_indexes": successful_tool_event_indexes,
        "action_event_indexes": action_event_indexes,
        "last_file_change_event_index": last_file_change_event_index,
        "top_level_failures": top_level_failures,
        "top_level_failure_event_indexes": top_level_failure_event_indexes,
        "observed_models": sorted(observed_models),
        "observed_providers": sorted(observed_providers),
        "terminal_events": terminal_events,
        "terminal_event_indexes": terminal_event_indexes,
        "post_terminal_event_count": post_terminal_event_count,
        "invalid_json_line_count": invalid_json_line_count,
        "non_object_json_record_count": non_object_json_record_count,
        "collab_schema_failures": sorted(set(collab_schema_failures)),
        "tool_schema_failures": sorted(set(tool_schema_failures)),
        "main_thread_id_observed": main_thread_id,
        "skills_context_budget_overflow_count": (
            skills_context_budget_overflow_count
        ),
    }


def exec_json_main_message_contract_valid(
    attempts: list[dict[str, object]],
    expected_final_text: str,
    expected_boot_receipt: str,
) -> bool:
    """Bind collaboration prose on the public exec JSON surface."""
    normalized: list[tuple[int, datetime | None, str | None]] = []
    for attempt in attempts:
        index = attempt.get("event_index")
        text = attempt.get("text")
        if isinstance(index, bool) or not isinstance(index, int):
            return False
        normalized.append(
            (index, None, str(text) if isinstance(text, str) else None)
        )
    return main_assistant_message_contract_valid(
        normalized,
        expected_final_text,
        expected_boot_receipt,
        require_final=True,
    )


def expected_skill_name(case: dict[str, Any]) -> str | None:
    return {
        "canonical": SKILL_NAME,
        "legacy": LEGACY_SKILL_NAME,
        "none": None,
    }.get(str(case.get("expected_entrypoint")))


def allowed_guard_skill_name(case: dict[str, Any]) -> str | None:
    return {
        "canonical": SKILL_NAME,
        "legacy": LEGACY_SKILL_NAME,
        "none": None,
    }.get(str(case.get("allowed_guard_bundle", "none")))


def preload_text_uses_only_vocabulary(
    text: str, vocabulary: tuple[str, ...]
) -> bool:
    residual = text.lower()
    for identity in (
        SKILL_NAME.lower(),
        LEGACY_SKILL_NAME.lower(),
        "chief of staff",
        "幕僚长",
    ):
        residual = residual.replace(identity, "")
    for token in sorted(vocabulary, key=len, reverse=True):
        residual = residual.replace(token, "")
    residual = re.sub(r"[\s$`'\"，,、。.！!?：:（）()\[\]{}]+", "", residual)
    return residual == ""


def normalize_announcement_grounding_text(text: str) -> str:
    return re.sub(
        r"[\s$`'\"“”‘’，,、。.！!?：:；;（）()\[\]{}<>《》/\\|→·._-]+",
        "",
        text.lower(),
    )


def preload_announcement_is_prompt_grounded(text: str, prompt: str) -> bool:
    residual = text.lower()
    for identity in (
        SKILL_NAME.lower(),
        LEGACY_SKILL_NAME.lower(),
        "chief of staff",
        "幕僚长",
    ):
        residual = residual.replace(identity, "")
    for token in sorted(
        PRELOAD_ANNOUNCEMENT_META_VOCABULARY, key=len, reverse=True
    ):
        residual = residual.replace(token, "")
    residual = normalize_announcement_grounding_text(residual)
    if not residual:
        return True
    prompt_normalized = normalize_announcement_grounding_text(prompt)
    if not prompt_normalized:
        return False

    def has_non_negated_occurrence(fragment: str) -> bool:
        start = 0
        while True:
            index = prompt_normalized.find(fragment, start)
            if index < 0:
                return False
            prefix = prompt_normalized[max(0, index - 12) : index]
            if not any(prefix.endswith(marker) for marker in PROMPT_NEGATION_PREFIXES):
                return True
            start = index + 1

    while residual:
        matched = False
        for length in range(min(len(residual), 64), 1, -1):
            if has_non_negated_occurrence(residual[:length]):
                residual = residual[length:]
                matched = True
                break
        if matched:
            continue
        digit_match = re.match(r"[0-9]+", residual)
        if digit_match and digit_match.group(0) in prompt_normalized:
            residual = residual[len(digit_match.group(0)) :]
            continue
        return False
    return True


def is_valid_preload_announcement(
    text: str, required_skill_name: str = SKILL_NAME, prompt: str = ""
) -> bool:
    lower = text.lower()
    stripped_lower = text.lstrip().lower()
    canonical_mentioned = SKILL_NAME.lower() in lower
    legacy_mentioned = LEGACY_SKILL_NAME.lower() in lower
    if canonical_mentioned or legacy_mentioned:
        exact_entrypoint_identity = (
            required_skill_name == SKILL_NAME
            and canonical_mentioned
            and not legacy_mentioned
        ) or (
            required_skill_name == LEGACY_SKILL_NAME
            and legacy_mentioned
            and not canonical_mentioned
        )
    else:
        exact_entrypoint_identity = "幕僚长" in text or "chief of staff" in lower
    return (
        len(text) <= 240
        and "\n" not in text
        and "\r" not in text
        and "```" not in text
        and stripped_lower.startswith(
            ("我会", "我将", "现在", "i will", "i'll", "i am", "i'm", "using", "applying")
        )
        and exact_entrypoint_identity
        and (
            "使用" in text
            or "启用" in text
            or "启动" in text
            or "采用" in text
            or "执行" in text
            or "will use" in lower
            or "will apply" in lower
            or "using" in lower
            or "applying" in lower
        )
        and "COS_BOOT_RECEIPT" not in text
        and "已完成" not in text
        and "已接管" not in text
        and "completed" not in lower
        and PRELOAD_RESULT_RE.search(text) is None
        and not any(marker in lower for marker in PRELOAD_BUSINESS_MARKERS)
        and preload_announcement_is_prompt_grounded(text, prompt)
    )


def is_valid_preload_recovery(text: str) -> bool:
    lower = text.lower()
    return (
        len(text) <= 240
        and "\n" not in text
        and "\r" not in text
        and "```" not in text
        and text.count("；") + text.count(";") == 0
        and text.count("，") + text.count(",") <= 1
        and ("技能" in text or "skill" in lower)
        and (
            "读取" in text
            or "定位" in text
            or "路径" in text
            or "位置" in text
            or "改用" in text
            or "read" in lower
            or "locat" in lower
            or "path" in lower
            or "retry" in lower
        )
        and "COS_BOOT_RECEIPT" not in text
        and "已完成" not in text
        and "已接管" not in text
        and "completed" not in lower
        and not any(
            marker in lower
            for marker in PRELOAD_BUSINESS_MARKERS
            if marker not in {"失败", "failed"}
        )
        and preload_text_uses_only_vocabulary(text, PRELOAD_RECOVERY_VOCABULARY)
    )


def boot_sequence_evidence(
    case: dict[str, Any],
    message_events: list[dict[str, object]],
    skill_load_event_indexes: list[int],
    action_event_indexes: list[int] | None = None,
    skill_preload_action_event_indexes: list[int] | None = None,
    skill_location_failure_action_indexes: list[int] | None = None,
) -> dict[str, object]:
    boot_positions = [
        index
        for index, item in enumerate(message_events)
        if str(item.get("text", "")).lstrip().startswith("COS_BOOT_RECEIPT")
    ]
    if boot_positions == [0]:
        boot_index = int(message_events[0].get("event_index", -1))
        actions_before = {
            event_index
            for event_index in (action_event_indexes or [])
            if event_index < boot_index
        }
        load_attempts_before = {
            event_index
            for event_index in (skill_preload_action_event_indexes or [])
            if event_index < boot_index
        }
        loads_before = {
            event_index
            for event_index in skill_load_event_indexes
            if event_index < boot_index
        }
        if loads_before and actions_before == load_attempts_before:
            return {
                "valid": True,
                "boot_message": str(message_events[0]["text"]).lstrip(),
                "boot_message_position": 1,
                "preload_announcement_verified": False,
                "preload_message_count": 0,
            }
    if (
        len(boot_positions) == 1
        and 1 <= boot_positions[0] <= MAX_PRELOAD_MESSAGES
        and case.get("activation") in {"explicit", "implicit"}
        and case.get("allow_preload_announcement") is True
        and is_valid_preload_announcement(
            str(message_events[0].get("text", "")),
            expected_skill_name(case) or SKILL_NAME,
            str(case.get("prompt", "")),
        )
        and all(
            is_valid_preload_recovery(str(item.get("text", "")))
            for item in message_events[1 : boot_positions[0]]
        )
    ):
        preload_count = boot_positions[0]
        announcement_index = int(message_events[0].get("event_index", -1))
        last_preload_index = int(
            message_events[preload_count - 1].get("event_index", -1)
        )
        boot_index = int(message_events[preload_count].get("event_index", -1))
        actions_before_announcement = {
            event_index
            for event_index in (action_event_indexes or [])
            if event_index < announcement_index
        }
        loads_between = {
            event_index
            for event_index in skill_load_event_indexes
            if last_preload_index < event_index < boot_index
        }
        actions_between = {
            event_index
            for event_index in (action_event_indexes or [])
            if announcement_index < event_index < boot_index
        }
        load_attempts_between = {
            event_index
            for event_index in (skill_preload_action_event_indexes or [])
            if announcement_index < event_index < boot_index
        }
        location_failures_before_boot = {
            event_index
            for event_index in (skill_location_failure_action_indexes or [])
            if announcement_index < event_index < boot_index
        }
        location_failures_before_recovery = {
            event_index
            for event_index in location_failures_before_boot
            if event_index < last_preload_index
        }
        recovery_sequence_valid = (
            not location_failures_before_boot
            if preload_count == 1
            else (
                bool(location_failures_before_recovery)
                and location_failures_before_boot
                == location_failures_before_recovery
            )
        )
        if (
            not actions_before_announcement
            and loads_between
            and recovery_sequence_valid
            and actions_between
            == load_attempts_between | location_failures_before_boot
        ):
            return {
                "valid": True,
                "boot_message": str(message_events[preload_count]["text"]).lstrip(),
                "boot_message_position": preload_count + 1,
                "preload_announcement_verified": True,
                "preload_message_count": preload_count,
            }
    observed_boot_position = boot_positions[0] if len(boot_positions) == 1 else None
    observed_boot_message = (
        str(message_events[observed_boot_position].get("text", "")).lstrip()
        if observed_boot_position is not None
        else ""
    )
    return {
        "valid": False,
        "boot_message": observed_boot_message,
        "boot_message_position": (
            observed_boot_position + 1
            if observed_boot_position is not None
            else None
        ),
        "preload_announcement_verified": False,
        "preload_message_count": observed_boot_position or 0,
    }


def contract_failures(
    case: dict[str, Any],
    surface: str,
    assistant_messages: list[str] | None = None,
    collab_tool_events: int = 0,
    assistant_message_events: list[dict[str, object]] | None = None,
    skill_load_event_indexes: list[int] | None = None,
    action_event_indexes: list[int] | None = None,
    skill_preload_action_event_indexes: list[int] | None = None,
    skill_load_events_by_name: dict[str, list[int]] | None = None,
    skill_preload_actions_by_name: dict[str, list[int]] | None = None,
    skill_touch_attempt_ids_by_name: dict[str, list[str]] | None = None,
    skill_touch_first_event_indexes_by_name: dict[str, list[int]] | None = None,
    valid_skill_read_attempt_ids_by_name: dict[str, list[str]] | None = None,
    skill_location_failure_attempt_ids_by_name: dict[str, list[str]] | None = None,
    skill_location_failure_action_indexes_by_name: dict[str, list[int]] | None = None,
    tool_attempt_order: list[str] | None = None,
    context_budget_overflow: bool = False,
    final_text: str | None = None,
    tool_events: int = 0,
    tool_attempts: int | None = None,
) -> list[str]:
    failures: list[str] = []
    messages = assistant_messages or []
    message_events = assistant_message_events or [
        {"event_index": index, "text": message}
        for index, message in enumerate(messages)
    ]
    boot_event_indexes = [
        int(item.get("event_index", -1))
        for item in message_events
        if str(item.get("text", "")).lstrip().startswith("COS_BOOT_RECEIPT")
    ]
    boot_event_index = (
        boot_event_indexes[0] if len(boot_event_indexes) == 1 else None
    )
    booted = "COS_BOOT_RECEIPT" in surface
    if case["should_trigger"] and not booted:
        failures.append("should_trigger=true but no COS_BOOT_RECEIPT was observed")
    if not case["should_trigger"] and booted:
        failures.append("should_trigger=false but COS_BOOT_RECEIPT was observed")
    collaboration = case["collaboration"]
    if collaboration == "none" and collab_tool_events:
        failures.append("collaboration=none but a collaboration tool was attempted")

    load_map = skill_load_events_by_name or {name: [] for name in INSTALL_NAMES}
    preload_map = skill_preload_actions_by_name or {
        name: [] for name in INSTALL_NAMES
    }
    touch_evidence_supplied = skill_touch_attempt_ids_by_name is not None
    touch_map = skill_touch_attempt_ids_by_name or {
        name: [] for name in INSTALL_NAMES
    }
    touch_index_map = skill_touch_first_event_indexes_by_name or {
        name: [] for name in INSTALL_NAMES
    }
    valid_read_map = valid_skill_read_attempt_ids_by_name or {
        name: [] for name in INSTALL_NAMES
    }
    location_failure_id_map = skill_location_failure_attempt_ids_by_name or {
        name: [] for name in INSTALL_NAMES
    }
    expected_name = expected_skill_name(case)
    if expected_name is None:
        guard_name = allowed_guard_skill_name(case)
        for name in INSTALL_NAMES:
            loads = list(load_map.get(name, []))
            preload_actions = list(preload_map.get(name, []))
            touches = list(touch_map.get(name, []))
            valid_reads = list(valid_read_map.get(name, []))
            if name == guard_name and (loads or preload_actions or touches or valid_reads):
                guard_ids = set(touches)
                valid_ids = set(valid_reads)
                first_touch_indexes = list(touch_index_map.get(name, []))
                if len(guard_ids) != 1:
                    failures.append(
                        f"worker guard must touch exactly one stable tool attempt: {name}"
                    )
                if valid_ids != guard_ids or len(loads) != 1:
                    failures.append(
                        f"worker guard did not prove one successful exact full-bundle read: {name}"
                    )
                guard_id = next(iter(guard_ids), None)
                if (
                    guard_id is None
                    or not tool_attempt_order
                    or tool_attempt_order[0] != guard_id
                    or not first_touch_indexes
                    or not action_event_indexes
                    or min(first_touch_indexes) != min(action_event_indexes)
                ):
                    failures.append(
                        f"worker guard was not the first tool action: {name}"
                    )
                continue
            if loads or preload_actions or touches or valid_reads:
                failures.append(
                    f"expected_entrypoint=none but Skill bundle was touched, loaded, or acted on: {name}"
                )
    else:
        expected_loads = list(load_map.get(expected_name, []))
        expected_touches = set(touch_map.get(expected_name, []))
        expected_location_failures = set(
            location_failure_id_map.get(expected_name, [])
        )
        expected_touch_indexes = [
            int(index) for index in touch_index_map.get(expected_name, [])
        ]
        preboot_loads = [
            int(index)
            for index in expected_loads
            if boot_event_index is not None and int(index) < boot_event_index
        ]
        preboot_touches = [
            index
            for index in expected_touch_indexes
            if boot_event_index is None or index < boot_event_index
        ]
        location_failure_indexes = [
            int(index)
            for index in (
                skill_location_failure_action_indexes_by_name or {}
            ).get(expected_name, [])
        ]
        if not expected_loads:
            qualifier = (
                " after Skill context-budget overflow"
                if context_budget_overflow
                else ""
            )
            failures.append(
                f"expected entrypoint bundle load was not observed{qualifier}: {expected_name}"
            )
        if touch_evidence_supplied and (
            len(preboot_loads) != 1
            or len(expected_location_failures) > 1
            or len(preboot_touches) != 1 + len(expected_location_failures)
            or not expected_location_failures.issubset(expected_touches)
            or any(
                boot_event_index is None or index >= boot_event_index
                for index in location_failure_indexes
            )
        ):
            failures.append(
                "expected entrypoint pre-boot phase must have one exact full read plus "
                f"at most one failed location attempt: {expected_name}"
            )
        for name in INSTALL_NAMES:
            if name == expected_name:
                continue
            if (
                load_map.get(name)
                or preload_map.get(name)
                or touch_map.get(name)
                or valid_read_map.get(name)
                or location_failure_id_map.get(name)
            ):
                failures.append(
                    f"unexpected entrypoint bundle was touched, loaded, or acted on: {name}"
                )

    observed_tool_attempts = tool_events if tool_attempts is None else tool_attempts
    if case.get("require_no_tool_events") and observed_tool_attempts:
        failures.append("require_no_tool_events=true but a tool was attempted")
    expected_final = case.get("exact_final")
    if isinstance(expected_final, str):
        observed_final = final_text if final_text is not None else surface
        if observed_final.strip() != expected_final:
            failures.append(
                f"final answer did not exactly match {expected_final!r}"
            )
    if not case["should_trigger"]:
        if case.get("activation") == "worker" and collab_tool_events:
            failures.append("delegated worker used a collaboration tool")
        for marker, expected_count in case.get("exact_marker_counts", {}).items():
            actual_count = surface.count(marker)
            if actual_count != expected_count:
                failures.append(
                    f"marker {marker!r} count {actual_count}, expected {expected_count}"
                )
        return failures

    boot_sequence = boot_sequence_evidence(
        case,
        message_events,
        skill_load_event_indexes or [],
        action_event_indexes or [],
        skill_preload_action_event_indexes or [],
        (
            skill_location_failure_action_indexes_by_name.get(expected_name, [])
            if expected_name is not None
            and skill_location_failure_action_indexes_by_name is not None
            else []
        ),
    )
    if boot_sequence["valid"] is not True:
        failures.append(
            "boot sequence did not prove a task-free first-message boot or a verified Skill preload sequence"
        )
    boot_message = str(boot_sequence["boot_message"])
    expected_boot_receipt = case.get("expected_boot_receipt")
    if (
        isinstance(expected_boot_receipt, str)
        and boot_message != expected_boot_receipt
    ):
        failures.append("boot receipt did not exactly match the case contract")

    mode_markers = {
        "direct": "模式：直接",
        "structured": "模式：结构化",
        "goal": "模式：Goal",
    }
    marker = mode_markers.get(str(case["mode"]))
    if marker and marker not in boot_message:
        failures.append(f"boot receipt does not declare expected {marker}")

    accepted = {
        "none": ("协作：无",),
        "native_subagents": ("协作：原生子代理",),
        "native_subagents_optional": ("协作：无", "协作：原生子代理"),
        "real_task": ("协作：真实任务",),
    }[collaboration]
    if not any(value in boot_message for value in accepted):
        failures.append(
            "boot receipt does not declare expected collaboration: " + " or ".join(accepted)
        )
    expected_entrypoint = case.get("expected_entrypoint")
    if expected_entrypoint in {"canonical", "legacy"}:
        entrypoint_marker = f"入口：{expected_entrypoint}"
        if entrypoint_marker not in boot_message:
            failures.append(f"boot receipt does not declare expected {entrypoint_marker}")
    for marker_name, expected_count in case.get("exact_marker_counts", {}).items():
        actual_count = surface.count(marker_name)
        if actual_count != expected_count:
            failures.append(
                f"marker {marker_name!r} count {actual_count}, expected {expected_count}"
            )
    return failures


def review_prompt_contract_flags(
    prompt: str,
    expected_file: str,
    expected_text: str,
    evidence_marker: str | None = None,
) -> dict[str, bool]:
    return {
        "worker_packet": is_valid_worker_packet(prompt),
        "exact_packet": prompt.rstrip("\n")
        == expected_strict_worker_packet(expected_file),
        "expected_text_not_disclosed": expected_text not in prompt,
        "evidence_marker_not_disclosed": not evidence_marker
        or evidence_marker not in prompt,
    }


def review_prompt_is_self_contained(
    prompt: str,
    expected_file: str,
    expected_text: str,
    evidence_marker: str | None = None,
) -> bool:
    return all(
        review_prompt_contract_flags(
            prompt, expected_file, expected_text, evidence_marker
        ).values()
    )


def is_host_encrypted_collaboration_message(value: str) -> bool:
    return bool(
        100 <= len(value) <= 16_384
        and re.fullmatch(r"gAAAAA[A-Za-z0-9_-]+={0,2}", value)
    )


def claims_passing_cold_review(text: str) -> bool:
    subject = (
        r"(?:cold[- ]?review|cold[- ]?context\s+isolation|"
        r"independent\s+review|独立(?:的)?(?:审核|审查|review))"
    )
    affirmative = r"(?:通过|已验证|\bverified\b|\bpass(?:ed)?\b)"
    return bool(
        re.search(
            rf"(?:{subject}.{{0,28}}{affirmative}|"
            rf"{affirmative}.{{0,28}}{subject})",
            text,
            flags=re.IGNORECASE,
        )
    )


def claims_external_reviewer_result(text: str) -> bool:
    """Detect affirmative reviewer-result claims, not plans or negations."""
    reviewer_subject = (
        r"(?:不同\s*(?:agent|代理)|reviewer|独立(?:的)?(?:审核|review)|"
        r"cold[- ]?review)"
    )
    affirmative_result = (
        r"(?:已完成|完成了|已通过|通过了|pass(?:ed)?|已返回|返回了|"
        r"已报告|报告了|已确认|确认了|给出(?:了)?(?:结论|结果|verdict)|"
        r"(?:结论|结果|verdict)(?:是|为|:|：))"
    )
    patterns = (
        re.compile(
            reviewer_subject
            + r".{0,120}(?P<trigger>"
            + affirmative_result
            + r")",
            flags=re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"(?P<trigger>已收到|收到了|已核对|核对了).{0,120}"
            r"(?:终态结果|审核结果|审查结果|review(?:er)?\s+(?:result|verdict)|"
            r"不同\s*(?:agent|代理).{0,40}(?:结果|结论))",
            flags=re.IGNORECASE | re.DOTALL,
        ),
    )
    return has_unconditional_named_claim(text, patterns)


def claim_trigger_is_conditional(text: str, trigger_start: int) -> bool:
    """Return whether a candidate result belongs to a conditional/current plan."""
    prefix = text[max(0, trigger_start - 96) : trigger_start]
    clause_prefix = re.split(r"[。！？.!?；;\n]", prefix)[-1]
    conditional = re.compile(
        r"(?:若|如果|假如|倘若|如有|是否|有无|"
        r"可能|也许|或许|预计|预期|尚未|未曾|没有|并未|"
        r"(?:我|我们|主线程)\s*(?:将|会|准备|计划|打算)|"
        r"(?:等待|待).{0,48}(?:reviewer|审核|审查|复核|读取|验证)|"
        r"(?:正在)?(?:检查|核对|排查|寻找|复核)(?!发现).{0,24}$|"
        r"(?:将|会|准备|计划|待).{0,16}(?:检查|核对|排查|寻找|复核|发现)|"
        r"\bif\b|\bwhether\b|"
        r"\b(?:may|might|could|would|possibly|perhaps|"
        r"is\s+expected\s+to|was\s+expected\s+to|expected\s+to|"
        r"did\s+not|has\s+not|have\s+not|was\s+not|is\s+not|never|no)\b|"
        r"\b(?:I|we|the\s+main\s+thread)\s+(?:will|shall|plan\s+to|"
        r"intend\s+to|am\s+going\s+to|are\s+going\s+to)\b|"
        r"\bwait(?:ing)?\s+for\b.{0,48}(?:review|read|verif)|"
        r"\b(?:checking\s+for|looking\s+for|searching\s+for)\b.{0,24}$|"
        r"\b(?:will|shall|plan(?:s|ned)?\s+to|going\s+to)\b.{0,24}"
        r"\b(?:check|verify|review|look\s+for|find)\b)",
        flags=re.IGNORECASE,
    )
    return conditional.search(clause_prefix) is not None


def claim_match_is_nonaffirmative(text: str, match: re.Match[str]) -> bool:
    """Reject conditional, negated, unverified, and interrogative claim matches."""
    trigger_start = match.start("trigger")
    trigger_end = match.end("trigger")
    if claim_trigger_is_conditional(text, trigger_start):
        return True
    suffix = text[trigger_end : trigger_end + 48]
    if re.match(
        r"\s*(?:未验证|未经验证|尚未验证|没有|无|不|"
        r"unverified\b|not\s+verified\b|no\b|not\b|never\b|without\b)",
        suffix,
        flags=re.IGNORECASE,
    ):
        return True
    clause_tail = re.split(r"[。！.!；;\n]", text[trigger_end : trigger_end + 96])[0]
    return "?" in clause_tail or "？" in clause_tail


def claims_affirmative_blocking_finding(text: str) -> bool:
    """Detect an affirmative blocking finding without treating plans as results."""
    reviewer = r"(?:reviewer|review|auditor|审核员|审核|审查|复核)"
    finding = (
        r"(?:p0|rce|critical|high[- ]?severity|vulnerabilit(?:y|ies)|漏洞|高危|"
        r"严重|阻塞|block(?:er|ing)?|finding|问题)"
    )
    candidate_patterns = (
        re.compile(
            rf"{reviewer}.{{0,48}}(?P<trigger>发现(?:了)?|存在|found|identified|"
            rf"reported|discovered|detected)"
            rf".{{0,24}}{finding}",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<trigger>\bI\s+(?:found|identified)\b|\bfound\b|"
            rf"发现(?:了)?|存在|需要修复).{{0,24}}{finding}",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<trigger>\bP0\b|critical|严重|阻塞|blocking|blocker).{0,32}"
            r"(?:RCE|vulnerabilit(?:y|ies)|issue|problem|finding|漏洞|问题|风险)",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in candidate_patterns:
        for match in pattern.finditer(text):
            if not claim_match_is_nonaffirmative(text, match):
                return True
    return False


def claims_affirmative_review_failure(text: str) -> bool:
    """Detect a concluded review failure while allowing conditional discussion."""
    pattern = re.compile(
        r"(?:review|审核|审查|复核).{0,16}(?P<trigger>failed|失败|不通过)",
        flags=re.IGNORECASE,
    )
    return any(
        not claim_match_is_nonaffirmative(text, match)
        for match in pattern.finditer(text)
    )


def has_unconditional_named_claim(
    text: str, patterns: tuple[re.Pattern[str], ...]
) -> bool:
    """Return true when a named claim trigger is not conditional or future."""
    return any(
        not claim_match_is_nonaffirmative(text, match)
        for pattern in patterns
        for match in pattern.finditer(text)
    )


def claims_completion_contradiction(text: str) -> bool:
    """Detect user-visible findings, rejection, or overclaimed review evidence."""
    reviewer = r"(?:reviewer|review|auditor|审核员|审核|审查|复核)"
    rejection = (
        re.compile(
            rf"(?P<trigger>拒绝|不接受|暂不接受|不采纳|未采纳|不同意|"
            rf"不认可|否决|驳回|"
            rf"\bdid\s+not\s+accept\b|\bnot\s+adopt(?:ed)?\b|\breject(?:ed)?\b)"
            rf".{{0,48}}(?:{reviewer}|结果|结论|verdict|result)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"(?:{reviewer}|结果|结论|verdict|result).{{0,48}}"
            rf"(?P<trigger>拒绝|不接受|暂不接受|不采纳|未采纳|不同意|"
            rf"不认可|否决|驳回|\bdid\s+not\s+accept\b|"
            rf"\bnot\s+adopt(?:ed)?\b|\breject(?:ed)?\b)",
            flags=re.IGNORECASE,
        ),
    )
    read_overclaim = (
        re.compile(
            rf"{reviewer}.{{0,48}}(?:读取|read).{{0,24}}"
            rf"(?P<trigger>已验证|已经验证|\bverified\b|已确认)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"{reviewer}.{{0,48}}(?P<trigger>独立(?:地)?读取(?:了)?|已读取|"
            rf"已经阅读|阅读了|(?:independently\s+)?read|has\s+read|did\s+read)"
            rf".{{0,48}}(?:README|文件|artifact|file)",
            flags=re.IGNORECASE,
        ),
    )
    isolation_overclaim = (
        re.compile(
            r"(?:上下文隔离|context\s+isolation|cold[- ]?context).{0,24}"
            r"(?P<trigger>已验证|已经验证|\bverified\b|已确认|通过)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?:reviewer|subagent|agent|审核员|子代理).{0,48}"
            r"(?P<trigger>ran|executed|worked|started|运行|执行|工作).{0,32}"
            r"(?:fresh|isolated|cold|隔离).{0,16}(?:context|上下文)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?:reviewer|subagent|agent|审核员|子代理|上下文|context).{0,48}"
            r"(?P<trigger>已经隔离|已隔离|隔离完成|is\s+isolated|was\s+isolated|"
            r"ran\s+isolated|freshly\s+isolated)",
            flags=re.IGNORECASE,
        ),
    )
    return bool(
        claims_affirmative_blocking_finding(text)
        or claims_affirmative_review_failure(text)
        or has_unconditional_named_claim(text, rejection)
        or has_unconditional_named_claim(text, read_overclaim)
        or has_unconditional_named_claim(text, isolation_overclaim)
    )


def main_assistant_message_contract_valid(
    messages: list[tuple[int, datetime | None, str | None]],
    expected_final_text: str,
    expected_boot_receipt: str,
    *,
    allow_final: bool = True,
    require_final: bool = False,
) -> bool:
    """Accept only boot/preload, fixed progress tokens, and the exact final."""
    preload_count = 0
    boot_count = 0
    final_positions: list[int] = []
    progress_positions: list[int] = []
    progress_seen: set[str] = set()
    for index, _, text in messages:
        if not isinstance(text, str):
            return False
        normalized = text.rstrip("\n")
        if normalized == expected_final_text.rstrip("\n"):
            if not allow_final:
                return False
            final_positions.append(index)
            continue
        if normalized == CANONICAL_PRELOAD_ANNOUNCEMENT:
            preload_count += 1
            continue
        if expected_boot_receipt and normalized == expected_boot_receipt:
            boot_count += 1
            continue
        if normalized in MAIN_PROGRESS_SEQUENCE:
            if normalized in progress_seen:
                return False
            progress_seen.add(normalized)
            progress_positions.append(MAIN_PROGRESS_SEQUENCE.index(normalized))
            continue
        return False
    return (
        preload_count <= 1
        and boot_count <= 1
        and (not require_final or len(final_positions) == 1)
        and len(final_positions) <= 1
        and (
            not final_positions
            or final_positions[0] == max(item[0] for item in messages)
        )
        and progress_positions == sorted(progress_positions)
    )


def assistant_response_phase_contract_valid(
    messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ],
    expected_final_text: str,
) -> bool:
    """Bind response-item text to the current commentary/final phase schema."""
    for _, _, text, phase in messages:
        if not isinstance(text, str) or phase not in {
            "commentary",
            "final_answer",
        }:
            return False
        is_final = text.rstrip("\n") == expected_final_text.rstrip("\n")
        if is_final != (phase == "final_answer"):
            return False
    return True


def rollout_event_agent_message(
    payload: dict[str, object],
) -> tuple[str, str] | None:
    """Parse the exact raw rollout event message schema or reject it."""
    if set(payload) != {"type", "message", "phase", "memory_citation"}:
        return None
    if payload.get("type") != "agent_message":
        return None
    # Model evals run in a clean isolated home. Memory-backed prose is outside
    # the closed behavior contract and must not be silently accepted.
    if payload.get("memory_citation") is not None:
        return None
    phase = payload.get("phase")
    message = payload.get("message")
    if not isinstance(phase, str) or not isinstance(message, str) or not message:
        return None
    return phase, message


def main_event_message_contract_valid(
    messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ],
    expected_final_text: str,
    expected_boot_receipt: str,
    *,
    final_after_index: int,
    terminal_index: int,
    final_after_timestamp: datetime,
    terminal_timestamp: datetime,
) -> bool:
    """Validate the raw event channel independently from response messages."""
    commentary: list[tuple[int, datetime | None, str | None]] = []
    finals: list[tuple[int, datetime | None, str]] = []
    for index, timestamp, phase, message in messages:
        if not isinstance(phase, str) or not isinstance(message, str):
            return False
        if phase == "commentary":
            if message.rstrip("\n") == expected_final_text.rstrip("\n"):
                return False
            commentary.append((index, timestamp, message))
        elif phase == "final_answer":
            if message.rstrip("\n") != expected_final_text.rstrip("\n"):
                return False
            finals.append((index, timestamp, message))
        else:
            return False
    if not main_assistant_message_contract_valid(
        commentary,
        expected_final_text,
        expected_boot_receipt,
        allow_final=False,
    ):
        return False
    if len(finals) != 1:
        return False
    final_index, final_timestamp, _ = finals[0]
    if not (
        final_after_index < final_index < terminal_index
        and final_index == max(item[0] for item in messages)
        and isinstance(final_timestamp, datetime)
        and final_after_timestamp <= final_timestamp <= terminal_timestamp
    ):
        return False
    return True


def child_event_message_contract_valid(
    messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ],
    expected_terminal_text: str,
    progress_token: str,
    *,
    turn_index: int,
    commentary_after_index: int | None = None,
    commentary_before_index: int,
    final_after_index: int,
    terminal_index: int,
    commentary_after_timestamp: datetime | None = None,
    final_after_timestamp: datetime | None = None,
    terminal_timestamp: datetime | None = None,
) -> bool:
    """Validate one child event channel without double-counting its mirrors."""
    progress: list[tuple[int, datetime | None, str]] = []
    finals: list[tuple[int, datetime | None, str]] = []
    for index, timestamp, phase, message in messages:
        if not isinstance(phase, str) or not isinstance(message, str):
            return False
        normalized = message.rstrip("\n")
        if phase == "commentary":
            if normalized != progress_token:
                return False
            progress.append((index, timestamp, message))
        elif phase == "final_answer":
            if normalized != expected_terminal_text.rstrip("\n"):
                return False
            finals.append((index, timestamp, message))
        else:
            return False
    if len(progress) > 1 or len(finals) != 1:
        return False
    if progress and not (
        turn_index < progress[0][0] < commentary_before_index
    ):
        return False
    if progress and commentary_after_index is not None and not (
        commentary_after_index < progress[0][0]
    ):
        return False
    if progress and commentary_after_timestamp is not None and (
        not isinstance(progress[0][1], datetime)
        or progress[0][1] <= commentary_after_timestamp
    ):
        return False
    final_index, final_timestamp, _ = finals[0]
    if not (
        final_after_index < final_index < terminal_index
        and final_index == max(item[0] for item in messages)
    ):
        return False
    if final_after_timestamp is not None and (
        not isinstance(final_timestamp, datetime)
        or final_timestamp < final_after_timestamp
    ):
        return False
    if terminal_timestamp is not None and (
        not isinstance(final_timestamp, datetime)
        or final_timestamp > terminal_timestamp
    ):
        return False
    return True


def expected_review_terminal(evidence_marker: str, expected_text: str) -> str:
    """Return the only accepted zero-finding reviewer terminal."""
    return "\n".join(
        (
            REVIEW_EVIDENCE_FIRST_LINE_PREFIX + evidence_marker,
            REVIEW_EVIDENCE_TARGET_LINE_PREFIX + expected_text,
            REVIEW_FINDINGS_COUNT_ZERO,
            REVIEW_NO_BLOCKERS_VERDICT,
        )
    )


def review_terminal_has_no_blockers(
    text: str, evidence_marker: str, expected_text: str
) -> bool:
    return text.rstrip("\n") == expected_review_terminal(
        evidence_marker, expected_text
    )


def expected_main_review_adoption(
    evidence_marker: str, expected_text: str
) -> str:
    return "\n".join(
        (
            expected_review_terminal(evidence_marker, expected_text),
            MAIN_REVIEW_ADOPTION_ACCEPTED,
            COLD_CONTEXT_ISOLATION_UNVERIFIED,
        )
    )


def final_adopts_review_evidence(
    text: str, evidence_marker: str, expected_text: str
) -> bool:
    if not evidence_marker or not expected_text:
        return False
    return text.rstrip("\n") == expected_main_review_adoption(
        evidence_marker, expected_text
    )


def parsed_json_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def explicit_spawn_failure_output(value: object) -> bool:
    """Accept only a non-success spawn output that explicitly reports failure."""
    parsed = parsed_json_object(value)
    if parsed is not None:
        if "task_name" in parsed:
            return False
        error = parsed.get("error")
        status = parsed.get("status")
        return bool(
            (isinstance(error, str) and error.strip())
            or (
                isinstance(status, str)
                and status.lower()
                in {"failed", "error", "rejected", "unavailable", "cancelled", "canceled"}
            )
        )
    if not isinstance(value, str) or not value.strip():
        return False
    return bool(
        re.search(
            r"\b(?:error|failed|failure|unavailable|unable|rejected|limit|capacity|conflict|exists|duplicate|cancelled|canceled)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def rollout_record_timestamp(record: dict[str, object]) -> datetime | None:
    value = record.get("timestamp")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def rollout_assistant_response_message(
    payload: dict[str, object],
) -> tuple[str, str] | None:
    """Return one exact phased assistant output_text; mixed content is invalid."""
    if payload.get("type") != "message" or payload.get("role") != "assistant":
        return None
    phase = payload.get("phase")
    if phase not in {"commentary", "final_answer"}:
        return None
    content = payload.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if (
        not isinstance(item, dict)
        or set(item) != {"type", "text"}
        or item.get("type") != "output_text"
        or not isinstance(item.get("text"), str)
        or not item.get("text")
    ):
        return None
    return str(phase), str(item["text"])


def rollout_assistant_response_content(payload: dict[str, object]) -> str | None:
    """Compatibility accessor for one exact phased assistant response."""
    parsed = rollout_assistant_response_message(payload)
    return parsed[1] if parsed is not None else None


def rollout_delivery_content(payload: dict[str, object]) -> str | None:
    """Return one exact delivered input_text block; mixed content is invalid."""
    if payload.get("type") != "agent_message":
        return None
    content = payload.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if (
        not isinstance(item, dict)
        or set(item) != {"type", "text"}
        or item.get("type") != "input_text"
        or not isinstance(item.get("text"), str)
        or not item.get("text")
    ):
        return None
    return str(item["text"])


def rollout_inbound_agent_message(
    payload: dict[str, object],
) -> tuple[str, str, str] | None:
    """Parse one syntactically bound parent-to-child transport envelope."""
    if set(payload) != {
        "type",
        "author",
        "recipient",
        "content",
        "internal_chat_message_metadata_passthrough",
    } or payload.get("type") != "agent_message":
        return None
    author = payload.get("author")
    recipient = payload.get("recipient")
    metadata = payload.get("internal_chat_message_metadata_passthrough")
    content = payload.get("content")
    if (
        not isinstance(author, str)
        or not author
        or not isinstance(recipient, str)
        or not recipient
        or not isinstance(metadata, dict)
        or set(metadata) != {"turn_id"}
        or not isinstance(metadata.get("turn_id"), str)
        or not isinstance(content, list)
        or len(content) != 2
    ):
        return None
    visible, encrypted = content
    if (
        not isinstance(visible, dict)
        or set(visible) != {"type", "text"}
        or visible.get("type") != "input_text"
        or not isinstance(visible.get("text"), str)
        or visible.get("text")
        != f"Message Type: NEW_TASK\nTask name: {recipient}\nSender: {author}\nPayload:\n"
        or not isinstance(encrypted, dict)
        or set(encrypted) != {"type", "encrypted_content"}
        or encrypted.get("type") != "encrypted_content"
        or not isinstance(encrypted.get("encrypted_content"), str)
        or not is_host_encrypted_collaboration_message(
            str(encrypted["encrypted_content"])
        )
    ):
        return None
    return author, recipient, str(metadata["turn_id"])


def child_transport_action_surface_valid(
    records: list[dict[str, object]], turn_index: int, inbound_index: int
) -> bool:
    """Require the transport to be first and reject unknown child actions."""
    if not (0 <= turn_index < inbound_index < len(records)):
        return False
    first_response = next(
        (
            index
            for index in range(turn_index + 1, len(records))
            if records[index].get("type") == "response_item"
        ),
        None,
    )
    if first_response != inbound_index:
        return False
    for index in range(turn_index + 1, inbound_index):
        if records[index].get("type") == "event_msg":
            return False
    tool_types = {
        "custom_tool_call",
        "function_call",
        "custom_tool_call_output",
        "function_call_output",
    }
    for index in range(inbound_index, len(records)):
        record = records[index]
        payload = record.get("payload")
        if record.get("type") == "response_item":
            if not isinstance(payload, dict):
                return False
            item_type = payload.get("type")
            if index == inbound_index:
                if item_type != "agent_message":
                    return False
            elif item_type == "agent_message":
                return False
            elif item_type == "message":
                if payload.get("role") != "assistant":
                    return False
            elif item_type == "reasoning" or item_type in tool_types:
                continue
            else:
                return False
        elif record.get("type") == "event_msg":
            if not isinstance(payload, dict) or payload.get("type") not in {
                "agent_message",
                "task_complete",
                "token_count",
            }:
                return False
    return True


def rollout_spawn_evidence(
    rollout_source: Path | dict[PurePosixPath, bytes],
    main_thread_id: str | None,
) -> dict[str, object]:
    """Bind completed spawn calls to the main rollout without trusting prose."""
    failures: list[str] = []
    evidence: dict[str, object] = {
        "source": "codex_rollout_main_spawn_lifecycle",
        "main_spawn_call_count": 0,
        "completed_spawn_count": 0,
        "context_isolation_requested_count": 0,
        "schema_failures": failures,
    }
    if not isinstance(main_thread_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", main_thread_id
    ):
        failures.append("spawn evidence lacked a valid main thread id")
        return evidence
    snapshot, tree_failures = resolved_rollout_snapshot(rollout_source)
    if tree_failures:
        failures.extend(tree_failures)
        return evidence
    main_candidates = [
        path for path in snapshot if path.name.endswith(f"-{main_thread_id}.jsonl")
    ]
    if len(main_candidates) != 1:
        failures.append("spawn evidence did not map to exactly one main rollout")
        return evidence
    try:
        text = snapshot[main_candidates[0]].decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        failures.append("spawn evidence main rollout was not bounded UTF-8 JSONL")
        return evidence
    calls: dict[str, tuple[int, dict[str, object] | None]] = {}
    outputs: dict[str, tuple[int, object]] = {}
    duplicate_lifecycle = False
    for index, line in enumerate(split_jsonl_records(text)):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            failures.append("spawn evidence main rollout contained malformed JSONL")
            return evidence
        if not isinstance(record, dict):
            failures.append("spawn evidence main rollout contained a non-object record")
            return evidence
        payload = record.get("payload")
        if record.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        call_id = payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        if payload.get("type") == "function_call" and payload.get("name") == "spawn_agent":
            if call_id in calls:
                duplicate_lifecycle = True
            calls[call_id] = (index, parsed_json_object(payload.get("arguments")))
        elif payload.get("type") == "function_call_output":
            if call_id in outputs:
                duplicate_lifecycle = True
            outputs[call_id] = (index, payload.get("output"))
    evidence["main_spawn_call_count"] = len(calls)
    if duplicate_lifecycle:
        failures.append("spawn evidence reused a collaboration lifecycle id")
        return evidence
    completed = 0
    isolated = 0
    for call_id, (call_index, arguments) in calls.items():
        if not isinstance(arguments, dict) or set(arguments) != {
            "task_name",
            "message",
            "fork_turns",
        }:
            continue
        task_name = arguments.get("task_name")
        message = arguments.get("message")
        if (
            not isinstance(task_name, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", task_name)
            or not isinstance(message, str)
            or not message
            or arguments.get("fork_turns") != "none"
        ):
            continue
        output_record = outputs.get(call_id)
        if output_record is None or output_record[0] <= call_index:
            continue
        output = parsed_json_object(output_record[1])
        reviewer_path = output.get("task_name") if output is not None else None
        if (
            not isinstance(reviewer_path, str)
            or not reviewer_path.endswith(f"/{task_name}")
            or not re.fullmatch(r"/[a-z0-9_/-]{1,192}", reviewer_path)
        ):
            continue
        completed += 1
        isolated += 1
    evidence["completed_spawn_count"] = completed
    evidence["context_isolation_requested_count"] = isolated
    return evidence


def delivered_review_message_matches(
    content: str,
    reviewer_path: str,
    parent_path: str,
    reviewer_message: str,
) -> bool:
    """Accept only the current exact host FINAL_ANSWER delivery envelope."""
    payload = reviewer_message.rstrip("\n")
    expected = (
        "Message Type: FINAL_ANSWER\n"
        f"Task name: {parent_path}\n"
        f"Sender: {reviewer_path}\n"
        "Payload:\n"
        f"{payload}"
    )
    return content.rstrip("\n") == expected


def expected_strict_worker_fields(expected_file: str) -> dict[str, str]:
    return {
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
            f"如需 artifact 工具前进度，只能精确输出 {STRICT_REVIEW_PROGRESS}。"
        ),
        "停止条件": "完成一次 artifact 读取和唯一终态后停止，不输出启动行或继续派发。",
    }


def expected_strict_worker_packet(expected_file: str) -> str:
    fields = expected_strict_worker_fields(expected_file)
    return "\n".join(
        ["AGENCY_WORKER: true"]
        + [f"{label}：{value}" for label, value in fields.items()]
    )


def expected_natural_worker_fields(expected_file: str) -> dict[str, str]:
    return {
        "委派目标": (
            f"独立复核 {expected_file} 修改。"
        ),
        "读取范围": f"{expected_file}。",
        "写入范围": "无。",
        "期望产物": (
            f"从 {expected_file} 直接读回的当前完整目标行；"
            "不得使用主线程提供的预期值。"
        ),
        "验证要求": (
            f"直接读取 {expected_file} 后检查当前文件；终态严格使用 "
            "NATURAL_REVIEW_FILE、NATURAL_REVIEW_TARGET、REVIEW_VERDICT 三行，"
            "NATURAL_REVIEW_TARGET 填实际读回的完整目标行；"
            "REVIEW_VERDICT 只能为 NO_BLOCKING_FINDINGS 或 BLOCKING_FINDINGS，禁止 PASS；"
            f"如需终态前进度，只能精确输出 {NATURAL_REVIEW_PROGRESS}。"
        ),
        "停止条件": "完成复核并返回唯一终态。",
    }


def expected_natural_worker_packet(expected_file: str) -> str:
    fields = expected_natural_worker_fields(expected_file)
    return "\n".join(
        ["AGENCY_WORKER: true"]
        + [f"{label}：{value}" for label, value in fields.items()]
    )


def natural_review_prompt_checks(
    prompt: str, expected_file: str, expected_text: str
) -> dict[str, bool]:
    """Check an exact worker contract without prescribing its tool sequence."""
    fields = worker_packet_fields(prompt)
    expected = expected_natural_worker_fields(expected_file)
    if fields is None:
        return {
            "worker_packet": False,
            "exact_packet": False,
            "review_goal": False,
            "read_scope": False,
            "no_write_scope": False,
            "expected_target_contract": False,
            "expected_answer_absent": False,
            "verification_goal": False,
            "terminal_schema": False,
            "stop_condition": False,
        }
    return {
        "worker_packet": True,
        "exact_packet": prompt.rstrip("\n")
        == expected_natural_worker_packet(expected_file),
        "review_goal": fields["委派目标"] == expected["委派目标"],
        "read_scope": fields["读取范围"] == expected["读取范围"],
        "no_write_scope": fields["写入范围"] == expected["写入范围"],
        "expected_target_contract": fields["期望产物"] == expected["期望产物"],
        "expected_answer_absent": expected_text not in prompt,
        "verification_goal": fields["验证要求"] == expected["验证要求"],
        "terminal_schema": all(
            marker in fields["验证要求"]
            for marker in (
                "NATURAL_REVIEW_FILE",
                "NATURAL_REVIEW_TARGET",
                "REVIEW_VERDICT",
            )
        ),
        "stop_condition": fields["停止条件"] == expected["停止条件"],
    }


def expected_natural_review_terminal(expected_file: str, expected_text: str) -> str:
    return "\n".join(
        (
            NATURAL_REVIEW_FILE_PREFIX + expected_file,
            NATURAL_REVIEW_TARGET_PREFIX + expected_text,
            REVIEW_NO_BLOCKERS_VERDICT,
        )
    )


def natural_review_terminal_is_substantive(
    text: str, expected_file: str, expected_text: str
) -> bool:
    """Require an exact task-bound terminal while keeping tool choice open."""
    return text.rstrip("\n") == expected_natural_review_terminal(
        expected_file, expected_text
    )


def rollout_collab_completion_evidence(
    rollout_source: Path | dict[PurePosixPath, bytes],
    main_thread_id: str | None,
    fixture: Path,
    expected_file: str,
    expected_text: str,
    expected_main_final_text: str,
    expected_boot_receipt: str,
    artifact_mtime_ns: int | None,
    artifact_ctime_ns: int | None,
    expected_model: str | None,
    expected_provider: str,
    expected_reasoning_effort: str | None,
    expected_cli_version: str,
    auth_secrets: set[str],
) -> dict[str, object]:
    """Bind one natural child completion, delivery, and explicit main adoption."""
    failures: list[str] = []
    rejection_codes: list[str] = []
    evidence: dict[str, object] = {
        "source": "codex_rollout_natural_collaboration_completion",
        "main_spawn_call_count": 0,
        "completed_spawn_count": 0,
        "failed_spawn_attempt_count": 0,
        "spawn_retry_count": 0,
        "started_activity_count": 0,
        "child_rollout_count": 0,
        "child_session_meta_count": 0,
        "child_turn_context_count": 0,
        "child_terminal_count": 0,
        "child_inbound_agent_message_count": 0,
        "child_inbound_agent_message_contract_verified": False,
        "child_progress_message_count": 0,
        "child_event_progress_message_count": 0,
        "child_response_message_attempt_count": 0,
        "child_preload_announcement_count": 0,
        "child_boot_receipt_count": 0,
        "child_expected_terminal_message_count": 0,
        "child_pass_schema_message_count": 0,
        "child_response_turn_binding_verified": False,
        "child_event_message_attempt_count": 0,
        "child_event_message_contract_verified": False,
        "reviewer_delivery_attempt_count": 0,
        "main_agent_delivery_attempt_count": 0,
        "reviewer_message_call_count": 0,
        "bound_delivery_count": 0,
        "main_terminal_count": 0,
        "main_response_message_attempt_count": 0,
        "main_response_turn_binding_verified": False,
        "main_event_message_attempt_count": 0,
        "main_event_message_contract_verified": False,
        "context_isolation_requested_count": 0,
        "context_isolation_verified_count": 0,
        "reviewer_owned_read_verified": False,
        "child_terminal_after_artifact_verified": False,
        "artifact_final_before_spawn_verified": False,
        "artifact_change_time_basis": "max_mtime_ctime",
        "artifact_spawn_timestamp_tolerance_ms": 0,
        "started_timestamp_tolerance_ms": 250,
        "delivery_after_child_terminal_verified": False,
        "delivery_before_main_terminal_verified": False,
        "delivery_parent_turn_verified": False,
        "reviewer_result_copied_to_final": False,
        "main_adoption_verified": False,
        "isolation_disclosure_verified": False,
        "reviewer_owned_read_disclosure_verified": False,
        "review_prompt_visibility": None,
        "review_prompt_content_verified": False,
        "completion_chain_count": 0,
        "completion_chain_terminal_stage": "main_not_bound",
        "completion_record_sha256": None,
        "auth_exact_value_leak_detected": False,
        "rejection_codes": rejection_codes,
        "schema_failures": failures,
    }

    def reject(code: str, message: str) -> dict[str, object]:
        if code not in rejection_codes:
            rejection_codes.append(code)
        failures.append(message)
        evidence["rejection_codes"] = sorted(rejection_codes)
        evidence["schema_failures"] = sorted(set(failures))
        return evidence

    if not isinstance(main_thread_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", main_thread_id
    ):
        return reject(
            "E_COMPLETION_MAIN_ID", "completion evidence lacked a valid main thread id"
        )
    if (
        not expected_file
        or not expected_text
        or not expected_main_final_text
        or not expected_boot_receipt
        or artifact_mtime_ns is None
        or artifact_mtime_ns < 0
        or artifact_ctime_ns is None
        or artifact_ctime_ns < 0
    ):
        return reject(
            "E_COMPLETION_ARTIFACT_CONTRACT",
            "completion evidence lacked the post-change artifact contract",
        )
    if (
        not isinstance(expected_model, str)
        or not EXECUTION_ID_RE.fullmatch(expected_model)
        or expected_provider != LOCKED_MODEL_PROVIDER
        or not isinstance(expected_reasoning_effort, str)
        or not REASONING_EFFORT_RE.fullmatch(expected_reasoning_effort)
        or not CLI_VERSION_VALUE_RE.fullmatch(expected_cli_version)
    ):
        return reject(
            "E_COMPLETION_IDENTITY_CONTRACT",
            "completion evidence lacked the expected child identity",
        )
    snapshot, tree_failures = resolved_rollout_snapshot(rollout_source)
    if tree_failures:
        failures.extend(tree_failures)
        return reject(
            "E_COMPLETION_SNAPSHOT", "completion rollout snapshot was not trustworthy"
        )
    rollout_files = sorted(snapshot)
    main_candidates = [
        path for path in rollout_files if path.name.endswith(f"-{main_thread_id}.jsonl")
    ]
    if len(main_candidates) != 1:
        return reject(
            "E_COMPLETION_MAIN_ROLLOUT",
            "completion evidence did not map to exactly one main rollout",
        )

    def records_for(path: PurePosixPath, label: str) -> list[dict[str, object]] | None:
        try:
            text = snapshot[path].decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            failures.append(f"{label} rollout was not bounded UTF-8 JSONL")
            return None
        _, leak = redact_exact_auth_values(text, auth_secrets)
        if leak:
            evidence["auth_exact_value_leak_detected"] = True
            failures.append(f"{label} rollout contained an exact auth value")
            return None
        records: list[dict[str, object]] = []
        for line in split_jsonl_records(text):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"{label} rollout contained malformed JSONL")
                return None
            if not isinstance(record, dict):
                failures.append(f"{label} rollout contained a non-object record")
                return None
            records.append(record)
        return records

    main_records = records_for(main_candidates[0], "main completion")
    if main_records is None:
        return reject(
            "E_COMPLETION_MAIN_SCHEMA", "main completion rollout was not valid"
        )
    main_turns: list[tuple[int, datetime | None, dict[str, object]]] = []
    spawn_calls: list[
        tuple[
            int,
            datetime | None,
            str,
            dict[str, object] | None,
            object,
            object,
        ]
    ] = []
    outputs: dict[str, tuple[int, datetime | None, object, object]] = {}
    activities: list[
        tuple[int, datetime | None, str, str, str, str | None, object]
    ] = []
    delivery_attempts: list[
        tuple[
            int,
            datetime | None,
            str | None,
            str | None,
            str | None,
            object,
        ]
    ] = []
    main_assistant_messages: list[
        tuple[int, datetime | None, str | None, str | None, object]
    ] = []
    main_event_messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ] = []
    main_terminals: list[tuple[int, datetime | None, str | None, str | None]] = []
    call_ids: set[str] = set()
    output_ids: set[str] = set()
    duplicate_lifecycle = False
    main_failure_count = 0
    main_spawn_attempt_count = 0
    started_activity_attempt_count = 0
    failed_activity_attempt_count = 0
    main_delivery_schema_failure = False
    reviewer_message_calls: list[tuple[int, datetime | None, str, object]] = []
    for index, record in enumerate(main_records):
        payload = record.get("payload")
        timestamp = rollout_record_timestamp(record)
        if record.get("type") == "turn_context":
            if isinstance(payload, dict):
                main_turns.append((index, timestamp, payload))
            else:
                main_turns.append((index, timestamp, {}))
            continue
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "response_item":
            payload_type = payload.get("type")
            call_id = payload.get("call_id")
            if (
                payload_type == "function_call"
                and payload.get("name") in {"followup_task", "send_message"}
            ):
                reviewer_message_calls.append(
                    (
                        index,
                        timestamp,
                        str(payload.get("name")),
                        payload.get("arguments"),
                    )
                )
            elif payload_type == "function_call" and payload.get("name") == "spawn_agent":
                main_spawn_attempt_count += 1
                if isinstance(call_id, str) and call_id:
                    if call_id in call_ids:
                        duplicate_lifecycle = True
                    call_ids.add(call_id)
                    spawn_calls.append(
                        (
                            index,
                            timestamp,
                            call_id,
                            parsed_json_object(payload.get("arguments")),
                            payload.get("namespace"),
                            payload.get("internal_chat_message_metadata_passthrough"),
                        )
                    )
            elif payload_type == "function_call_output" and isinstance(call_id, str):
                if call_id in output_ids:
                    duplicate_lifecycle = True
                output_ids.add(call_id)
                outputs[call_id] = (
                    index,
                    timestamp,
                    payload.get("output"),
                    payload.get("internal_chat_message_metadata_passthrough"),
                )
            elif payload_type == "agent_message":
                content = rollout_delivery_content(payload)
                if content is None:
                    main_delivery_schema_failure = True
                delivery_attempts.append(
                    (
                        index,
                        timestamp,
                        str(payload["author"])
                        if isinstance(payload.get("author"), str)
                        else None,
                        str(payload["recipient"])
                        if isinstance(payload.get("recipient"), str)
                        else None,
                        content,
                        payload.get("internal_chat_message_metadata_passthrough"),
                    )
                )
            elif payload_type == "message" and payload.get("role") == "assistant":
                parsed_response = rollout_assistant_response_message(payload)
                main_assistant_messages.append(
                    (
                        index,
                        timestamp,
                        parsed_response[1]
                        if parsed_response is not None
                        else None,
                        parsed_response[0]
                        if parsed_response is not None
                        else None,
                        payload.get("internal_chat_message_metadata_passthrough"),
                    )
                )
        elif record.get("type") == "event_msg":
            if payload.get("type") == "agent_message":
                parsed_event_message = rollout_event_agent_message(payload)
                main_event_messages.append(
                    (
                        index,
                        timestamp,
                        parsed_event_message[0]
                        if parsed_event_message is not None
                        else None,
                        parsed_event_message[1]
                        if parsed_event_message is not None
                        else None,
                    )
                )
            elif payload.get("type") == "sub_agent_activity":
                activity_kind = payload.get("kind")
                if activity_kind == "started":
                    started_activity_attempt_count += 1
                if isinstance(activity_kind, str) and activity_kind.lower() in {
                    "failed",
                    "cancelled",
                    "canceled",
                    "errored",
                    "aborted",
                }:
                    failed_activity_attempt_count += 1
                if (
                    isinstance(payload.get("agent_path"), str)
                    and isinstance(payload.get("agent_thread_id"), str)
                    and isinstance(activity_kind, str)
                ):
                    activities.append(
                        (
                            index,
                            timestamp,
                            str(payload["agent_path"]),
                            str(payload["agent_thread_id"]),
                            activity_kind,
                            str(payload["event_id"])
                            if isinstance(payload.get("event_id"), str)
                            else None,
                            payload.get("occurred_at_ms"),
                        )
                    )
            elif payload.get("type") == "task_complete":
                main_terminals.append(
                    (
                        index,
                        timestamp,
                        str(payload["turn_id"])
                        if isinstance(payload.get("turn_id"), str)
                        else None,
                        str(payload["last_agent_message"])
                        if isinstance(payload.get("last_agent_message"), str)
                        else None,
                    )
                )
        if (
            record.get("type") in {"turn_aborted", "turn.failed"}
            or payload.get("type")
            in {"turn_aborted", "task_failed", "agent_error", "stream_error"}
        ):
            main_failure_count += 1
    evidence["main_spawn_call_count"] = main_spawn_attempt_count
    evidence["main_terminal_count"] = len(main_terminals)
    evidence["main_response_message_attempt_count"] = len(
        main_assistant_messages
    )
    evidence["main_event_message_attempt_count"] = len(main_event_messages)
    evidence["main_agent_delivery_attempt_count"] = len(delivery_attempts)
    evidence["reviewer_message_call_count"] = len(reviewer_message_calls)
    if reviewer_message_calls:
        return reject(
            "E_COMPLETION_REVIEWER_MESSAGE_MUTATION",
            "natural completion attempted to mutate a spawned reviewer packet",
        )
    if main_delivery_schema_failure:
        return reject(
            "E_COMPLETION_DELIVERY_SCHEMA",
            "natural completion exposed a malformed delivered agent message",
        )
    if duplicate_lifecycle:
        return reject(
            "E_COMPLETION_MAIN_LIFECYCLE_DUPLICATE",
            "main completion rollout reused a lifecycle id",
        )
    if len(main_turns) != 1 or len(main_terminals) != 1:
        return reject(
            "E_COMPLETION_MAIN_TERMINAL_CARDINALITY",
            "main completion rollout did not expose one turn and one terminal",
        )
    main_turn_index, main_turn_timestamp, main_turn_payload = main_turns[0]
    main_turn_id = main_turn_payload.get("turn_id")
    main_terminal_index, main_terminal_timestamp, terminal_turn_id, terminal_text = (
        main_terminals[0]
    )
    if (
        not isinstance(main_turn_id, str)
        or terminal_turn_id != main_turn_id
        or not isinstance(main_terminal_timestamp, datetime)
        or terminal_text is None
        or terminal_text.rstrip("\n") != expected_main_final_text.rstrip("\n")
        or not isinstance(main_turn_timestamp, datetime)
        or main_terminal_timestamp < main_turn_timestamp
        or main_terminal_index != len(main_records) - 1
        or main_failure_count != 0
    ):
        return reject(
            "E_COMPLETION_MAIN_TERMINAL",
            "main completion terminal did not bind to the persisted final answer",
        )
    if any(
        item[4] != {"turn_id": main_turn_id}
        for item in main_assistant_messages
    ):
        return reject(
            "E_COMPLETION_MAIN_RESPONSE_TURN_BINDING",
            "natural completion main response was not bound to the current turn",
        )
    evidence["main_response_turn_binding_verified"] = True
    evidence["completion_chain_terminal_stage"] = "main_terminal"
    if main_spawn_attempt_count not in {1, 2} or len(spawn_calls) != main_spawn_attempt_count:
        return reject(
            "E_COMPLETION_SPAWN_CARDINALITY",
            "natural completion exceeded the one-failure/one-retry spawn budget",
        )

    successful_spawn_calls = []
    for candidate in spawn_calls:
        candidate_arguments = candidate[3]
        candidate_output = outputs.get(candidate[2])
        if not isinstance(candidate_arguments, dict) or candidate_output is None:
            continue
        candidate_task_name = candidate_arguments.get("task_name")
        parsed_output = parsed_json_object(candidate_output[2])
        if (
            isinstance(candidate_task_name, str)
            and isinstance(parsed_output, dict)
            and set(parsed_output) == {"task_name"}
            and parsed_output.get("task_name") == f"/root/{candidate_task_name}"
        ):
            successful_spawn_calls.append(candidate)
    if len(successful_spawn_calls) != 1:
        return reject(
            "E_COMPLETION_SPAWN_OUTPUT"
            if len(spawn_calls) == 1
            else "E_COMPLETION_COMPLETED_SPAWN_CARDINALITY",
            "natural completion did not contain exactly one completed spawn",
        )
    (
        spawn_index,
        spawn_timestamp,
        spawn_call_id,
        arguments,
        spawn_namespace,
        spawn_turn_metadata,
    ) = successful_spawn_calls[0]
    artifact_latest_change_ns = max(artifact_mtime_ns, artifact_ctime_ns)
    artifact_changed_at = datetime.fromtimestamp(
        artifact_latest_change_ns / 1_000_000_000, tz=timezone.utc
    )
    if len(spawn_calls) == 2:
        failed_calls = [item for item in spawn_calls if item[2] != spawn_call_id]
        failed_call = failed_calls[0]
        (
            failed_index,
            failed_timestamp,
            failed_call_id,
            failed_arguments,
            failed_namespace,
            failed_turn_metadata,
        ) = failed_call
        failed_output_record = outputs.get(failed_call_id)
        if (
            not isinstance(failed_timestamp, datetime)
            or failed_index <= main_turn_index
            or failed_timestamp < main_turn_timestamp
            or failed_timestamp <= artifact_changed_at
            or failed_index >= spawn_index
            or failed_namespace != "collaboration"
            or failed_turn_metadata != {"turn_id": main_turn_id}
            or not isinstance(failed_arguments, dict)
            or set(failed_arguments) != {"task_name", "message", "fork_turns"}
            or failed_arguments.get("fork_turns") != "none"
            or not isinstance(failed_arguments.get("task_name"), str)
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9_-]{0,63}", str(failed_arguments.get("task_name"))
            )
            or not isinstance(failed_arguments.get("message"), str)
            or not failed_arguments.get("message")
            or not isinstance(arguments, dict)
            or failed_arguments.get("message") != arguments.get("message")
            or failed_output_record is None
            or failed_output_record[0] <= failed_index
            or failed_output_record[0] >= spawn_index
            or not isinstance(failed_output_record[1], datetime)
            or failed_output_record[1] < failed_timestamp
            or failed_output_record[3] != {"turn_id": main_turn_id}
            or not explicit_spawn_failure_output(failed_output_record[2])
            or any(item[5] == failed_call_id for item in activities)
        ):
            return reject(
                "E_COMPLETION_SPAWN_RETRY_CONTRACT",
                "natural completion retry was not preceded by one explicit, childless spawn failure",
            )
        evidence["failed_spawn_attempt_count"] = 1
        evidence["spawn_retry_count"] = 1
    if (
        not isinstance(spawn_timestamp, datetime)
        or spawn_index <= main_turn_index
        or spawn_timestamp < main_turn_timestamp
        or spawn_namespace != "collaboration"
        or not isinstance(spawn_turn_metadata, dict)
        or set(spawn_turn_metadata) != {"turn_id"}
        or spawn_turn_metadata.get("turn_id") != main_turn_id
        or not isinstance(arguments, dict)
        or set(arguments) != {"task_name", "message", "fork_turns"}
        or arguments.get("fork_turns") != "none"
        or not isinstance(arguments.get("task_name"), str)
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,63}", str(arguments.get("task_name"))
        )
        or not isinstance(arguments.get("message"), str)
        or not str(arguments.get("message"))
    ):
        return reject(
            "E_COMPLETION_SPAWN_CONTRACT",
            "natural completion spawn did not use one isolated worker packet",
        )
    if spawn_timestamp <= artifact_changed_at:
        return reject(
            "E_COMPLETION_SPAWN_BEFORE_FINAL_ARTIFACT",
            "natural completion reviewer was not spawned strictly after the final artifact change",
        )
    evidence["artifact_final_before_spawn_verified"] = True
    prompt = str(arguments["message"])
    prompt_checks = natural_review_prompt_checks(prompt, expected_file, expected_text)
    opaque_prompt = is_host_encrypted_collaboration_message(prompt)
    if not opaque_prompt and not all(prompt_checks.values()):
        return reject(
            "E_COMPLETION_PROMPT_CONTRACT",
            "natural completion reviewer packet was not self-contained",
        )
    evidence["review_prompt_visibility"] = "opaque" if opaque_prompt else "plaintext"
    evidence["review_prompt_content_verified"] = not opaque_prompt
    output_record = outputs.get(spawn_call_id)
    if output_record is None or output_record[0] <= spawn_index:
        return reject(
            "E_COMPLETION_SPAWN_OUTPUT",
            "natural completion spawn lacked a later bound output",
        )
    (
        spawn_output_index,
        spawn_output_timestamp,
        spawn_output_value,
        spawn_output_turn_metadata,
    ) = output_record
    spawn_output = parsed_json_object(spawn_output_value)
    reviewer_path = spawn_output.get("task_name") if spawn_output else None
    task_name = str(arguments["task_name"])
    if (
        not isinstance(spawn_output_timestamp, datetime)
        or spawn_output_timestamp < spawn_timestamp
        or not isinstance(spawn_output_turn_metadata, dict)
        or set(spawn_output_turn_metadata) != {"turn_id"}
        or spawn_output_turn_metadata.get("turn_id") != main_turn_id
        or not isinstance(spawn_output, dict)
        or set(spawn_output) != {"task_name"}
        or not isinstance(reviewer_path, str)
        or reviewer_path != f"/root/{task_name}"
    ):
        return reject(
            "E_COMPLETION_SPAWN_OUTPUT",
            "natural completion spawn output did not bind one reviewer path",
        )
    evidence["completed_spawn_count"] = 1
    evidence["context_isolation_requested_count"] = 1
    parent_path = reviewer_path.rsplit("/", 1)[0]
    started = [item for item in activities if item[4] == "started"]
    evidence["started_activity_count"] = started_activity_attempt_count
    if started_activity_attempt_count != 1 or len(started) != 1:
        return reject(
            "E_COMPLETION_STARTED_CARDINALITY",
            "natural completion did not expose exactly one child start",
        )
    (
        started_index,
        started_timestamp,
        started_path,
        child_thread_id,
        _,
        started_event_id,
        started_occurred_at_ms,
    ) = started[0]
    if (
        started_path != reviewer_path
        or not re.fullmatch(
            r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", child_thread_id
        )
        or not isinstance(started_timestamp, datetime)
        or started_event_id != spawn_call_id
        or not isinstance(started_occurred_at_ms, int)
        or isinstance(started_occurred_at_ms, bool)
        or abs(
            started_occurred_at_ms
            - round(started_timestamp.timestamp() * 1_000)
        )
        > 250
        or not (spawn_index < started_index < spawn_output_index)
        or not (spawn_timestamp <= started_timestamp <= spawn_output_timestamp)
    ):
        return reject(
            "E_COMPLETION_STARTED_BINDING",
            "natural completion child start was not bound to the spawn lifecycle",
        )
    if failed_activity_attempt_count or any(
        item[4].lower() in {"failed", "cancelled", "canceled", "errored", "aborted"}
        for item in activities
    ):
        return reject(
            "E_COMPLETION_CHILD_ACTIVITY_FAILED",
            "natural completion exposed a failed or cancelled child activity",
        )
    child_candidates = [
        path for path in rollout_files if path.name.endswith(f"-{child_thread_id}.jsonl")
    ]
    evidence["child_rollout_count"] = len(child_candidates)
    if len(child_candidates) != 1 or len(rollout_files) != 2:
        return reject(
            "E_COMPLETION_CHILD_ROLLOUT",
            "natural completion did not contain exactly one main and one child rollout",
        )
    child_records = records_for(child_candidates[0], "child completion")
    if child_records is None:
        return reject(
            "E_COMPLETION_CHILD_SCHEMA", "child completion rollout was not valid"
        )
    evidence["completion_chain_terminal_stage"] = "child_rollout"
    child_sessions: list[tuple[int, datetime | None, dict[str, object]]] = []
    child_turns: list[tuple[int, datetime | None, dict[str, object]]] = []
    child_terminals: list[tuple[int, datetime | None, str | None, str | None]] = []
    child_assistant_messages: list[
        tuple[int, datetime | None, str | None, str, str | None, object]
    ] = []
    child_inbound_agent_messages: list[
        tuple[int, datetime | None, tuple[str, str, str] | None]
    ] = []
    child_tool_actions: list[tuple[int, datetime | None]] = []
    child_event_messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ] = []
    child_failures = 0
    for index, record in enumerate(child_records):
        payload = record.get("payload")
        timestamp = rollout_record_timestamp(record)
        if record.get("type") == "session_meta":
            child_sessions.append(
                (index, timestamp, payload if isinstance(payload, dict) else {})
            )
        elif record.get("type") == "turn_context":
            child_turns.append(
                (index, timestamp, payload if isinstance(payload, dict) else {})
            )
        if not isinstance(payload, dict):
            continue
        if (
            record.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
        ):
            parsed_response = rollout_assistant_response_message(payload)
            child_assistant_messages.append(
                (
                    index,
                    timestamp,
                    parsed_response[1] if parsed_response is not None else None,
                    "assistant_message",
                    parsed_response[0]
                    if parsed_response is not None
                    else None,
                    payload.get("internal_chat_message_metadata_passthrough"),
                )
            )
        elif (
            record.get("type") == "response_item"
            and payload.get("type") == "agent_message"
        ):
            child_inbound_agent_messages.append(
                (index, timestamp, rollout_inbound_agent_message(payload))
            )
        elif record.get("type") == "response_item" and payload.get("type") in {
            "custom_tool_call",
            "function_call",
            "custom_tool_call_output",
            "function_call_output",
        }:
            child_tool_actions.append((index, timestamp))
        if record.get("type") == "event_msg":
            if payload.get("type") == "agent_message":
                parsed_event_message = rollout_event_agent_message(payload)
                child_event_messages.append(
                    (
                        index,
                        timestamp,
                        parsed_event_message[0]
                        if parsed_event_message is not None
                        else None,
                        parsed_event_message[1]
                        if parsed_event_message is not None
                        else None,
                    )
                )
            elif payload.get("type") == "task_complete":
                child_terminals.append(
                    (
                        index,
                        timestamp,
                        str(payload["turn_id"])
                        if isinstance(payload.get("turn_id"), str)
                        else None,
                        str(payload["last_agent_message"])
                        if isinstance(payload.get("last_agent_message"), str)
                        else None,
                    )
                )
        if (
            record.get("type") in {"turn_aborted", "turn.failed"}
            or payload.get("type")
            in {"turn_aborted", "task_failed", "agent_error", "stream_error"}
        ):
            child_failures += 1
    evidence["child_session_meta_count"] = len(child_sessions)
    evidence["child_turn_context_count"] = len(child_turns)
    evidence["child_terminal_count"] = len(child_terminals)
    evidence["child_inbound_agent_message_count"] = len(
        child_inbound_agent_messages
    )
    evidence["child_response_message_attempt_count"] = len(
        child_assistant_messages
    )
    evidence["child_preload_announcement_count"] = sum(
        isinstance(item[2], str)
        and item[2].rstrip("\n") == CANONICAL_PRELOAD_ANNOUNCEMENT
        for item in child_assistant_messages
    )
    evidence["child_boot_receipt_count"] = sum(
        isinstance(item[2], str) and item[2].startswith("COS_BOOT_RECEIPT")
        for item in child_assistant_messages
    )
    evidence["child_expected_terminal_message_count"] = sum(
        isinstance(item[2], str)
        and item[2].rstrip("\n")
        == expected_natural_review_terminal(expected_file, expected_text).rstrip("\n")
        for item in child_assistant_messages
    )
    evidence["child_pass_schema_message_count"] = sum(
        isinstance(item[2], str) and "REVIEW_VERDICT: PASS" in item[2]
        for item in child_assistant_messages
    )
    evidence["child_event_message_attempt_count"] = len(child_event_messages)
    if len(child_sessions) != 1:
        return reject(
            "E_COMPLETION_CHILD_SESSION_CARDINALITY",
            "natural completion child did not contain exactly one session_meta",
        )
    session_index, session_timestamp, session_payload = child_sessions[0]
    source = session_payload.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn_source = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    if (
        not isinstance(spawn_source, dict)
        or session_payload.get("id") != child_thread_id
        or session_payload.get("session_id") != main_thread_id
        or session_payload.get("parent_thread_id") != main_thread_id
        or "forked_from_id" in session_payload
        or session_payload.get("thread_source") != "subagent"
        or session_payload.get("agent_path") != reviewer_path
        or session_payload.get("model_provider") != expected_provider
        or session_payload.get("cli_version") != expected_cli_version
        or normalized_absolute_path(session_payload.get("cwd"))
        != normalized_absolute_path(str(fixture.resolve()))
        or spawn_source.get("parent_thread_id") != main_thread_id
        or spawn_source.get("agent_path") != reviewer_path
        or spawn_source.get("depth") != 1
        or not isinstance(session_payload.get("agent_nickname"), str)
        or not session_payload.get("agent_nickname")
        or session_payload.get("agent_nickname")
        != spawn_source.get("agent_nickname")
        or not isinstance(session_timestamp, datetime)
        or session_timestamp < spawn_timestamp
    ):
        return reject(
            "E_COMPLETION_CHILD_SESSION_IDENTITY",
            "natural completion child session identity was not bound",
        )
    if len(child_turns) != 1:
        return reject(
            "E_COMPLETION_CHILD_TURN_CARDINALITY",
            "natural completion child did not contain exactly one turn_context",
        )
    turn_index, turn_timestamp, turn_payload = child_turns[0]
    child_turn_id = turn_payload.get("turn_id")
    if (
        turn_index <= session_index
        or not isinstance(child_turn_id, str)
        or not EXECUTION_ID_RE.fullmatch(child_turn_id)
        or turn_payload.get("model") != expected_model
        or turn_payload.get("effort") != expected_reasoning_effort
        or normalized_absolute_path(turn_payload.get("cwd"))
        != normalized_absolute_path(str(fixture.resolve()))
        or not isinstance(turn_timestamp, datetime)
        or turn_timestamp < session_timestamp
    ):
        return reject(
            "E_COMPLETION_CHILD_TURN_IDENTITY",
            "natural completion child turn identity was not bound",
        )
    if len(child_inbound_agent_messages) != 1:
        return reject(
            "E_COMPLETION_CHILD_INBOUND_CARDINALITY",
            "natural completion child did not contain one parent task transport",
        )
    inbound_index, inbound_timestamp, inbound = child_inbound_agent_messages[0]
    child_action_records = (
        [(item[0], item[1]) for item in child_assistant_messages]
        + child_tool_actions
        + [(item[0], item[1]) for item in child_event_messages]
        + [(item[0], item[1]) for item in child_terminals]
    )
    first_child_output_index = min(
        (item[0] for item in child_action_records), default=len(child_records)
    )
    child_action_timestamps = [
        item[1] for item in child_action_records if isinstance(item[1], datetime)
    ]
    if (
        inbound is None
        or inbound != (parent_path, reviewer_path, child_turn_id)
        or inbound_index <= turn_index
        or inbound_index >= first_child_output_index
        or not child_transport_action_surface_valid(
            child_records, turn_index, inbound_index
        )
        or not isinstance(inbound_timestamp, datetime)
        or inbound_timestamp < turn_timestamp
        or len(child_action_timestamps) != len(child_action_records)
        or (
            child_action_timestamps
            and inbound_timestamp >= min(child_action_timestamps)
        )
    ):
        return reject(
            "E_COMPLETION_CHILD_INBOUND_CONTRACT",
            "natural completion child parent task transport was not bound and first",
        )
    evidence["child_inbound_agent_message_contract_verified"] = True
    if child_failures or len(child_terminals) != 1:
        return reject(
            "E_COMPLETION_CHILD_TERMINAL_CARDINALITY",
            "natural completion child did not have one successful terminal",
        )
    child_terminal_index, child_terminal_timestamp, child_terminal_turn, child_message = (
        child_terminals[0]
    )
    if (
        child_terminal_index != len(child_records) - 1
        or child_terminal_turn != child_turn_id
        or not isinstance(child_terminal_timestamp, datetime)
        or child_terminal_timestamp < turn_timestamp
        or child_terminal_timestamp < spawn_output_timestamp
        or child_terminal_timestamp < started_timestamp
        or child_terminal_timestamp <= artifact_changed_at
        or not isinstance(child_message, str)
        or not natural_review_terminal_is_substantive(
            child_message, expected_file, expected_text
        )
    ):
        return reject(
            "E_COMPLETION_CHILD_TERMINAL",
            "natural completion child terminal was not post-change and final",
        )
    if any(
        item[3] != "assistant_message"
        or item[5] != {"turn_id": child_turn_id}
        for item in child_assistant_messages
    ):
        return reject(
            "E_COMPLETION_CHILD_RESPONSE_TURN_BINDING",
            "natural completion child response was not bound to the current turn",
        )
    evidence["child_response_turn_binding_verified"] = True
    exact_child_messages = [
        item
        for item in child_assistant_messages
        if isinstance(item[2], str)
        and item[2].rstrip("\n") == child_message.rstrip("\n")
        and item[3] == "assistant_message"
        and item[4] == "final_answer"
    ]
    protected_child_claim = re.compile(
        r"(?:NATURAL_REVIEW_|REVIEW_VERDICT|NO_BLOCKING_FINDINGS|"
        r"\bFINDINGS?\s*:|BLOCKING_FINDINGS|CRITICAL_FINDING|"
        r"MAIN_REVIEW_ADOPTION|COLD_CONTEXT_ISOLATION)",
        flags=re.IGNORECASE,
    )
    fixed_child_progress_messages = [
        item
        for item in child_assistant_messages
        if item not in exact_child_messages
        and item[3] == "assistant_message"
        and item[4] == "commentary"
        and isinstance(item[2], str)
        and item[2].rstrip("\n") == NATURAL_REVIEW_PROGRESS
        and turn_index < item[0] < child_terminal_index
    ]
    evidence["child_progress_message_count"] = len(fixed_child_progress_messages)
    event_progress_messages = [
        item
        for item in child_event_messages
        if item[2] == "commentary"
        and isinstance(item[3], str)
        and item[3].rstrip("\n") == NATURAL_REVIEW_PROGRESS
    ]
    evidence["child_event_progress_message_count"] = len(
        event_progress_messages
    )
    if not child_event_message_contract_valid(
        child_event_messages,
        child_message,
        NATURAL_REVIEW_PROGRESS,
        turn_index=turn_index,
        commentary_before_index=child_terminal_index,
        final_after_index=turn_index,
        terminal_index=child_terminal_index,
        final_after_timestamp=max(
            artifact_changed_at, spawn_output_timestamp, started_timestamp
        ),
        terminal_timestamp=child_terminal_timestamp,
    ):
        return reject(
            "E_COMPLETION_CHILD_EVENT_MESSAGE_CONTRACT",
            "natural completion child emitted a non-canonical raw event message",
        )
    evidence["child_event_message_contract_verified"] = True
    invalid_child_messages = [
        item
        for item in child_assistant_messages
        if item not in exact_child_messages
        and item not in fixed_child_progress_messages
    ]
    if (
        len(exact_child_messages) != 1
        or len(fixed_child_progress_messages) > 1
        or (
            exact_child_messages[0][0]
            != max(item[0] for item in child_assistant_messages)
            or exact_child_messages[0][0] >= child_terminal_index
            or not isinstance(exact_child_messages[0][1], datetime)
            or exact_child_messages[0][1]
            < max(
                artifact_changed_at,
                spawn_output_timestamp,
                started_timestamp,
            )
            or exact_child_messages[0][1] > child_terminal_timestamp
        )
    ):
        return reject(
            "E_COMPLETION_CHILD_CONTRADICTION",
            "natural completion child emitted intermediate or contradictory prose",
        )
    if invalid_child_messages:
        contradiction = any(
            isinstance(item[2], str)
            and (
                protected_child_claim.search(item[2]) is not None
                or claims_completion_contradiction(item[2])
            )
            for item in invalid_child_messages
        )
        return reject(
            "E_COMPLETION_CHILD_CONTRADICTION"
            if contradiction
            else "E_COMPLETION_CHILD_MESSAGE_CONTRACT",
            "natural completion child emitted a non-canonical assistant message",
        )
    evidence["child_terminal_after_artifact_verified"] = True
    evidence["completion_chain_terminal_stage"] = "child_terminal"
    reviewer_delivery_attempts = [
        item
        for item in delivery_attempts
        if item[2] == reviewer_path or item[3] == parent_path
    ]
    evidence["reviewer_delivery_attempt_count"] = len(reviewer_delivery_attempts)
    bound_deliveries = [
        item
        for item in reviewer_delivery_attempts
        if item[2] == reviewer_path
        and item[3] == parent_path
        and isinstance(item[4], str)
        and item[5] == {"turn_id": main_turn_id}
        and spawn_output_index < item[0] < main_terminal_index
        and isinstance(item[1], datetime)
        and child_terminal_timestamp <= item[1] <= main_terminal_timestamp
        and spawn_output_timestamp <= item[1]
        and delivered_review_message_matches(
            item[4], reviewer_path, parent_path, child_message
        )
    ]
    evidence["bound_delivery_count"] = len(bound_deliveries)
    if (
        len(delivery_attempts) != 1
        or len(reviewer_delivery_attempts) != 1
        or len(bound_deliveries) != 1
    ):
        return reject(
            "E_COMPLETION_DELIVERY_BINDING",
            "natural completion child terminal was not delivered exactly once before main terminal",
        )
    evidence["delivery_after_child_terminal_verified"] = True
    evidence["delivery_before_main_terminal_verified"] = True
    evidence["delivery_parent_turn_verified"] = True
    evidence["completion_chain_terminal_stage"] = "bound_delivery"
    delivered_index = bound_deliveries[0][0]
    forbidden_claim = re.compile(
        r"(?:MAIN_REVIEW_ADOPTION|COLD_CONTEXT_ISOLATION|NATURAL_REVIEW_|"
        r"REVIEW_VERDICT|reviewer-owned\s+read|\bADOPTION\s*:|"
        r"\bFINDINGS?\s*:|\bISOLATION\s*:)",
        flags=re.IGNORECASE,
    )
    exact_main_final_messages = [
        item
        for item in main_assistant_messages
        if isinstance(item[2], str)
        and item[2].rstrip("\n") == expected_main_final_text.rstrip("\n")
    ]
    if (
        len(exact_main_final_messages) != 1
        or (
            exact_main_final_messages[0][0] <= delivered_index
            or exact_main_final_messages[0][0] >= main_terminal_index
            or exact_main_final_messages[0][0]
            != max(item[0] for item in main_assistant_messages)
            or not isinstance(exact_main_final_messages[0][1], datetime)
            or exact_main_final_messages[0][1] < bound_deliveries[0][1]
            or exact_main_final_messages[0][1] > main_terminal_timestamp
        )
    ):
        return reject(
            "E_COMPLETION_MAIN_FINAL_CARDINALITY",
            "natural completion main rollout emitted duplicate or misplaced final messages",
        )
    contradictory_main_messages = [
        item
        for item in main_assistant_messages
        if item not in exact_main_final_messages
        and isinstance(item[2], str)
        and (
            forbidden_claim.search(item[2]) is not None
            or claims_external_reviewer_result(item[2])
            or claims_completion_contradiction(item[2])
        )
    ]
    if contradictory_main_messages:
        return reject(
            "E_COMPLETION_MAIN_CONTRADICTION",
            "natural completion main rollout emitted premature or contradictory review claims",
        )
    if not main_assistant_message_contract_valid(
        [(item[0], item[1], item[2]) for item in main_assistant_messages],
        expected_main_final_text,
        expected_boot_receipt,
        require_final=True,
    ):
        return reject(
            "E_COMPLETION_MAIN_MESSAGE_CONTRACT",
            "natural completion main rollout emitted non-canonical progress text",
        )
    if not assistant_response_phase_contract_valid(
        [
            (item[0], item[1], item[2], item[3])
            for item in main_assistant_messages
        ],
        expected_main_final_text,
    ):
        return reject(
            "E_COMPLETION_MAIN_RESPONSE_PHASE_CONTRACT",
            "natural completion main response text used a non-canonical phase",
        )
    if not main_event_message_contract_valid(
        main_event_messages,
        expected_main_final_text,
        expected_boot_receipt,
        final_after_index=delivered_index,
        terminal_index=main_terminal_index,
        final_after_timestamp=bound_deliveries[0][1],
        terminal_timestamp=main_terminal_timestamp,
    ):
        return reject(
            "E_COMPLETION_MAIN_EVENT_MESSAGE_CONTRACT",
            "natural completion main emitted a non-canonical raw event message",
        )
    evidence["main_event_message_contract_verified"] = True
    expected_natural_final = "\n".join(
        (
            child_message.rstrip("\n"),
            MAIN_REVIEW_ADOPTION_ACCEPTED,
            COLD_CONTEXT_ISOLATION_UNVERIFIED,
            REVIEWER_OWNED_READ_UNVERIFIED,
        )
    )
    if expected_main_final_text.rstrip("\n") != expected_natural_final:
        return reject(
            "E_COMPLETION_FINAL_ADOPTION",
            "main final did not copy, adopt, and scope the delivered reviewer result",
        )
    evidence["reviewer_result_copied_to_final"] = True
    evidence["main_adoption_verified"] = True
    evidence["isolation_disclosure_verified"] = True
    evidence["reviewer_owned_read_disclosure_verified"] = True
    evidence["completion_chain_count"] = 1
    evidence["completion_chain_terminal_stage"] = "complete"
    completion_record = {
        "prompt_visibility": evidence["review_prompt_visibility"],
        "reviewer_message_sha256": sha256_bytes(child_message.encode()),
        "reviewer_path_sha256": sha256_bytes(reviewer_path.encode()),
        "child_thread_sha256": sha256_bytes(child_thread_id.encode()),
        "adoption": MAIN_REVIEW_ADOPTION_ACCEPTED,
        "isolation": COLD_CONTEXT_ISOLATION_UNVERIFIED,
        "reviewer_owned_read": REVIEWER_OWNED_READ_UNVERIFIED,
    }
    evidence["completion_record_sha256"] = sha256_bytes(
        json.dumps(
            completion_record, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    evidence["rejection_codes"] = []
    evidence["schema_failures"] = []
    return evidence


def strict_code_mode_exec_arguments(value: str) -> dict[str, object] | None:
    """Parse the one inert wrapper that forwards only exec_command stdout."""
    if (
        len(value) > 32_768
        or value.count("tools.exec_command") != 1
        or value.count("tools.") != 1
        or value.count("await") != 1
    ):
        return None
    object_pattern = r"(?P<object>\{[^{}]*\})"
    wrapper = re.compile(
        r"\A\s*const\s+(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*await\s+"
        r"tools\.exec_command\("
        + object_pattern
        + r"\)\s*;\s*text\(\s*(?P=var)\.output\s*\)\s*;?\s*\Z",
        flags=re.DOTALL,
    )
    match = wrapper.fullmatch(value)
    if match is None:
        return None
    object_text = match.group("object")
    allowed_keys = {
        "cmd",
        "workdir",
        "yield_time_ms",
        "max_output_tokens",
        "login",
        "tty",
        "shell",
    }
    string_keys = {"cmd", "workdir", "shell"}
    integer_keys = {"yield_time_ms", "max_output_tokens"}
    boolean_keys = {"login", "tty"}
    result: dict[str, object] = {}
    position = 1
    end = len(object_text) - 1
    json_string = re.compile(r'"(?:\\.|[^"\\])*"')
    identifier = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
    integer = re.compile(r"[0-9]+")
    while True:
        while position < end and object_text[position].isspace():
            position += 1
        if position == end:
            break
        key_match = json_string.match(object_text, position)
        if key_match is not None:
            try:
                key = json.loads(key_match.group(0))
            except json.JSONDecodeError:
                return None
            position = key_match.end()
        else:
            key_match = identifier.match(object_text, position)
            if key_match is None:
                return None
            key = key_match.group(0)
            position = key_match.end()
        if not isinstance(key, str) or key not in allowed_keys or key in result:
            return None
        while position < end and object_text[position].isspace():
            position += 1
        if position >= end or object_text[position] != ":":
            return None
        position += 1
        while position < end and object_text[position].isspace():
            position += 1
        if key in string_keys:
            value_match = json_string.match(object_text, position)
            if value_match is None:
                return None
            try:
                parsed_value = json.loads(value_match.group(0))
            except json.JSONDecodeError:
                return None
            position = value_match.end()
        elif key in integer_keys:
            value_match = integer.match(object_text, position)
            if value_match is None:
                return None
            parsed_value = int(value_match.group(0))
            position = value_match.end()
        else:
            if object_text.startswith("true", position):
                parsed_value = True
                position += 4
            elif object_text.startswith("false", position):
                parsed_value = False
                position += 5
            else:
                return None
        result[key] = parsed_value
        while position < end and object_text[position].isspace():
            position += 1
        if position == end:
            break
        if object_text[position] != ",":
            return None
        position += 1
    if not {"cmd", "workdir"}.issubset(result):
        return None
    return result


def strict_artifact_read_arguments(
    tool_name: str,
    tool_input: object,
    fixture: Path,
    expected_file: str,
    expected_text: str,
    evidence_marker: str,
) -> dict[str, object] | None:
    """Accept one exact /bin/cat read of the expected relative artifact."""
    arguments: dict[str, object] | None = None
    serialized_input = (
        tool_input
        if isinstance(tool_input, str)
        else json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    )
    if evidence_marker in serialized_input or expected_text in serialized_input:
        return None
    if tool_name == "exec" and isinstance(tool_input, str):
        arguments = strict_code_mode_exec_arguments(tool_input)
    elif tool_name == "exec_command":
        arguments = parsed_json_object(tool_input)
    if arguments is None:
        return None
    allowed_keys = {
        "cmd",
        "workdir",
        "yield_time_ms",
        "max_output_tokens",
    }
    if set(arguments) - allowed_keys:
        return None
    for key in ("yield_time_ms", "max_output_tokens"):
        value = arguments.get(key)
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            or value > 1_000_000
        ):
            return None
    command = arguments.get("cmd")
    workdir = arguments.get("workdir")
    if not isinstance(command, str) or not isinstance(workdir, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if tokens != ["/bin/cat", expected_file]:
        return None
    expected_relative = PurePosixPath(expected_file)
    if (
        expected_relative.is_absolute()
        or not expected_relative.parts
        or ".." in expected_relative.parts
    ):
        return None
    if normalized_absolute_path(workdir) != normalized_absolute_path(str(fixture.resolve())):
        return None
    return {"cmd": command, "workdir": workdir}


def strict_guard_skill_read_arguments(
    tool_name: str,
    tool_input: object,
    fixture: Path,
    expected_skill_path: str | None,
) -> dict[str, object] | None:
    """Accept one exact canonical Skill guard read before worker execution."""
    if not isinstance(expected_skill_path, str) or not expected_skill_path:
        return None
    arguments: dict[str, object] | None = None
    if tool_name == "exec" and isinstance(tool_input, str):
        arguments = strict_code_mode_exec_arguments(tool_input)
    elif tool_name == "exec_command":
        arguments = parsed_json_object(tool_input)
    if arguments is None or set(arguments) - {
        "cmd",
        "workdir",
        "yield_time_ms",
        "max_output_tokens",
    }:
        return None
    for key in ("yield_time_ms", "max_output_tokens"):
        value = arguments.get(key)
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            or value > 1_000_000
        ):
            return None
    command = arguments.get("cmd")
    workdir = arguments.get("workdir")
    if not isinstance(command, str) or not isinstance(workdir, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if tokens != ["/bin/cat", expected_skill_path]:
        return None
    if normalized_absolute_path(workdir) != normalized_absolute_path(
        str(fixture.resolve())
    ):
        return None
    return {"cmd": command, "workdir": workdir}


def tool_output_contains_exact_text(output: object, expected_text: str | None) -> bool:
    """Require one raw output field to equal the expected text exactly."""
    if not isinstance(expected_text, str) or not expected_text:
        return False
    values: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                values.append(value)
            else:
                if parsed == value:
                    values.append(value)
                else:
                    collect(parsed)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    values.append(str(item["text"]))
        elif isinstance(value, dict):
            for key in ("output", "stdout", "text"):
                if isinstance(value.get(key), str):
                    values.append(str(value[key]))

    collect(output)
    return sum(value.rstrip("\n") == expected_text.rstrip("\n") for value in values) == 1


def tool_output_contains_exact_artifact(
    output: object,
    expected_artifact_text: str,
    evidence_marker: str,
    expected_text: str,
) -> bool:
    """Accept only the canonical text-block encoding of one exact raw artifact."""
    del evidence_marker, expected_text
    if not isinstance(output, list) or not output:
        return False
    if not all(
        isinstance(item, dict)
        and set(item) == {"type", "text"}
        and item.get("type") == "input_text"
        and isinstance(item.get("text"), str)
        and item.get("text") != ""
        for item in output
    ):
        return False
    canonical_text_chunks = [str(item["text"]) for item in output]
    if canonical_text_chunks and canonical_direct_read_status_block(
        canonical_text_chunks[0]
    ):
        canonical_text_chunks = canonical_text_chunks[1:]
    return "".join(canonical_text_chunks) == expected_artifact_text


def canonical_direct_read_status_block(text: str) -> bool:
    """Recognize the exact content-free status prefix emitted by the exec surface."""
    return text == "Script completed\n" or bool(
        re.fullmatch(
            r"Script completed\nWall time [0-9]+(?:\.[0-9]+)? seconds\n",
            text,
        )
    )


def direct_read_output_shape(output: object) -> dict[str, object]:
    """Return a content-free receipt witness for a strict direct-read output."""
    if isinstance(output, list):
        blocks: list[dict[str, object]] = []
        for item in output:
            if not isinstance(item, dict):
                blocks.append({"kind": "non-object"})
                continue
            raw_type = item.get("type")
            type_class = (
                raw_type
                if raw_type in {"input_text", "output_text", "text"}
                else "other"
            )
            text = item.get("text")
            blocks.append(
                {
                    "kind": "object",
                    "keys_exact_type_text": set(item) == {"type", "text"},
                    "type": type_class,
                    "text_is_string": isinstance(text, str),
                    "text_empty": text == "" if isinstance(text, str) else False,
                    "canonical_status_block": canonical_direct_read_status_block(text)
                    if isinstance(text, str)
                    else False,
                    "text_utf8_bytes": len(text.encode("utf-8"))
                    if isinstance(text, str)
                    else None,
                }
            )
        return {"kind": "list", "block_count": len(output), "blocks": blocks}
    if isinstance(output, str):
        return {"kind": "string", "utf8_bytes": len(output.encode("utf-8"))}
    if isinstance(output, dict):
        return {
            "kind": "object",
            "field_count": len(output),
            "has_output_string": isinstance(output.get("output"), str),
            "has_stdout_string": isinstance(output.get("stdout"), str),
            "has_text_string": isinstance(output.get("text"), str),
            "has_error_field": "error" in output,
        }
    return {"kind": "other"}


def rollout_review_evidence(
    rollout_source: Path | dict[PurePosixPath, bytes],
    main_thread_id: str | None,
    fixture: Path,
    expected_file: str,
    expected_text: str,
    expected_artifact_text: str,
    expected_main_final_text: str,
    evidence_marker: str,
    expected_boot_receipt: str,
    artifact_mtime_ns: int | None,
    artifact_ctime_ns: int | None,
    expected_model: str | None,
    expected_provider: str,
    expected_reasoning_effort: str | None,
    expected_cli_version: str,
    auth_secrets: set[str],
    expected_guard_skill_path: str | None = None,
    expected_guard_skill_text: str | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Bind one reviewer lifecycle, identity, exact artifact read, and terminal."""
    failures: list[str] = []
    evidence: dict[str, object] = {
        "source": "codex_rollout_main_and_subagent",
        "main_spawn_call_count": 0,
        "completed_spawn_count": 0,
        "failed_spawn_attempt_count": 0,
        "spawn_retry_count": 0,
        "spawn_retry_contract_verified": False,
        "main_wait_call_count": 0,
        "completed_wait_count": 0,
        "wait_process_attempt_count": 0,
        "wait_process_output_pair_count": 0,
        "main_subagent_activity_count": 0,
        "main_subagent_activity_attempt_count": 0,
        "main_terminal_verified_count": 0,
        "main_task_complete_event_count": 0,
        "premature_reviewer_claim_count": 0,
        "main_contradictory_review_claim_count": 0,
        "main_exact_final_message_count": 0,
        "main_response_message_attempt_count": 0,
        "main_response_turn_binding_verified": False,
        "main_event_message_attempt_count": 0,
        "main_event_message_contract_verified": False,
        "main_agent_delivery_attempt_count": 0,
        "reviewer_message_call_count": 0,
        "reviewer_delivery_attempt_count": 0,
        "candidate_bound_delivery_count": 0,
        "review_prompt_contract_match_count": 0,
        "encrypted_spawn_prompt_count": 0,
        "opaque_spawn_prompt_count": 0,
        "review_prompt_visibility": None,
        "review_prompt_acceptance_mode": None,
        "review_prompt_content_verified": False,
        "review_marker_nonforwarding_verified": False,
        "review_prompt_contract_checks": {},
        "matching_reviewer_activity_count": 0,
        "candidate_child_thread_count": 0,
        "started_activity_order_match_count": 0,
        "started_timestamp_tolerance_ms": 250,
        "matching_child_rollout_count": 0,
        "wait_bound_to_single_child_count": 0,
        "child_rollout_count": 0,
        "child_session_binding_count": 0,
        "child_session_meta_event_count": 0,
        "child_turn_context_record_count": 0,
        "child_turn_context_event_count": 0,
        "child_distinct_turn_id_count": 0,
        "child_inbound_agent_message_count": 0,
        "child_inbound_agent_message_contract_verified_count": 0,
        "child_tool_call_count": 0,
        "child_tool_output_count": 0,
        "child_identity_verified_count": 0,
        "child_terminal_verified_count": 0,
        "child_task_complete_event_count": 0,
        "child_assistant_message_attempt_count": 0,
        "child_preload_announcement_count": 0,
        "child_boot_receipt_count": 0,
        "child_expected_terminal_message_count": 0,
        "child_pass_schema_message_count": 0,
        "child_response_turn_binding_verified_count": 0,
        "child_progress_message_count": 0,
        "child_event_progress_message_count": 0,
        "child_event_message_attempt_count": 0,
        "child_event_message_contract_verified": False,
        "review_result_delivery_verified_count": 0,
        "delivery_before_main_terminal_verified_count": 0,
        "delivery_parent_turn_verified_count": 0,
        "direct_exact_read_verified_count": 0,
        "guard_skill_read_verified_count": 0,
        "post_change_read_verified_count": 0,
        "artifact_change_time_basis": "max_mtime_ctime",
        "artifact_read_timestamp_tolerance_ms": 0,
        "rc_review_chain_count": 0,
        "reviewer_owned_read_verified_count": 0,
        "context_isolation_requested_count": 0,
        "context_isolation_verified_count": 0,
        "auth_exact_value_leak_detected": False,
        "review_record_sha256": None,
        "review_truth_verified": False,
        "review_process_compliant": False,
        "review_sync_method": None,
        "review_chain_terminal_stage": "spawn_not_bound",
        "review_chain_rejection_codes": [],
        "duplicate_child_lifecycle_detected": False,
        "child_session_checks": {"observed": False},
        "child_turn_checks": {"observed": False},
        "child_direct_read_checks": {"observed": False},
        "wait_call_checks": [],
        "main_terminal_checks": {"observed": False},
        "schema_failures": failures,
    }
    rejection_codes: list[str] = evidence["review_chain_rejection_codes"]  # type: ignore[assignment]
    stage_order = {
        "spawn_not_bound": 0,
        "child_rollout": 1,
        "session_binding": 2,
        "session_identity": 3,
        "turn_identity": 4,
        "tool_cardinality": 5,
        "terminal": 6,
        "direct_read": 7,
        "bound_delivery": 8,
        "complete": 9,
    }

    def reject(code: str) -> None:
        if code not in rejection_codes:
            rejection_codes.append(code)

    def advance_stage(stage: str) -> None:
        current = str(evidence["review_chain_terminal_stage"])
        if stage_order[stage] > stage_order[current]:
            evidence["review_chain_terminal_stage"] = stage
    completed_reviews: dict[str, dict[str, object]] = {}
    if not isinstance(main_thread_id, str) or not re.fullmatch(
        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", main_thread_id
    ):
        failures.append("review rollout binding lacked a valid main thread id")
        return evidence, completed_reviews
    if (
        not expected_file
        or not expected_text
        or not evidence_marker
        or not expected_main_final_text
        or not expected_boot_receipt
    ):
        failures.append("review rollout binding lacked the expected artifact contract")
        return evidence, completed_reviews
    if (
        not expected_artifact_text
        or evidence_marker not in expected_artifact_text
        or expected_text not in expected_artifact_text
        or artifact_mtime_ns is None
        or artifact_mtime_ns < 0
        or artifact_ctime_ns is None
        or artifact_ctime_ns < 0
    ):
        failures.append("review rollout binding lacked exact post-change artifact evidence")
        return evidence, completed_reviews
    if (
        not isinstance(expected_model, str)
        or not EXECUTION_ID_RE.fullmatch(expected_model)
        or expected_provider != LOCKED_MODEL_PROVIDER
        or not isinstance(expected_reasoning_effort, str)
        or not REASONING_EFFORT_RE.fullmatch(expected_reasoning_effort)
        or not CLI_VERSION_VALUE_RE.fullmatch(expected_cli_version)
    ):
        failures.append("review rollout binding lacked the expected child identity")
        return evidence, completed_reviews

    rollout_snapshot, tree_failures = resolved_rollout_snapshot(rollout_source)
    rollout_files = sorted(rollout_snapshot)
    if tree_failures:
        failures.extend(tree_failures)
        return evidence, completed_reviews
    main_candidates = [
        path
        for path in rollout_files
        if path.name.endswith(f"-{main_thread_id}.jsonl")
    ]
    if len(main_candidates) != 1:
        failures.append("review main thread did not map to exactly one rollout")
        return evidence, completed_reviews

    def read_records(
        path: PurePosixPath, label: str
    ) -> list[dict[str, object]] | None:
        try:
            raw = rollout_snapshot[path]
            text = raw.decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            failures.append(f"{label} rollout was not bounded UTF-8 JSONL")
            return None
        _, auth_leak = redact_exact_auth_values(text, auth_secrets)
        if auth_leak:
            evidence["auth_exact_value_leak_detected"] = True
            failures.append(f"{label} rollout contained an exact auth value")
            return None
        records: list[dict[str, object]] = []
        for line in split_jsonl_records(text):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                failures.append(f"{label} rollout contained malformed JSONL")
                return None
            if not isinstance(record, dict):
                failures.append(f"{label} rollout contained a non-object record")
                return None
            records.append(record)
        return records

    main_records = read_records(main_candidates[0], "main review")
    if main_records is None:
        return evidence, completed_reviews
    spawn_calls: list[dict[str, object]] = []
    function_outputs: dict[str, tuple[int, datetime | None, object]] = {}
    function_output_turn_metadata: dict[str, object] = {}
    wait_calls: list[dict[str, object]] = []
    activities: list[
        tuple[int, datetime | None, str, str, str, str | None, object]
    ] = []
    delivery_attempts: list[
        tuple[
            int,
            datetime | None,
            str | None,
            str | None,
            str | None,
            object,
        ]
    ] = []
    main_assistant_messages: list[
        tuple[int, datetime | None, str | None, str | None, object]
    ] = []
    main_event_messages: list[
        tuple[int, datetime | None, str | None, str | None]
    ] = []
    main_task_completions: list[
        tuple[int, datetime | None, str | None, str]
    ] = []
    main_turn_ids: list[str] = []
    main_call_ids: set[str] = set()
    main_output_ids: set[str] = set()
    duplicate_main_lifecycle_id = False
    main_task_complete_event_count = 0
    main_subagent_activity_attempt_count = 0
    malformed_subagent_activity = False
    marker_variants = {
        evidence_marker,
        evidence_marker.encode().hex(),
        base64.b64encode(evidence_marker.encode()).decode(),
        base64.urlsafe_b64encode(evidence_marker.encode()).decode(),
    }
    marker_forwarded = False
    main_delivery_schema_failure = False
    reviewer_message_calls: list[tuple[int, datetime | None, str, object]] = []
    for index, record in enumerate(main_records):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        timestamp = rollout_record_timestamp(record)
        if record.get("type") == "turn_context":
            turn_id = payload.get("turn_id")
            if isinstance(turn_id, str) and EXECUTION_ID_RE.fullmatch(turn_id):
                main_turn_ids.append(turn_id)
        if record.get("type") == "response_item":
            payload_type = payload.get("type")
            call_id = payload.get("call_id")
            if payload_type == "message" and payload.get("role") == "assistant":
                parsed_response = rollout_assistant_response_message(payload)
                main_assistant_messages.append(
                    (
                        index,
                        timestamp,
                        parsed_response[1]
                        if parsed_response is not None
                        else None,
                        parsed_response[0]
                        if parsed_response is not None
                        else None,
                        payload.get("internal_chat_message_metadata_passthrough"),
                    )
                )
            if payload_type == "agent_message":
                content = rollout_delivery_content(payload)
                if content is None:
                    main_delivery_schema_failure = True
                delivery_attempts.append(
                    (
                        index,
                        timestamp,
                        str(payload["author"])
                        if isinstance(payload.get("author"), str)
                        else None,
                        str(payload["recipient"])
                        if isinstance(payload.get("recipient"), str)
                        else None,
                        content,
                        payload.get("internal_chat_message_metadata_passthrough"),
                    )
                )
            if (
                payload_type == "function_call"
                and payload.get("name") in {"send_message", "followup_task"}
            ):
                reviewer_message_calls.append(
                    (
                        index,
                        timestamp,
                        str(payload.get("name")),
                        payload.get("arguments"),
                    )
                )
                if isinstance(payload.get("arguments"), str) and any(
                    variant and variant in str(payload["arguments"])
                    for variant in marker_variants
                ):
                    marker_forwarded = True
            if (
                payload_type == "function_call"
                and payload.get("name") == "spawn_agent"
                and isinstance(call_id, str)
                and call_id
            ):
                if call_id in main_call_ids:
                    duplicate_main_lifecycle_id = True
                main_call_ids.add(call_id)
                arguments = parsed_json_object(payload.get("arguments"))
                spawn_calls.append(
                    {
                        "index": index,
                        "timestamp": timestamp,
                        "call_id": call_id,
                        "arguments": arguments,
                        "namespace": payload.get("namespace"),
                        "turn_metadata": payload.get(
                            "internal_chat_message_metadata_passthrough"
                        ),
                    }
                )
            elif (
                payload_type == "function_call"
                and payload.get("name") == "wait_agent"
                and isinstance(call_id, str)
                and call_id
            ):
                if call_id in main_call_ids:
                    duplicate_main_lifecycle_id = True
                main_call_ids.add(call_id)
                wait_calls.append(
                    {
                        "index": index,
                        "timestamp": timestamp,
                        "call_id": call_id,
                        "arguments": parsed_json_object(payload.get("arguments")),
                        "namespace": payload.get("namespace"),
                        "turn_metadata": payload.get(
                            "internal_chat_message_metadata_passthrough"
                        ),
                    }
                )
            elif (
                payload_type == "function_call_output"
                and isinstance(call_id, str)
                and call_id
            ):
                if call_id in main_output_ids:
                    duplicate_main_lifecycle_id = True
                main_output_ids.add(call_id)
                function_outputs[call_id] = (index, timestamp, payload.get("output"))
                function_output_turn_metadata[call_id] = payload.get(
                    "internal_chat_message_metadata_passthrough"
                )
        elif record.get("type") == "event_msg":
            if payload.get("type") == "agent_message":
                parsed_event_message = rollout_event_agent_message(payload)
                main_event_messages.append(
                    (
                        index,
                        timestamp,
                        parsed_event_message[0]
                        if parsed_event_message is not None
                        else None,
                        parsed_event_message[1]
                        if parsed_event_message is not None
                        else None,
                    )
                )
            if payload.get("type") == "task_complete":
                main_task_complete_event_count += 1
            if payload.get("type") == "sub_agent_activity":
                main_subagent_activity_attempt_count += 1
                if (
                    isinstance(payload.get("agent_path"), str)
                    and isinstance(payload.get("agent_thread_id"), str)
                    and isinstance(payload.get("kind"), str)
                ):
                    activities.append(
                        (
                            index,
                            timestamp,
                            str(payload["agent_path"]),
                            str(payload["agent_thread_id"]),
                            str(payload["kind"]),
                            str(payload["event_id"])
                            if isinstance(payload.get("event_id"), str)
                            else None,
                            payload.get("occurred_at_ms"),
                        )
                    )
                else:
                    malformed_subagent_activity = True
            elif (
                payload.get("type") == "task_complete"
                and isinstance(payload.get("last_agent_message"), str)
            ):
                main_task_completions.append(
                    (
                        index,
                        timestamp,
                        str(payload["turn_id"])
                        if isinstance(payload.get("turn_id"), str)
                        else None,
                        str(payload["last_agent_message"]),
                    )
                )
    if duplicate_main_lifecycle_id:
        failures.append("main review rollout reused a collaboration lifecycle id")
        evidence["schema_failures"] = sorted(set(failures))
        return evidence, completed_reviews
    evidence["main_response_message_attempt_count"] = len(
        main_assistant_messages
    )
    evidence["main_event_message_attempt_count"] = len(main_event_messages)
    evidence["main_agent_delivery_attempt_count"] = len(delivery_attempts)
    evidence["reviewer_message_call_count"] = len(reviewer_message_calls)
    if reviewer_message_calls:
        reject("E_REVIEW_REVIEWER_MESSAGE_MUTATION")
        failures.append("main review rollout attempted to mutate a spawned reviewer packet")
        evidence["schema_failures"] = sorted(set(failures))
        evidence["review_chain_rejection_codes"] = sorted(rejection_codes)
        return evidence, completed_reviews
    if main_delivery_schema_failure:
        reject("E_REVIEW_DELIVERY_SCHEMA")
        failures.append("main review rollout contained a malformed agent delivery")
        evidence["schema_failures"] = sorted(set(failures))
        return evidence, completed_reviews
    if marker_forwarded:
        failures.append("main review rollout forwarded the hidden marker to a reviewer")
        evidence["schema_failures"] = sorted(set(failures))
        return evidence, completed_reviews
    evidence["main_spawn_call_count"] = len(spawn_calls)
    evidence["main_subagent_activity_count"] = len(activities)
    evidence["main_subagent_activity_attempt_count"] = (
        main_subagent_activity_attempt_count
    )
    evidence["main_task_complete_event_count"] = main_task_complete_event_count
    if malformed_subagent_activity:
        reject("E_REVIEW_ACTIVITY_SCHEMA")
        failures.append("main review rollout contained malformed subagent activity")
        evidence["schema_failures"] = sorted(set(failures))
        evidence["review_chain_rejection_codes"] = sorted(rejection_codes)
        return evidence, completed_reviews
    if len(main_turn_ids) != 1:
        failures.append("main review rollout did not expose exactly one turn id")
        evidence["schema_failures"] = sorted(set(failures))
        return evidence, completed_reviews
    main_turn_id = main_turn_ids[0]
    if any(
        item[4] != {"turn_id": main_turn_id}
        for item in main_assistant_messages
    ):
        reject("E_REVIEW_MAIN_RESPONSE_TURN_BINDING")
        failures.append("main review response was not bound to the current turn")
        evidence["schema_failures"] = sorted(set(failures))
        evidence["review_chain_rejection_codes"] = sorted(rejection_codes)
        return evidence, completed_reviews
    evidence["main_response_turn_binding_verified"] = True
    bound_main_terminals = [
        item for item in main_task_completions if item[2] == main_turn_id
    ]
    evidence["main_terminal_checks"] = {
        "observed": bool(bound_main_terminals),
        "total_unique": main_task_complete_event_count == 1,
        "unique": len(bound_main_terminals) == 1,
        "timestamp_present": len(bound_main_terminals) == 1
        and isinstance(bound_main_terminals[0][1], datetime),
        "matches_final_file": len(bound_main_terminals) == 1
        and bound_main_terminals[0][3].rstrip("\n")
        == expected_main_final_text.rstrip("\n"),
        "terminal_is_last_record": len(bound_main_terminals) == 1
        and bound_main_terminals[0][0] == len(main_records) - 1,
    }
    if not all(bool(value) for value in evidence["main_terminal_checks"].values()):
        reject(
            "E_REVIEW_MAIN_TERMINAL_CARDINALITY"
            if main_task_complete_event_count != 1
            else "E_REVIEW_MAIN_TERMINAL"
        )
        failures.append(
            "main review rollout did not bind one terminal to the persisted final answer"
        )
        evidence["schema_failures"] = sorted(set(failures))
        evidence["review_chain_rejection_codes"] = sorted(rejection_codes)
        return evidence, completed_reviews
    main_terminal_index = bound_main_terminals[0][0]
    main_terminal_timestamp = bound_main_terminals[0][1]
    assert isinstance(main_terminal_timestamp, datetime)
    evidence["main_terminal_verified_count"] = 1
    completed_waits: list[dict[str, object]] = []
    wait_process_pairs: list[dict[str, object]] = []
    wait_check_records: list[dict[str, bool]] = []
    evidence["main_wait_call_count"] = len(wait_calls)
    evidence["wait_process_attempt_count"] = len(wait_calls)
    evidence["wait_call_checks"] = wait_check_records
    for wait in wait_calls:
        call_index = int(wait["index"])
        call_id = str(wait["call_id"])
        arguments = wait.get("arguments")
        arguments_object = isinstance(arguments, dict)
        arguments_empty = arguments_object and not arguments
        arguments_exact_timeout = (
            arguments_object and set(arguments) == {"timeout_ms"}
        )
        timeout_ms = arguments.get("timeout_ms") if arguments_object else None
        timeout_valid = (
            isinstance(timeout_ms, int)
            and not isinstance(timeout_ms, bool)
            and 10_000 <= timeout_ms <= 3_600_000
        )
        safe_arguments = bool(
            arguments_empty or (arguments_exact_timeout and timeout_valid)
        )
        output_record = function_outputs.get(call_id)
        wait_call_timestamp = wait.get("timestamp")
        wait_output_timestamp = output_record[1] if output_record else None
        output = parsed_json_object(output_record[2]) if output_record else None
        wait_turn_metadata = wait.get("turn_metadata")
        wait_output_turn_metadata = function_output_turn_metadata.get(call_id)
        output_non_timeout_complete = bool(
            output is not None
            and output.get("timed_out") is False
            and isinstance(output.get("message"), str)
            and str(output["message"]).strip() == "Wait completed."
        )
        wait_checks = {
            "arguments_object": arguments_object,
            "arguments_empty": arguments_empty,
            "arguments_exact_timeout": arguments_exact_timeout,
            "timeout_valid": timeout_valid,
            "safe_arguments": safe_arguments,
            "call_namespace_matches": wait.get("namespace") == "collaboration",
            "call_turn_metadata_matches": isinstance(wait_turn_metadata, dict)
            and wait_turn_metadata == {"turn_id": main_turn_id},
            "output_turn_metadata_matches": isinstance(
                wait_output_turn_metadata, dict
            )
            and wait_output_turn_metadata == {"turn_id": main_turn_id},
            "output_pair_exists": output_record is not None,
            "output_record_after_call": output_record is not None
            and output_record[0] > call_index,
            "call_timestamp_present": isinstance(wait_call_timestamp, datetime),
            "output_timestamp_present": isinstance(
                wait_output_timestamp, datetime
            ),
            "output_after_call": isinstance(wait_call_timestamp, datetime)
            and isinstance(wait_output_timestamp, datetime)
            and wait_output_timestamp >= wait_call_timestamp,
            "output_non_timeout_complete": output_non_timeout_complete,
        }
        safe_output_pair = bool(
            safe_arguments
            and wait_checks["call_namespace_matches"]
            and wait_checks["call_turn_metadata_matches"]
            and wait_checks["output_turn_metadata_matches"]
            and wait_checks["output_pair_exists"]
            and wait_checks["output_record_after_call"]
            and wait_checks["call_timestamp_present"]
            and wait_checks["output_timestamp_present"]
            and wait_checks["output_after_call"]
            and wait_checks["output_non_timeout_complete"]
        )
        wait_checks["safe_output_pair"] = safe_output_pair
        wait_check_records.append(wait_checks)
        if safe_output_pair:
            assert output_record is not None
            wait_process_pairs.append(
                {
                    "call_index": call_index,
                    "call_timestamp": wait.get("timestamp"),
                    "output_index": output_record[0],
                    "output_timestamp": output_record[1],
                }
            )
        required_wait_checks = (
            "arguments_exact_timeout",
            "timeout_valid",
            "call_namespace_matches",
            "call_turn_metadata_matches",
            "output_turn_metadata_matches",
            "output_pair_exists",
            "output_record_after_call",
            "call_timestamp_present",
            "output_timestamp_present",
            "output_after_call",
            "output_non_timeout_complete",
        )
        if not all(wait_checks[key] for key in required_wait_checks):
            continue
        assert output_record is not None
        completed_waits.append(
            {
                "call_index": call_index,
                "call_timestamp": wait.get("timestamp"),
                "output_index": output_record[0],
                "output_timestamp": output_record[1],
            }
        )
    evidence["completed_wait_count"] = len(completed_waits)
    evidence["wait_process_output_pair_count"] = len(wait_process_pairs)
    if len(spawn_calls) > 2:
        failures.append("review rollout exceeded the allowed spawn retry count")

    candidate_records: list[tuple[dict[str, object], dict[str, object]]] = []
    completed_spawn_lifecycles: list[
        tuple[dict[str, object], str, tuple[int, datetime | None, object]]
    ] = []
    for spawn in spawn_calls:
        call_index = int(spawn["index"])
        call_id = str(spawn["call_id"])
        arguments = spawn.get("arguments")
        if not isinstance(arguments, dict):
            continue
        spawn_turn_metadata = spawn.get("turn_metadata")
        if (
            spawn.get("namespace") != "collaboration"
            or not isinstance(spawn_turn_metadata, dict)
            or set(spawn_turn_metadata) != {"turn_id"}
            or spawn_turn_metadata.get("turn_id") != main_turn_id
        ):
            reject("E_REVIEW_SPAWN_HOST_BINDING")
            continue
        task_name = arguments.get("task_name")
        prompt = arguments.get("message")
        if not isinstance(task_name, str) or not isinstance(prompt, str):
            continue
        if set(arguments) != {"task_name", "message", "fork_turns"}:
            continue
        if arguments.get("fork_turns") != "none":
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", task_name):
            continue
        output_record = function_outputs.get(call_id)
        if output_record is None or output_record[0] <= call_index:
            continue
        spawn_call_timestamp = spawn.get("timestamp")
        spawn_output_timestamp = output_record[1]
        if (
            not isinstance(spawn_call_timestamp, datetime)
            or not isinstance(spawn_output_timestamp, datetime)
            or spawn_output_timestamp < spawn_call_timestamp
        ):
            continue
        output = parsed_json_object(output_record[2])
        output_turn_metadata = function_output_turn_metadata.get(call_id)
        spawn_output_index = output_record[0]
        reviewer_path = output.get("task_name") if output is not None else None
        if (
            not isinstance(output_turn_metadata, dict)
            or set(output_turn_metadata) != {"turn_id"}
            or output_turn_metadata.get("turn_id") != main_turn_id
            or not isinstance(output, dict)
            or set(output) != {"task_name"}
            or not isinstance(reviewer_path, str)
            or not reviewer_path.endswith(f"/{task_name}")
            or not re.fullmatch(r"/[a-z0-9_/-]{1,192}", reviewer_path)
        ):
            reject("E_REVIEW_SPAWN_OUTPUT_BINDING")
            continue
        completed_spawn_lifecycles.append((spawn, reviewer_path, output_record))
        parent_path = reviewer_path.rsplit("/", 1)[0]
        evidence["completed_spawn_count"] = int(
            evidence["completed_spawn_count"]
        ) + 1
        evidence["context_isolation_requested_count"] = int(
            evidence["context_isolation_requested_count"]
        ) + 1
        prompt_checks = review_prompt_contract_flags(
            prompt, expected_file, expected_text, evidence_marker
        )
        evidence["review_prompt_contract_checks"] = prompt_checks
        plaintext_prompt_verified = all(prompt_checks.values())
        encrypted_prompt = is_host_encrypted_collaboration_message(prompt)
        if not plaintext_prompt_verified and not encrypted_prompt:
            continue
        if plaintext_prompt_verified:
            evidence["review_prompt_contract_match_count"] = int(
                evidence["review_prompt_contract_match_count"]
            ) + 1
            evidence["review_prompt_acceptance_mode"] = "plaintext_contract"
            evidence["review_prompt_visibility"] = "plaintext"
        if encrypted_prompt:
            evidence["encrypted_spawn_prompt_count"] = int(
                evidence["encrypted_spawn_prompt_count"]
            ) + 1
            evidence["opaque_spawn_prompt_count"] = int(
                evidence["opaque_spawn_prompt_count"]
            ) + 1
            evidence["review_prompt_acceptance_mode"] = (
                "opaque_transport_behavior_only"
            )
            evidence["review_prompt_visibility"] = "opaque_spawn_prompt"
        if any(variant and variant in prompt for variant in marker_variants):
            continue
        if plaintext_prompt_verified:
            evidence["review_prompt_content_verified"] = True
            evidence["review_marker_nonforwarding_verified"] = True
        candidate_activities = [
            item
            for item in activities
            if item[0] > call_index
            and item[2] == reviewer_path
            and re.fullmatch(
                r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", item[3]
            )
        ]
        evidence["matching_reviewer_activity_count"] = int(
            evidence["matching_reviewer_activity_count"]
        ) + len(candidate_activities)
        child_ids = {item[3] for item in candidate_activities}
        evidence["candidate_child_thread_count"] = len(child_ids)
        if len(child_ids) != 1:
            continue
        child_thread_id = next(iter(child_ids))
        started_activities = [
            item
            for item in candidate_activities
            if item[4] == "started"
            and call_index < item[0] < spawn_output_index
            and isinstance(item[1], datetime)
            and spawn_call_timestamp <= item[1] <= spawn_output_timestamp
        ]
        evidence["started_activity_order_match_count"] = len(
            started_activities
        )
        failed_activities = [
            item
            for item in candidate_activities
            if item[4].lower()
            in {"failed", "cancelled", "canceled", "errored", "aborted"}
        ]
        if len(started_activities) != 1 or failed_activities:
            reject("E_REVIEW_STARTED_ACTIVITY")
            continue
        started_activity = started_activities[0]
        started_timestamp = started_activity[1]
        started_occurred_at_ms = started_activity[6]
        if (
            started_activity[5] != call_id
            or not isinstance(started_timestamp, datetime)
            or not isinstance(started_occurred_at_ms, int)
            or isinstance(started_occurred_at_ms, bool)
            or abs(
                started_occurred_at_ms
                - round(started_timestamp.timestamp() * 1_000)
            )
            > 250
        ):
            reject("E_REVIEW_STARTED_ACTIVITY")
            continue
        child_candidates = [
            path
            for path in rollout_files
            if path.name.endswith(f"-{child_thread_id}.jsonl")
        ]
        evidence["matching_child_rollout_count"] = len(child_candidates)
        if len(child_candidates) != 1:
            continue
        evidence["child_rollout_count"] = int(evidence["child_rollout_count"]) + 1
        advance_stage("child_rollout")
        child_records = read_records(child_candidates[0], "child review")
        if child_records is None:
            continue
        session_bindings: list[tuple[int, datetime | None, dict[str, object], dict[str, object]]] = []
        all_session_indexes: list[int] = []
        turn_contexts: list[tuple[int, datetime | None, dict[str, object]]] = []
        child_tool_calls: dict[str, tuple[int, datetime | None, str, object]] = {}
        child_tool_outputs: dict[str, tuple[int, datetime | None, object]] = {}
        all_child_calls: dict[str, tuple[int, datetime | None]] = {}
        all_child_outputs: dict[str, tuple[int, datetime | None]] = {}
        task_completions: list[tuple[int, datetime | None, str, str | None]] = []
        child_assistant_message_attempts: list[
            tuple[int, datetime | None, str | None, str, str | None, object]
        ] = []
        child_inbound_agent_messages: list[
            tuple[int, datetime | None, tuple[str, str, str] | None]
        ] = []
        child_event_message_attempts: list[
            tuple[int, datetime | None, str | None, str | None]
        ] = []
        child_call_ids: set[str] = set()
        child_output_ids: set[str] = set()
        duplicate_child_lifecycle_id = False
        child_failure_indexes: list[int] = []
        child_session_meta_event_count = 0
        child_turn_context_event_count = 0
        child_task_complete_event_count = 0
        for child_index, child_record in enumerate(child_records):
            if child_record.get("type") == "session_meta":
                child_session_meta_event_count += 1
            elif child_record.get("type") == "turn_context":
                child_turn_context_event_count += 1
            child_payload = child_record.get("payload")
            if not isinstance(child_payload, dict):
                continue
            child_timestamp = rollout_record_timestamp(child_record)
            if child_record.get("type") == "session_meta":
                all_session_indexes.append(child_index)
                source = child_payload.get("source")
                spawn_source = None
                if isinstance(source, dict):
                    subagent = source.get("subagent")
                    if isinstance(subagent, dict):
                        spawn_source = subagent.get("thread_spawn")
                if isinstance(spawn_source, dict):
                    session_bindings.append(
                        (child_index, child_timestamp, child_payload, spawn_source)
                    )
            elif child_record.get("type") == "turn_context":
                turn_contexts.append((child_index, child_timestamp, child_payload))
            elif child_record.get("type") == "response_item":
                child_type = child_payload.get("type")
                child_call_id = child_payload.get("call_id")
                if (
                    child_type == "message"
                    and child_payload.get("role") == "assistant"
                ):
                    parsed_child_response = rollout_assistant_response_message(
                        child_payload
                    )
                    child_assistant_message_attempts.append(
                        (
                            child_index,
                            child_timestamp,
                            parsed_child_response[1]
                            if parsed_child_response is not None
                            else None,
                            "assistant_message",
                            parsed_child_response[0]
                            if parsed_child_response is not None
                            else None,
                            child_payload.get(
                                "internal_chat_message_metadata_passthrough"
                            ),
                        )
                    )
                elif child_type == "agent_message":
                    child_inbound_agent_messages.append(
                        (
                            child_index,
                            child_timestamp,
                            rollout_inbound_agent_message(child_payload),
                        )
                    )
                if (
                    child_type in {"custom_tool_call", "function_call"}
                    and isinstance(child_call_id, str)
                ):
                    if child_call_id in child_call_ids:
                        duplicate_child_lifecycle_id = True
                    child_call_ids.add(child_call_id)
                    all_child_calls[child_call_id] = (
                        child_index, child_timestamp
                    )
                    if (
                        child_type == "custom_tool_call"
                        and child_payload.get("name") == "exec"
                        and isinstance(child_payload.get("input"), str)
                    ):
                        child_tool_calls[child_call_id] = (
                            child_index,
                            child_timestamp,
                            "exec",
                            child_payload["input"],
                        )
                    elif (
                        child_type == "function_call"
                        and child_payload.get("name") == "exec_command"
                        and isinstance(child_payload.get("arguments"), str)
                    ):
                        child_tool_calls[child_call_id] = (
                            child_index,
                            child_timestamp,
                            "exec_command",
                            child_payload["arguments"],
                        )
                elif (
                    child_type in {"custom_tool_call_output", "function_call_output"}
                    and isinstance(child_call_id, str)
                ):
                    if child_call_id in child_output_ids:
                        duplicate_child_lifecycle_id = True
                    child_output_ids.add(child_call_id)
                    all_child_outputs[child_call_id] = (
                        child_index, child_timestamp
                    )
                    child_tool_outputs[child_call_id] = (
                        child_index,
                        child_timestamp,
                        child_payload.get("output"),
                    )
            elif child_record.get("type") == "event_msg":
                if child_payload.get("type") == "agent_message":
                    parsed_event_message = rollout_event_agent_message(
                        child_payload
                    )
                    child_event_message_attempts.append(
                        (
                            child_index,
                            child_timestamp,
                            parsed_event_message[0]
                            if parsed_event_message is not None
                            else None,
                            parsed_event_message[1]
                            if parsed_event_message is not None
                            else None,
                        )
                    )
                elif child_payload.get("type") == "task_complete":
                    child_task_complete_event_count += 1
                    if isinstance(child_payload.get("last_agent_message"), str):
                        task_completions.append(
                            (
                                child_index,
                                child_timestamp,
                                str(child_payload["last_agent_message"]),
                                str(child_payload["turn_id"])
                                if isinstance(child_payload.get("turn_id"), str)
                                else None,
                            )
                        )
            if (
                child_record.get("type") in {"turn_aborted", "turn.failed"}
                or child_payload.get("type")
                in {"turn_aborted", "task_failed", "agent_error", "stream_error"}
            ):
                child_failure_indexes.append(child_index)
        if duplicate_child_lifecycle_id:
            evidence["duplicate_child_lifecycle_detected"] = True
            reject("E_REVIEW_CHILD_LIFECYCLE_DUPLICATE")
            continue
        evidence["child_session_binding_count"] = int(
            evidence["child_session_binding_count"]
        ) + len(session_bindings)
        evidence["child_session_meta_event_count"] = int(
            evidence["child_session_meta_event_count"]
        ) + child_session_meta_event_count
        evidence["child_turn_context_event_count"] = int(
            evidence["child_turn_context_event_count"]
        ) + child_turn_context_event_count
        evidence["child_task_complete_event_count"] = int(
            evidence["child_task_complete_event_count"]
        ) + child_task_complete_event_count
        evidence["child_assistant_message_attempt_count"] = int(
            evidence["child_assistant_message_attempt_count"]
        ) + len(child_assistant_message_attempts)
        evidence["child_inbound_agent_message_count"] = int(
            evidence["child_inbound_agent_message_count"]
        ) + len(child_inbound_agent_messages)
        evidence["child_preload_announcement_count"] = int(
            evidence["child_preload_announcement_count"]
        ) + sum(
            isinstance(item[2], str)
            and item[2].rstrip("\n") == CANONICAL_PRELOAD_ANNOUNCEMENT
            for item in child_assistant_message_attempts
        )
        evidence["child_boot_receipt_count"] = int(
            evidence["child_boot_receipt_count"]
        ) + sum(
            isinstance(item[2], str) and item[2].startswith("COS_BOOT_RECEIPT")
            for item in child_assistant_message_attempts
        )
        evidence["child_expected_terminal_message_count"] = int(
            evidence["child_expected_terminal_message_count"]
        ) + sum(
            isinstance(item[2], str)
            and item[2].rstrip("\n")
            == expected_review_terminal(evidence_marker, expected_text).rstrip("\n")
            for item in child_assistant_message_attempts
        )
        evidence["child_pass_schema_message_count"] = int(
            evidence["child_pass_schema_message_count"]
        ) + sum(
            isinstance(item[2], str) and "REVIEW_VERDICT: PASS" in item[2]
            for item in child_assistant_message_attempts
        )
        evidence["child_event_message_attempt_count"] = int(
            evidence["child_event_message_attempt_count"]
        ) + len(child_event_message_attempts)
        if child_session_meta_event_count != 1 or len(session_bindings) != 1:
            reject(
                "E_REVIEW_CHILD_SESSION_CARDINALITY"
                if child_session_meta_event_count != 1
                else "E_REVIEW_CHILD_SESSION_BINDING"
            )
            continue
        advance_stage("session_binding")
        session_index, session_timestamp, session_payload, spawn_source = session_bindings[0]
        session_checks = {
            "observed": True,
            "child_id_matches": session_payload.get("id") == child_thread_id,
            "parent_session_matches": session_payload.get("session_id")
            == main_thread_id,
            "parent_thread_matches": session_payload.get("parent_thread_id")
            == main_thread_id,
            "fork_none_lineage_absent": "forked_from_id" not in session_payload,
            "thread_source_matches": session_payload.get("thread_source")
            == "subagent",
            "top_level_agent_path_matches": session_payload.get("agent_path")
            == reviewer_path,
            "agent_nickname_matches": isinstance(
                session_payload.get("agent_nickname"), str
            )
            and bool(session_payload.get("agent_nickname"))
            and session_payload.get("agent_nickname")
            == spawn_source.get("agent_nickname"),
            "provider_matches": session_payload.get("model_provider")
            == expected_provider,
            "cli_version_matches": session_payload.get("cli_version")
            == expected_cli_version,
            "spawn_parent_matches": spawn_source.get("parent_thread_id")
            == main_thread_id,
            "agent_path_matches": spawn_source.get("agent_path") == reviewer_path,
            "depth_matches": spawn_source.get("depth") == 1,
            "cwd_matches": normalized_absolute_path(session_payload.get("cwd"))
            == normalized_absolute_path(str(fixture.resolve())),
            "timestamp_present": isinstance(session_timestamp, datetime),
            "after_spawn_call": isinstance(session_timestamp, datetime)
            and session_timestamp >= spawn_call_timestamp,
            "before_spawn_output": isinstance(session_timestamp, datetime)
            and session_timestamp <= spawn_output_timestamp,
        }
        evidence["child_session_checks"] = session_checks
        session_identity_keys = {
            "child_id_matches",
            "parent_session_matches",
            "parent_thread_matches",
            "fork_none_lineage_absent",
            "thread_source_matches",
            "top_level_agent_path_matches",
            "agent_nickname_matches",
            "provider_matches",
            "cli_version_matches",
            "spawn_parent_matches",
            "agent_path_matches",
            "depth_matches",
            "cwd_matches",
        }
        if not all(bool(session_checks[key]) for key in session_identity_keys):
            reject("E_REVIEW_CHILD_SESSION_IDENTITY")
            continue
        # The spawn call causally precedes child startup, but its tool output may
        # be recorded before the child writes session_meta in a separate JSONL.
        # Keep that upper-bound bit for diagnostics; do not treat it as identity.
        if not all(
            bool(session_checks[key])
            for key in (
                "timestamp_present",
                "after_spawn_call",
            )
        ):
            reject("E_REVIEW_CHILD_SESSION_TIME_ORDER")
            continue
        advance_stage("session_identity")
        session_floor = max(all_session_indexes, default=session_index)
        applicable_turn_contexts = [
            item
            for item in turn_contexts
            if item[0] > session_floor
            and item[2].get("turn_id") != main_turn_id
        ]
        evidence["child_turn_context_record_count"] = int(
            evidence["child_turn_context_record_count"]
        ) + len(applicable_turn_contexts)
        distinct_turn_ids = {
            str(item[2]["turn_id"])
            for item in applicable_turn_contexts
            if isinstance(item[2].get("turn_id"), str)
        }
        evidence["child_distinct_turn_id_count"] = int(
            evidence["child_distinct_turn_id_count"]
        ) + len(distinct_turn_ids)
        if child_turn_context_event_count != 1 or len(applicable_turn_contexts) != 1:
            reject("E_REVIEW_CHILD_TURN_CARDINALITY")
            continue
        turn_index, turn_timestamp, turn_payload = applicable_turn_contexts[0]
        turn_checks = {
            "observed": True,
            "turn_id_valid": isinstance(turn_payload.get("turn_id"), str)
            and bool(EXECUTION_ID_RE.fullmatch(str(turn_payload["turn_id"]))),
            "model_matches": turn_payload.get("model") == expected_model,
            "effort_matches": turn_payload.get("effort")
            == expected_reasoning_effort,
            "cwd_matches": normalized_absolute_path(turn_payload.get("cwd"))
            == normalized_absolute_path(str(fixture.resolve())),
            "timestamp_present": isinstance(turn_timestamp, datetime),
            "after_session": isinstance(turn_timestamp, datetime)
            and isinstance(session_timestamp, datetime)
            and turn_timestamp >= session_timestamp,
        }
        evidence["child_turn_checks"] = turn_checks
        if not all(
            bool(turn_checks[key])
            for key in ("turn_id_valid", "model_matches", "effort_matches", "cwd_matches")
        ):
            reject("E_REVIEW_CHILD_TURN_IDENTITY")
            continue
        if not all(
            bool(turn_checks[key])
            for key in (
                "timestamp_present",
                "after_session",
            )
        ):
            reject("E_REVIEW_CHILD_TURN_TIME_ORDER")
            continue
        child_turn_id = str(turn_payload["turn_id"])
        if len(child_inbound_agent_messages) != 1:
            reject("E_REVIEW_CHILD_INBOUND_CARDINALITY")
            continue
        inbound_index, inbound_timestamp, inbound = child_inbound_agent_messages[0]
        child_action_records = (
            [(item[0], item[1]) for item in child_assistant_message_attempts]
            + list(all_child_calls.values())
            + list(all_child_outputs.values())
            + [(item[0], item[1]) for item in child_event_message_attempts]
            + [(item[0], item[1]) for item in task_completions]
        )
        first_child_action_index = min(
            (item[0] for item in child_action_records), default=len(child_records)
        )
        child_action_timestamps = [
            item[1] for item in child_action_records if isinstance(item[1], datetime)
        ]
        if (
            inbound is None
            or inbound != (parent_path, reviewer_path, child_turn_id)
            or inbound_index <= turn_index
            or inbound_index >= first_child_action_index
            or not child_transport_action_surface_valid(
                child_records, turn_index, inbound_index
            )
            or not isinstance(inbound_timestamp, datetime)
            or inbound_timestamp < turn_timestamp
            or len(child_action_timestamps) != len(child_action_records)
            or (
                child_action_timestamps
                and inbound_timestamp >= min(child_action_timestamps)
            )
        ):
            reject("E_REVIEW_CHILD_INBOUND_CONTRACT")
            continue
        evidence["child_inbound_agent_message_contract_verified_count"] = int(
            evidence["child_inbound_agent_message_contract_verified_count"]
        ) + 1
        if any(
            item[3] != "assistant_message"
            or item[5] != {"turn_id": child_turn_id}
            for item in child_assistant_message_attempts
        ):
            reject("E_REVIEW_CHILD_RESPONSE_TURN_BINDING")
            continue
        evidence["child_response_turn_binding_verified_count"] = int(
            evidence["child_response_turn_binding_verified_count"]
        ) + 1
        advance_stage("turn_identity")
        evidence["child_identity_verified_count"] = int(
            evidence["child_identity_verified_count"]
        ) + 1
        child_tool_calls = {
            key: value
            for key, value in child_tool_calls.items()
            if value[0] > turn_index
        }
        child_tool_outputs = {
            key: value
            for key, value in child_tool_outputs.items()
            if value[0] > turn_index
        }
        all_child_calls = {
            key: value
            for key, value in all_child_calls.items()
            if value[0] > turn_index
        }
        all_child_outputs = {
            key: value
            for key, value in all_child_outputs.items()
            if value[0] > turn_index
        }
        evidence["child_tool_call_count"] = int(
            evidence["child_tool_call_count"]
        ) + len(all_child_calls)
        evidence["child_tool_output_count"] = int(
            evidence["child_tool_output_count"]
        ) + len(all_child_outputs)
        if (
            len(all_child_calls) not in {1, 2}
            or set(all_child_outputs) != set(all_child_calls)
            or set(child_tool_calls) != set(all_child_calls)
            or set(child_tool_outputs) != set(all_child_calls)
        ):
            reject("E_REVIEW_CHILD_TOOL_CARDINALITY")
            continue
        advance_stage("tool_cardinality")
        task_completions = [
            item for item in task_completions if item[0] > turn_index
        ]
        child_failure = any(index > turn_index for index in child_failure_indexes)
        if (
            child_failure
            or child_task_complete_event_count != 1
            or len(task_completions) != 1
        ):
            reject("E_REVIEW_CHILD_TERMINAL")
            continue
        (
            terminal_index,
            terminal_timestamp,
            reviewer_message,
            terminal_turn_id,
        ) = task_completions[0]
        if (
            terminal_index != len(child_records) - 1
            or terminal_timestamp is None
            or terminal_turn_id != turn_payload.get("turn_id")
            or not review_terminal_has_no_blockers(
                reviewer_message, evidence_marker, expected_text
            )
        ):
            reject("E_REVIEW_CHILD_TERMINAL")
            continue
        exact_child_terminal_messages = [
            item
            for item in child_assistant_message_attempts
            if isinstance(item[2], str)
            and item[2].rstrip("\n") == reviewer_message.rstrip("\n")
            and item[3] == "assistant_message"
            and item[4] == "final_answer"
        ]
        artifact_read_call_indexes = [
            item[0]
            for item in child_tool_calls.values()
            if strict_artifact_read_arguments(
                item[2],
                item[3],
                fixture,
                expected_file,
                expected_text,
                evidence_marker,
            )
            is not None
        ]
        artifact_read_call_index = (
            artifact_read_call_indexes[0]
            if len(artifact_read_call_indexes) == 1
            else terminal_index
        )
        guard_read_call_ids = [
            call_id
            for call_id, item in child_tool_calls.items()
            if strict_guard_skill_read_arguments(
                item[2], item[3], fixture, expected_guard_skill_path
            )
            is not None
        ]
        guard_output_records = [
            child_tool_outputs[call_id]
            for call_id in guard_read_call_ids
            if call_id in child_tool_outputs
        ]
        guard_completion_index = max(
            (item[0] for item in guard_output_records), default=turn_index
        )
        guard_completion_timestamp = (
            max(guard_output_records, key=lambda item: item[0])[1]
            if guard_output_records
            else None
        )
        last_tool_output_index = max(
            (item[0] for item in all_child_outputs.values()), default=turn_index
        )
        last_tool_output_timestamp = max(
            all_child_outputs.values(), key=lambda item: item[0]
        )[1]
        safe_child_progress_messages = [
            item
            for item in child_assistant_message_attempts
            if item not in exact_child_terminal_messages
            and item[3] == "assistant_message"
            and item[4] == "commentary"
            and guard_completion_index < item[0] < artifact_read_call_index
            and (
                guard_completion_timestamp is None
                or (
                    isinstance(item[1], datetime)
                    and item[1] > guard_completion_timestamp
                )
            )
            and isinstance(item[2], str)
            and item[2].rstrip("\n") == STRICT_REVIEW_PROGRESS
        ]
        evidence["child_progress_message_count"] = int(
            evidence["child_progress_message_count"]
        ) + len(safe_child_progress_messages)
        event_child_progress_messages = [
            item
            for item in child_event_message_attempts
            if item[2] == "commentary"
            and isinstance(item[3], str)
            and item[3].rstrip("\n") == STRICT_REVIEW_PROGRESS
        ]
        evidence["child_event_progress_message_count"] = int(
            evidence["child_event_progress_message_count"]
        ) + len(event_child_progress_messages)
        if not child_event_message_contract_valid(
            child_event_message_attempts,
            reviewer_message,
            STRICT_REVIEW_PROGRESS,
            turn_index=turn_index,
            commentary_after_index=guard_completion_index,
            commentary_before_index=artifact_read_call_index,
            final_after_index=last_tool_output_index,
            terminal_index=terminal_index,
            commentary_after_timestamp=guard_completion_timestamp,
            final_after_timestamp=last_tool_output_timestamp,
            terminal_timestamp=terminal_timestamp,
        ):
            reject("E_REVIEW_CHILD_EVENT_MESSAGE_CONTRACT")
            continue
        evidence["child_event_message_contract_verified"] = True
        if (
            len(exact_child_terminal_messages) != 1
            or len(safe_child_progress_messages) > 1
            or len(exact_child_terminal_messages) + len(safe_child_progress_messages)
            != len(child_assistant_message_attempts)
            or not (
                last_tool_output_index < exact_child_terminal_messages[0][0]
                < terminal_index
            )
            or not isinstance(exact_child_terminal_messages[0][1], datetime)
            or not isinstance(last_tool_output_timestamp, datetime)
            or exact_child_terminal_messages[0][1] < last_tool_output_timestamp
            or exact_child_terminal_messages[0][1] > terminal_timestamp
        ):
            reject("E_REVIEW_CHILD_MESSAGE_CONTRADICTION")
            continue
        advance_stage("terminal")
        evidence["child_terminal_verified_count"] = int(
            evidence["child_terminal_verified_count"]
        ) + 1
        artifact_modified_at = datetime.fromtimestamp(
            artifact_mtime_ns / 1_000_000_000, tz=timezone.utc
        )
        artifact_changed_at = datetime.fromtimestamp(
            max(artifact_mtime_ns, artifact_ctime_ns) / 1_000_000_000,
            tz=timezone.utc,
        )
        verified_tools: list[
            tuple[int, int, datetime, str, dict[str, object]]
        ] = []
        verified_guard_tools: list[
            tuple[int, int, datetime, str, dict[str, object]]
        ] = []
        for child_call_id, (
            tool_index,
            tool_timestamp,
            tool_name,
            tool_input,
        ) in child_tool_calls.items():
            tool_output = child_tool_outputs.get(child_call_id)
            safe_arguments = strict_artifact_read_arguments(
                tool_name,
                tool_input,
                fixture,
                expected_file,
                expected_text,
                evidence_marker,
            )
            exact_output_match = bool(
                tool_output is not None
                and tool_output_contains_exact_artifact(
                    tool_output[2],
                    expected_artifact_text,
                    evidence_marker,
                    expected_text,
                )
            )
            guard_arguments = strict_guard_skill_read_arguments(
                tool_name,
                tool_input,
                fixture,
                expected_guard_skill_path,
            )
            guard_output_match = bool(
                tool_output is not None
                and tool_output_contains_exact_text(
                    tool_output[2], expected_guard_skill_text
                )
            )
            tool_input_text = str(tool_input)
            tool_output_value = tool_output[2] if tool_output is not None else None
            tool_output_text = json.dumps(
                tool_output_value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            verified_workdir = (
                safe_arguments.get("workdir")
                if safe_arguments is not None
                else None
            )
            workdir_literal_absolute = bool(
                isinstance(verified_workdir, str)
                and Path(verified_workdir).is_absolute()
            )
            workdir_canonical_match = bool(
                isinstance(verified_workdir, str)
                and normalized_absolute_path(verified_workdir)
                == normalized_absolute_path(str(fixture.resolve()))
            )
            output_timestamp = tool_output[1] if tool_output is not None else None
            direct_read_checks = {
                "observed": True,
                "tool_name_allowed": tool_name in {"exec", "exec_command"},
                "exact_command_once_in_input": tool_input_text.count(
                    f"/bin/cat {expected_file}"
                )
                == 1,
                "expected_file_mentioned": expected_file in tool_input_text,
                # Retained for receipt compatibility; this now reports the
                # parsed path property instead of a macOS /var vs /private/var
                # lexical comparison.
                "absolute_workdir_mentioned": workdir_literal_absolute,
                "workdir_literal_absolute": workdir_literal_absolute,
                "workdir_canonical_match": workdir_canonical_match,
                "cmd_key_mentioned": bool(
                    re.search(r'["\']?cmd["\']?\s*:', tool_input_text)
                ),
                "workdir_key_mentioned": bool(
                    re.search(r'["\']?workdir["\']?\s*:', tool_input_text)
                ),
                "login_key_mentioned": bool(
                    re.search(r'["\']?login["\']?\s*:', tool_input_text)
                ),
                "tty_key_mentioned": bool(
                    re.search(r'["\']?tty["\']?\s*:', tool_input_text)
                ),
                "shell_key_mentioned": bool(
                    re.search(r'["\']?shell["\']?\s*:', tool_input_text)
                ),
                "single_tool_namespace_call": tool_input_text.count("tools.") == 1,
                "single_await": tool_input_text.count("await") == 1,
                "output_property_forwarded": ".output" in tool_input_text,
                "meta_spread_used": "...meta" in tool_input_text,
                "single_text_call": tool_input_text.count("text(") == 1,
                "output_pair_exists": tool_output is not None,
                "output_record_after_call": tool_output is not None
                and tool_output[0] > tool_index,
                "call_timestamp_present": isinstance(tool_timestamp, datetime),
                "output_timestamp_present": isinstance(output_timestamp, datetime),
                "call_after_turn": isinstance(tool_timestamp, datetime)
                and tool_timestamp > turn_timestamp,
                "call_after_started_activity": isinstance(tool_timestamp, datetime)
                and isinstance(started_timestamp, datetime)
                and tool_timestamp >= started_timestamp,
                "strict_arguments_match": safe_arguments is not None,
                "exact_output_match": exact_output_match,
                "output_is_string": isinstance(tool_output_value, str),
                "output_is_list": isinstance(tool_output_value, list),
                "output_is_object": isinstance(tool_output_value, dict),
                "output_shape": direct_read_output_shape(tool_output_value),
                "output_contains_marker": evidence_marker in tool_output_text,
                "output_contains_expected_text": expected_text in tool_output_text,
                "output_contains_exact_artifact": expected_artifact_text
                in tool_output_text,
                "call_after_artifact_mtime": isinstance(tool_timestamp, datetime)
                and tool_timestamp >= artifact_modified_at,
                "call_after_artifact_change": isinstance(tool_timestamp, datetime)
                and tool_timestamp > artifact_changed_at,
                "output_after_call": isinstance(output_timestamp, datetime)
                and isinstance(tool_timestamp, datetime)
                and output_timestamp >= tool_timestamp,
                "terminal_after_output": isinstance(output_timestamp, datetime)
                and terminal_timestamp >= output_timestamp,
            }
            evidence["child_direct_read_checks"] = direct_read_checks
            required_direct_read_checks = (
                "output_pair_exists",
                "output_record_after_call",
                "call_timestamp_present",
                "output_timestamp_present",
                "call_after_turn",
                "call_after_started_activity",
                "strict_arguments_match",
                "exact_output_match",
                "call_after_artifact_change",
                "output_after_call",
                "terminal_after_output",
            )
            if not all(
                bool(direct_read_checks[key])
                for key in required_direct_read_checks
            ):
                if (
                    guard_arguments is not None
                    and guard_output_match
                    and tool_output is not None
                    and isinstance(tool_timestamp, datetime)
                    and isinstance(output_timestamp, datetime)
                    and tool_output[0] > tool_index
                    and tool_timestamp > turn_timestamp
                    and output_timestamp >= tool_timestamp
                ):
                    verified_guard_tools.append(
                        (
                            tool_index,
                            tool_output[0],
                            output_timestamp,
                            tool_name,
                            guard_arguments,
                        )
                    )
                continue
            assert safe_arguments is not None
            assert isinstance(output_timestamp, datetime)
            verified_tools.append(
                (
                    tool_index,
                    tool_output[0],
                    output_timestamp,
                    tool_name,
                    safe_arguments,
                )
            )
        if (
            len(verified_tools) != 1
            or len(verified_guard_tools) != len(all_child_calls) - 1
            or (
                verified_guard_tools
                and verified_guard_tools[0][1] >= verified_tools[0][0]
            )
        ):
            reject("E_REVIEW_DIRECT_READ")
            continue
        evidence["guard_skill_read_verified_count"] = int(
            evidence["guard_skill_read_verified_count"]
        ) + len(verified_guard_tools)
        advance_stage("direct_read")
        evidence["direct_exact_read_verified_count"] = int(
            evidence["direct_exact_read_verified_count"]
        ) + 1
        evidence["post_change_read_verified_count"] = int(
            evidence["post_change_read_verified_count"]
        ) + 1
        (
            _tool_call_index,
            tool_output_index,
            _tool_output_timestamp,
            tool_name,
            safe_arguments,
        ) = verified_tools[0]
        process_waits = [
            wait
            for wait in wait_process_pairs
            if int(wait["call_index"]) > spawn_output_index
        ]
        parent_path = reviewer_path.rsplit("/", 1)[0]
        reviewer_delivery_attempts = [
            item
            for item in delivery_attempts
            if item[2] == reviewer_path or item[3] == parent_path
        ]
        evidence["reviewer_delivery_attempt_count"] = int(
            evidence["reviewer_delivery_attempt_count"]
        ) + len(reviewer_delivery_attempts)
        delivered_results = [
            item
            for item in reviewer_delivery_attempts
            if item[2] == reviewer_path
            and item[3] == parent_path
            and isinstance(item[4], str)
            and item[5] == {"turn_id": main_turn_id}
            and item[0] > spawn_output_index
            and item[0] < main_terminal_index
            and isinstance(item[1], datetime)
            and item[1] >= terminal_timestamp
            and item[1] <= main_terminal_timestamp
            and delivered_review_message_matches(
                item[4],
                reviewer_path,
                reviewer_path.rsplit("/", 1)[0],
                reviewer_message,
            )
        ]
        evidence["candidate_bound_delivery_count"] = int(
            evidence["candidate_bound_delivery_count"]
        ) + len(delivered_results)
        if (
            len(delivery_attempts) != 1
            or len(reviewer_delivery_attempts) != 1
            or len(delivered_results) != 1
        ):
            reject("E_REVIEW_DELIVERY_BINDING")
            continue
        delivered_result = delivered_results[0]
        process_waits = [
            wait
            for wait in process_waits
            if int(wait["output_index"]) < delivered_result[0]
        ]
        invalid_wait_process = bool(wait_calls) and len(process_waits) != len(
            wait_calls
        )
        if invalid_wait_process:
            reject("E_REVIEW_WAIT_PROCESS")
            continue
        premature_claims = [
            item
            for item in main_assistant_messages
            if item[0] < delivered_result[0]
            and isinstance(item[2], str)
            and claims_external_reviewer_result(item[2])
        ]
        evidence["premature_reviewer_claim_count"] = int(
            evidence["premature_reviewer_claim_count"]
        ) + len(premature_claims)
        if premature_claims:
            reject("E_REVIEW_PREMATURE_EXTERNAL_CLAIM")
            continue
        forbidden_strict_claim = re.compile(
            r"(?:REVIEW_EVIDENCE_|REVIEW_FINDINGS_COUNT|REVIEW_VERDICT|"
            r"MAIN_REVIEW_ADOPTION|COLD_CONTEXT_ISOLATION|"
            r"reviewer-owned\s+read|\bADOPTION\s*:|\bISOLATION\s*:|"
            r"\bFINDINGS?\s*:)",
            flags=re.IGNORECASE,
        )
        exact_main_final_messages = [
            item
            for item in main_assistant_messages
            if isinstance(item[2], str)
            and item[2].rstrip("\n") == expected_main_final_text.rstrip("\n")
        ]
        evidence["main_exact_final_message_count"] = len(exact_main_final_messages)
        if (
            len(exact_main_final_messages) != 1
            or (
                exact_main_final_messages[0][0] <= delivered_result[0]
                or exact_main_final_messages[0][0] >= main_terminal_index
                or exact_main_final_messages[0][0]
                != max(item[0] for item in main_assistant_messages)
                or not isinstance(exact_main_final_messages[0][1], datetime)
                or exact_main_final_messages[0][1] < delivered_result[1]
                or exact_main_final_messages[0][1] > main_terminal_timestamp
            )
        ):
            reject("E_REVIEW_MAIN_FINAL_CARDINALITY")
            continue
        contradictory_main_claims = [
            item
            for item in main_assistant_messages
            if item not in exact_main_final_messages
            and isinstance(item[2], str)
            and (
                forbidden_strict_claim.search(item[2]) is not None
                or claims_external_reviewer_result(item[2])
                or claims_completion_contradiction(item[2])
            )
        ]
        evidence["main_contradictory_review_claim_count"] = int(
            evidence["main_contradictory_review_claim_count"]
        ) + len(contradictory_main_claims)
        if contradictory_main_claims:
            reject("E_REVIEW_MAIN_CONTRADICTION")
            continue
        if not main_assistant_message_contract_valid(
            [(item[0], item[1], item[2]) for item in main_assistant_messages],
            expected_main_final_text,
            expected_boot_receipt,
            require_final=True,
        ):
            reject("E_REVIEW_MAIN_MESSAGE_CONTRACT")
            continue
        if not assistant_response_phase_contract_valid(
            [
                (item[0], item[1], item[2], item[3])
                for item in main_assistant_messages
            ],
            expected_main_final_text,
        ):
            reject("E_REVIEW_MAIN_RESPONSE_PHASE_CONTRACT")
            continue
        if not main_event_message_contract_valid(
            main_event_messages,
            expected_main_final_text,
            expected_boot_receipt,
            final_after_index=delivered_result[0],
            terminal_index=main_terminal_index,
            final_after_timestamp=delivered_result[1],
            terminal_timestamp=main_terminal_timestamp,
        ):
            reject("E_REVIEW_MAIN_EVENT_MESSAGE_CONTRACT")
            continue
        evidence["main_event_message_contract_verified"] = True
        advance_stage("bound_delivery")
        evidence["wait_bound_to_single_child_count"] = int(
            evidence["wait_bound_to_single_child_count"]
        ) + len(process_waits)
        evidence["review_result_delivery_verified_count"] = int(
            evidence["review_result_delivery_verified_count"]
        ) + 1
        evidence["delivery_before_main_terminal_verified_count"] = int(
            evidence["delivery_before_main_terminal_verified_count"]
        ) + 1
        evidence["delivery_parent_turn_verified_count"] = int(
            evidence["delivery_parent_turn_verified_count"]
        ) + 1
        evidence["review_truth_verified"] = True
        evidence["review_process_compliant"] = True
        evidence["review_sync_method"] = (
            "wait_then_bound_delivery"
            if process_waits
            else "bound_delivery_before_main_terminal"
        )
        review = {
            "spawn_event_index": -1,
            "wait_event_index": -1,
            "prompt": prompt,
            "review_prompt_plaintext_verified": plaintext_prompt_verified,
            "review_prompt_content_verified": plaintext_prompt_verified,
            "review_marker_nonforwarding_verified": plaintext_prompt_verified,
            "review_packet_behaviorally_verified": True,
            "message": reviewer_message,
            "sender_thread_id": main_thread_id,
            "context_isolation_verified": False,
            "reviewer_owned_file_read_verified": True,
            "post_change_artifact_read_verified": True,
            "review_sync_method": evidence["review_sync_method"],
        }
        record = {
            "reviewer_thread_sha256": sha256_bytes(child_thread_id.encode()),
            "reviewer_path_sha256": sha256_bytes(reviewer_path.encode()),
            "prompt_sha256": sha256_bytes(prompt.encode()),
            "message_sha256": sha256_bytes(reviewer_message.encode()),
            "tool_name": tool_name,
            "review_sync_method": evidence["review_sync_method"],
            "tool_command_sha256": sha256_bytes(
                str(safe_arguments["cmd"]).encode()
            ),
            "child_identity_sha256": sha256_bytes(
                json.dumps(
                    {
                        "model": expected_model,
                        "provider": expected_provider,
                        "effort": expected_reasoning_effort,
                        "cli_version": expected_cli_version,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ),
        }
        candidate_records.append((review, record))
        advance_stage("complete")

    spawn_retry_contract_verified = False
    if (
        len(rollout_files) == 2
        and len(spawn_calls) == 1
        and len(completed_spawn_lifecycles) == 1
    ):
        spawn_retry_contract_verified = True
    elif (
        len(rollout_files) == 2
        and len(spawn_calls) == 2
        and len(completed_spawn_lifecycles) == 1
    ):
        successful_spawn = completed_spawn_lifecycles[0][0]
        failed_spawns = [
            item for item in spawn_calls if item["call_id"] != successful_spawn["call_id"]
        ]
        failed_spawn = failed_spawns[0]
        failed_output = function_outputs.get(str(failed_spawn["call_id"]))
        failed_arguments = failed_spawn.get("arguments")
        successful_arguments = successful_spawn.get("arguments")
        failed_turn_metadata = failed_spawn.get("turn_metadata")
        failed_output_turn_metadata = function_output_turn_metadata.get(
            str(failed_spawn["call_id"])
        )
        if (
            int(failed_spawn["index"]) < int(successful_spawn["index"])
            and failed_spawn.get("namespace") == "collaboration"
            and failed_turn_metadata == {"turn_id": main_turn_id}
            and isinstance(failed_arguments, dict)
            and isinstance(successful_arguments, dict)
            and set(failed_arguments) == {"task_name", "message", "fork_turns"}
            and failed_arguments.get("fork_turns") == "none"
            and isinstance(failed_arguments.get("task_name"), str)
            and re.fullmatch(
                r"[a-z0-9][a-z0-9_-]{0,63}", str(failed_arguments.get("task_name"))
            )
            and isinstance(failed_arguments.get("message"), str)
            and failed_arguments.get("message") == successful_arguments.get("message")
            and isinstance(failed_spawn.get("timestamp"), datetime)
            and failed_output is not None
            and failed_output[0] > int(failed_spawn["index"])
            and failed_output[0] < int(successful_spawn["index"])
            and isinstance(failed_output[1], datetime)
            and failed_output[1] >= failed_spawn["timestamp"]
            and failed_output_turn_metadata == {"turn_id": main_turn_id}
            and explicit_spawn_failure_output(failed_output[2])
            and not any(
                activity[5] == failed_spawn["call_id"] for activity in activities
            )
            and not any(
                activity[4] == "started"
                and activity[5] != successful_spawn["call_id"]
                for activity in activities
            )
        ):
            evidence["failed_spawn_attempt_count"] = 1
            evidence["spawn_retry_count"] = 1
            spawn_retry_contract_verified = True
    evidence["spawn_retry_contract_verified"] = spawn_retry_contract_verified
    if not spawn_retry_contract_verified:
        reject("E_REVIEW_SPAWN_RETRY_CONTRACT")
        failures.append(
            "review rollout spawn lifecycle was not one success or one explicit childless failure followed by one success"
        )

    if (
        spawn_retry_contract_verified
        and len(candidate_records) == 1
        and int(evidence["completed_spawn_count"]) == 1
    ):
        review, record = candidate_records[0]
        reviewer_key = "sha256:" + str(record["reviewer_thread_sha256"])
        completed_reviews[reviewer_key] = review
        review_records = [record]
    else:
        review_records = []
        if len(candidate_records) > 1 or int(evidence["completed_spawn_count"]) > 1:
            failures.append("review rollout did not bind exactly one completed reviewer")
    evidence["rc_review_chain_count"] = len(completed_reviews)
    evidence["reviewer_owned_read_verified_count"] = len(completed_reviews)
    if review_records:
        evidence["review_record_sha256"] = sha256_bytes(
            json.dumps(
                review_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    if not completed_reviews:
        failures.append(
            "no rollout-bound spawn, child terminal/read, and bound delivery chain was verified"
        )
    evidence["review_chain_rejection_codes"] = sorted(rejection_codes)
    evidence["schema_failures"] = sorted(set(failures))
    return evidence, completed_reviews


def checked_artifact(fixture: Path, relative: PurePosixPath) -> Path:
    artifact = fixture.joinpath(*relative.parts)
    current = fixture
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"expected artifact traverses symlink: {relative}")
    if not artifact.resolve(strict=False).is_relative_to(fixture.resolve()):
        raise RuntimeError(f"expected artifact escaped fixture: {relative}")
    return artifact


def git_metadata_manifest(root: Path) -> dict[str, str]:
    """Hash every Git metadata entry across two mutation-stable scans."""
    try:
        root_fd = _open_directory_nofollow(root)
    except RuntimeError:
        raise RuntimeError("E_GIT_METADATA_MANIFEST") from None
    result: dict[str, str] | None = None
    failed = False
    try:
        root_before = os.fstat(root_fd)

        def scan_once() -> dict[str, str]:
            manifest: dict[str, str] = {}
            entry_count = 0
            total_bytes = 0

            def visit(
                directory_fd: int, prefix: tuple[str, ...], depth: int
            ) -> None:
                nonlocal entry_count, total_bytes
                if depth > MAX_GIT_METADATA_TREE_DEPTH:
                    raise RuntimeError("Git metadata tree exceeded the depth bound")
                directory_before = os.fstat(directory_fd)
                try:
                    with os.scandir(directory_fd) as entries:
                        names = sorted(entry.name for entry in entries)
                except OSError:
                    raise RuntimeError("Git metadata tree could not be enumerated") from None
                for name in names:
                    entry_count += 1
                    if entry_count > MAX_GIT_METADATA_TREE_ENTRIES:
                        raise RuntimeError("Git metadata tree exceeded the entry bound")
                    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                        raise RuntimeError("Git metadata tree contained an unsafe name")
                    try:
                        metadata = os.stat(
                            name, dir_fd=directory_fd, follow_symlinks=False
                        )
                    except OSError:
                        raise RuntimeError("Git metadata entry could not be inspected") from None
                    relative = PurePosixPath(*prefix, name)
                    if stat.S_ISLNK(metadata.st_mode):
                        raise RuntimeError("Git metadata tree contained a symlink")
                    if stat.S_ISDIR(metadata.st_mode):
                        child_fd = _open_directory_nofollow(name, dir_fd=directory_fd)
                        try:
                            opened = os.fstat(child_fd)
                            if stable_stat_signature(opened) != stable_stat_signature(
                                metadata
                            ):
                                raise RuntimeError(
                                    "Git metadata directory changed while opening"
                                )
                            visit(child_fd, (*prefix, name), depth + 1)
                            child_after = os.fstat(child_fd)
                        finally:
                            os.close(child_fd)
                        try:
                            rebound = os.stat(
                                name, dir_fd=directory_fd, follow_symlinks=False
                            )
                        except OSError:
                            raise RuntimeError(
                                "Git metadata directory name was rebound"
                            ) from None
                        if stable_stat_signature(rebound) != stable_stat_signature(
                            child_after
                        ):
                            raise RuntimeError("Git metadata directory name was rebound")
                        manifest[f"D:{relative}"] = json.dumps(
                            stable_stat_signature(child_after), separators=(",", ":")
                        )
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        raise RuntimeError("Git metadata tree contained a special file")
                    flags = (
                        os.O_RDONLY
                        | os.O_NOFOLLOW
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NONBLOCK", 0)
                    )
                    try:
                        file_fd = os.open(name, flags, dir_fd=directory_fd)
                    except OSError:
                        raise RuntimeError("Git metadata file could not be opened") from None
                    try:
                        before = os.fstat(file_fd)
                        if (
                            stable_stat_signature(before)
                            != stable_stat_signature(metadata)
                            or not stat.S_ISREG(before.st_mode)
                            or before.st_size < 0
                            or before.st_size > MAX_GIT_METADATA_FILE_BYTES
                        ):
                            raise RuntimeError("Git metadata file violated its size/type bound")
                        digest = hashlib.sha256()
                        size = 0
                        while chunk := os.read(
                            file_fd,
                            min(1024 * 1024, MAX_GIT_METADATA_FILE_BYTES + 1 - size),
                        ):
                            size += len(chunk)
                            total_bytes += len(chunk)
                            if (
                                size > MAX_GIT_METADATA_FILE_BYTES
                                or total_bytes > MAX_GIT_METADATA_TREE_BYTES
                            ):
                                raise RuntimeError("Git metadata tree exceeded its byte bound")
                            digest.update(chunk)
                        after = os.fstat(file_fd)
                        if (
                            stable_stat_signature(before)
                            != stable_stat_signature(after)
                            or size != after.st_size
                        ):
                            raise RuntimeError("Git metadata file changed while reading")
                        try:
                            rebound = os.stat(
                                name, dir_fd=directory_fd, follow_symlinks=False
                            )
                        except OSError:
                            raise RuntimeError(
                                "Git metadata file name was rebound"
                            ) from None
                        if stable_stat_signature(rebound) != stable_stat_signature(
                            after
                        ):
                            raise RuntimeError("Git metadata file name was rebound")
                        manifest[f"F:{relative}"] = json.dumps(
                            {
                                "metadata": stable_stat_signature(after),
                                "sha256": digest.hexdigest(),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    finally:
                        os.close(file_fd)
                try:
                    with os.scandir(directory_fd) as entries:
                        names_after = sorted(entry.name for entry in entries)
                except OSError:
                    raise RuntimeError("Git metadata tree could not be re-enumerated") from None
                directory_after = os.fstat(directory_fd)
                if (
                    names_after != names
                    or stable_stat_signature(directory_after)
                    != stable_stat_signature(directory_before)
                ):
                    raise RuntimeError("Git metadata directory changed while scanning")
                directory_key = PurePosixPath(*prefix) if prefix else PurePosixPath(".")
                manifest[f"D:{directory_key}"] = json.dumps(
                    stable_stat_signature(directory_after), separators=(",", ":")
                )

            visit(root_fd, (), 0)
            return manifest

        first = scan_once()
        second = scan_once()
        if first != second:
            raise RuntimeError("Git metadata tree was unstable across scans")
        root_after = os.fstat(root_fd)
        try:
            rebound = os.lstat(root)
        except OSError:
            raise RuntimeError("Git metadata root was rebound") from None
        if (
            stable_stat_signature(root_before) != stable_stat_signature(root_after)
            or stat.S_ISLNK(rebound.st_mode)
            or stable_stat_signature(rebound) != stable_stat_signature(root_after)
        ):
            raise RuntimeError("Git metadata root was rebound or changed")
        result = first
    except (OSError, RuntimeError, ValueError):
        failed = True
    try:
        os.close(root_fd)
    except OSError:
        failed = True
    if failed or result is None:
        raise RuntimeError("E_GIT_METADATA_MANIFEST") from None
    return result


def changed_paths(fixture: Path, git_executable: Path) -> set[str]:
    result = subprocess.run(
        [
            str(git_executable),
            "-c",
            f"core.excludesFile={os.devnull}",
            "-c",
            "status.showUntrackedFiles=all",
            "-C",
            str(fixture),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--no-renames",
        ],
        text=True,
        capture_output=True,
        check=True,
        env=helper_subprocess_env(),
    )
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            paths.add(path)
    return paths


def build_codex_command(
    codex_executable: Path,
    fixture: Path,
    final_path: Path,
    sandbox: str,
    model: str | None,
    reasoning_effort: str | None,
    shell_tool_path: str,
    prompt: str,
) -> list[str]:
    command = [
        str(codex_executable),
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-c",
        f'model_provider="{LOCKED_MODEL_PROVIDER}"',
        "--enable",
        "multi_agent",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "-c",
        "shell_environment_policy.inherit=none",
        "-c",
        f"shell_environment_policy.set.PATH={json.dumps(shell_tool_path)}",
        "-c",
        'shell_environment_policy.set.GIT_CONFIG_NOSYSTEM="1"',
        "-c",
        f"shell_environment_policy.set.GIT_CONFIG_GLOBAL={json.dumps(os.devnull)}",
        "-c",
        'shell_environment_policy.set.GIT_ATTR_NOSYSTEM="1"',
        "-c",
        'shell_environment_policy.set.GIT_OPTIONAL_LOCKS="0"',
        "--sandbox",
        sandbox,
        "--json",
        "--output-last-message",
        str(final_path),
        "-C",
        str(fixture),
    ]
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(
            ["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"]
        )
    command.append(prompt)
    return command


def process_group_exists(process_group_id: int) -> bool:
    if os.name != "posix" or not hasattr(os, "killpg"):
        raise RuntimeError("E_PROCESS_GROUP_UNSUPPORTED")
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_process_group_exit(process_group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process_group_exists(process_group_id):
        if time.monotonic() >= deadline:
            return False
        time.sleep(PROCESS_GROUP_POLL_SECONDS)
    return True


def terminate_process_group(
    process: subprocess.Popen[str],
) -> dict[str, bool]:
    """Terminate the POSIX process group; independently setsid children are out of scope."""
    process_group_id = process.pid
    attempted = True
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        return {"attempted": attempted, "verified": False}
    try:
        process.wait(timeout=PROCESS_GROUP_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    except OSError:
        return {"attempted": attempted, "verified": False}
    exited = wait_for_process_group_exit(
        process_group_id, PROCESS_GROUP_TERM_GRACE_SECONDS
    )
    if not exited:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            return {"attempted": attempted, "verified": False}
        try:
            process.wait(timeout=PROCESS_GROUP_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            return {"attempted": attempted, "verified": False}
        exited = wait_for_process_group_exit(
            process_group_id, PROCESS_GROUP_KILL_GRACE_SECONDS
        )
    try:
        process.wait(timeout=PROCESS_GROUP_KILL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return {"attempted": attempted, "verified": False}
    return {
        "attempted": attempted,
        "verified": exited
        and process.poll() is not None
        and not process_group_exists(process_group_id),
    }


def run_isolated_process_group(
    command: list[str], timeout: int | float, env: dict[str, str]
) -> dict[str, object]:
    """Run one case in a fresh POSIX session and verify process-group cleanup."""
    if os.name != "posix" or not hasattr(os, "killpg"):
        raise RuntimeError("E_PROCESS_GROUP_UNSUPPORTED")
    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except OSError:
        raise RuntimeError("E_CASE_PROCESS_START") from None
    timed_out = False
    cleanup_attempted = False
    cleanup_verified = False
    residual_detected = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        residual_detected = True
        cleanup = terminate_process_group(process)
        cleanup_attempted = cleanup["attempted"]
        cleanup_verified = cleanup["verified"]
        try:
            stdout, stderr = process.communicate(
                timeout=PROCESS_GROUP_KILL_GRACE_SECONDS
            )
        except (OSError, subprocess.TimeoutExpired):
            stdout, stderr = "", ""
            cleanup_verified = False
    except KeyboardInterrupt:
        cleanup = terminate_process_group(process)
        cleanup_attempted = cleanup["attempted"]
        cleanup_verified = cleanup["verified"]
        try:
            process.communicate(timeout=PROCESS_GROUP_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_verified = False
        if not cleanup_verified:
            raise RuntimeError("E_PROCESS_GROUP_CLEANUP_AFTER_INTERRUPT") from None
        raise
    except BaseException:
        cleanup = terminate_process_group(process)
        cleanup_attempted = cleanup["attempted"]
        cleanup_verified = cleanup["verified"]
        try:
            process.communicate(timeout=PROCESS_GROUP_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            cleanup_verified = False
        if not cleanup_verified:
            raise RuntimeError("E_PROCESS_GROUP_CLEANUP_AFTER_ERROR") from None
        raise
    else:
        residual_detected = process_group_exists(process.pid)
        if residual_detected:
            cleanup = terminate_process_group(process)
            cleanup_attempted = cleanup["attempted"]
            cleanup_verified = cleanup["verified"]
        else:
            cleanup_verified = process.poll() is not None
    return {
        "returncode": 124 if timed_out else process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "process_group_cleanup_attempted": cleanup_attempted,
        "process_group_cleanup_verified": cleanup_verified,
        "process_group_residual_detected": residual_detected,
    }


def run_case(
    case: dict[str, Any],
    fixture: Path,
    case_dir: Path,
    codex_executable: Path,
    codex_version_value: str,
    model: str | None,
    reasoning_effort: str | None,
    timeout: int,
    env: dict[str, str],
    auth_secrets: set[str],
    shell_tool_path: str,
    git_executable: Path,
) -> dict[str, object]:
    if case_dir.exists() or case_dir.is_symlink():
        raise RuntimeError(f"refusing to overwrite model-smoke case directory: {case_dir}")
    case_dir.mkdir(parents=True, mode=0o700)
    final_path = case_dir / "final.txt"
    write_new_text(final_path, "")
    sandbox = str(case.get("sandbox", "read-only"))
    if sandbox not in ALLOWED_SANDBOXES:
        raise RuntimeError(f"case {case['id']} requests unsafe sandbox {sandbox!r}")
    project_skill_root = fixture / ".agents" / "skills"
    discovery_skill_root = (
        project_skill_root
        if project_skill_root.is_dir()
        else Path(env["HOME"]) / ".agents" / "skills"
    )
    expected_skill_texts = {
        name: read_regular_nofollow(discovery_skill_root / name / "SKILL.md").decode(
            "utf-8"
        )
        for name in INSTALL_NAMES
    }
    command = build_codex_command(
        codex_executable,
        fixture,
        final_path,
        sandbox,
        model,
        reasoning_effort,
        shell_tool_path,
        str(case["prompt"]),
    )

    codex_home_path = Path(env["CODEX_HOME"])
    try:
        codex_home_before = os.lstat(codex_home_path)
    except OSError:
        raise RuntimeError("E_CODEX_HOME_ROOT_UNAVAILABLE") from None
    if stat.S_ISLNK(codex_home_before.st_mode) or not stat.S_ISDIR(
        codex_home_before.st_mode
    ):
        raise RuntimeError("E_CODEX_HOME_ROOT_UNSAFE")
    codex_home_identity = (
        codex_home_before.st_dev,
        codex_home_before.st_ino,
    )

    process_result = run_isolated_process_group(command, timeout, env)
    timed_out = process_result["timed_out"] is True
    process_group_cleanup_attempted = (
        process_result["process_group_cleanup_attempted"] is True
    )
    process_group_cleanup_verified = (
        process_result["process_group_cleanup_verified"] is True
    )
    process_group_residual_detected = (
        process_result["process_group_residual_detected"] is True
    )
    completed = subprocess.CompletedProcess(
        command,
        int(process_result["returncode"]),
        str(process_result["stdout"]),
        str(process_result["stderr"]),
    )
    raw_events = completed.stdout
    raw_stderr = completed.stderr
    if final_path.is_symlink():
        raw_final = ""
        final_path.unlink()
        final_output_unsafe = True
    else:
        raw_final = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
        final_output_unsafe = False
    raw_expected_skill_paths = {
        name: str(discovery_skill_root / name / "SKILL.md")
        for name in INSTALL_NAMES
    }
    review_artifact_mtime_ns: int | None = None
    review_artifact_ctime_ns: int | None = None
    if (
        case.get("require_collab_event") or case.get("require_collab_completion")
    ) and isinstance(case.get("expected_file"), str):
        try:
            review_relative = safe_relative_artifact(
                str(case["expected_file"]), str(case["id"])
            )
            review_artifact = checked_artifact(fixture, review_relative)
            review_metadata = os.lstat(review_artifact)
            if stat.S_ISREG(review_metadata.st_mode):
                review_artifact_mtime_ns = review_metadata.st_mtime_ns
                review_artifact_ctime_ns = review_metadata.st_ctime_ns
        except (OSError, RuntimeError):
            review_artifact_mtime_ns = None
            review_artifact_ctime_ns = None
    parsed = event_surface(
        raw_events, raw_final, expected_skill_texts, raw_expected_skill_paths
    )
    rollout_snapshot, rollout_snapshot_failures = snapshot_isolated_rollouts(
        codex_home_path, codex_home_identity
    )
    rollout_snapshot_evidence = {
        "source": "pre_run_root_identity_and_two_pass_open_dirfd_stable_snapshot",
        "file_count": len(rollout_snapshot),
        "total_bytes": sum(len(value) for value in rollout_snapshot.values()),
        "root_identity_reverified": not rollout_snapshot_failures,
        "stable_interval_verified": not rollout_snapshot_failures,
        "future_same_user_writer_excluded": False,
        "schema_failures": rollout_snapshot_failures,
    }
    rollout_auth = rollout_tree_auth_evidence(
        rollout_snapshot, auth_secrets
    )
    if rollout_snapshot_failures:
        auth_failures = rollout_auth.get("schema_failures")
        assert isinstance(auth_failures, list)
        auth_failures.extend(rollout_snapshot_failures)
    rollout_identity = rollout_identity_evidence(
        rollout_snapshot,
        str(parsed["main_thread_id_observed"])
        if parsed["main_thread_id_observed"] is not None
        else None,
        fixture,
        model,
        LOCKED_MODEL_PROVIDER,
        reasoning_effort,
        codex_version_value.removeprefix("codex-cli "),
    )
    rollout_spawn = rollout_spawn_evidence(
        rollout_snapshot,
        str(parsed["main_thread_id_observed"])
        if parsed["main_thread_id_observed"] is not None
        else None,
    )
    rollout_review: dict[str, object] | None = None
    rollout_completion: dict[str, object] | None = None
    rollout_completed_reviews: dict[str, dict[str, object]] = {}
    if case.get("require_collab_event"):
        rollout_review, rollout_completed_reviews = rollout_review_evidence(
            rollout_snapshot,
            str(parsed["main_thread_id_observed"])
            if parsed["main_thread_id_observed"] is not None
            else None,
            fixture,
            str(case.get("expected_file", "")),
            str(case.get("expected_text", "")),
            str(case.get("expected_file_content", "")),
            raw_final,
            str(case.get("review_evidence_marker", "")),
            str(case.get("expected_boot_receipt", "")),
            review_artifact_mtime_ns,
            review_artifact_ctime_ns,
            model,
            LOCKED_MODEL_PROVIDER,
            reasoning_effort,
            codex_version_value.removeprefix("codex-cli "),
            auth_secrets,
            raw_expected_skill_paths[SKILL_NAME],
            expected_skill_texts[SKILL_NAME],
        )
    if case.get("require_collab_completion"):
        rollout_completion = rollout_collab_completion_evidence(
            rollout_snapshot,
            str(parsed["main_thread_id_observed"])
            if parsed["main_thread_id_observed"] is not None
            else None,
            fixture,
            str(case.get("expected_file", "")),
            str(case.get("expected_text", "")),
            raw_final,
            str(case.get("expected_boot_receipt", "")),
            review_artifact_mtime_ns,
            review_artifact_ctime_ns,
            model,
            LOCKED_MODEL_PROVIDER,
            reasoning_effort,
            codex_version_value.removeprefix("codex-cli "),
            auth_secrets,
        )
    _, rollout_identity_leak = redact_exact_auth_values(
        json.dumps(rollout_identity, ensure_ascii=False, sort_keys=True), auth_secrets
    )
    rollout_review_leak = bool(
        rollout_review
        and (
            rollout_review.get("auth_exact_value_leak_detected") is True
            or redact_exact_auth_values(
                json.dumps(rollout_review, ensure_ascii=False, sort_keys=True),
                auth_secrets,
            )[1]
        )
    )
    rollout_completion_leak = bool(
        rollout_completion
        and (
            rollout_completion.get("auth_exact_value_leak_detected") is True
            or redact_exact_auth_values(
                json.dumps(rollout_completion, ensure_ascii=False, sort_keys=True),
                auth_secrets,
            )[1]
        )
    )
    rollout_auth_leak = rollout_auth.get("auth_exact_value_leak_detected") is True

    events_text, events_leak = redact_jsonl_auth_values(raw_events, auth_secrets)
    stderr_text, stderr_leak = redact_exact_auth_values(raw_stderr, auth_secrets)
    final_text, final_leak = redact_exact_auth_values(raw_final, auth_secrets)
    path_replacements = build_local_path_replacements(
        [
            (str(case_dir.parent), "<RECEIPT_ROOT>"),
            (str(fixture), "<FIXTURE>"),
            (str(codex_executable), "<CODEX_EXECUTABLE>"),
            (env.get("HOME", ""), "<EVAL_HOME>"),
            (env.get("CODEX_HOME", ""), "<EVAL_CODEX_HOME>"),
            (
                shell_tool_path.split(os.pathsep, 1)[0],
                "<PRIVATE_TOOL_BIN>",
            ),
        ]
    )
    events_text = redact_local_paths(events_text, path_replacements)
    stderr_text = redact_local_paths(stderr_text, path_replacements)
    final_text = redact_local_paths(final_text, path_replacements)
    runtime_review_marker = str(case.get("review_evidence_marker", ""))
    if runtime_review_marker:
        events_text = events_text.replace(
            runtime_review_marker, "[REDACTED_RUNTIME_REVIEW_MARKER]"
        )
        persisted_final_text = final_text.replace(
            runtime_review_marker, "[REDACTED_RUNTIME_REVIEW_MARKER]"
        )
    else:
        persisted_final_text = final_text
    if final_path.exists():
        final_path.write_text(persisted_final_text, encoding="utf-8")
    write_new_text(case_dir / "events.jsonl", events_text)
    write_new_text(case_dir / "stderr.txt", stderr_text)
    surface = str(parsed["surface"])
    assistant_messages = parsed["assistant_messages"]
    assert isinstance(assistant_messages, list)
    assistant_message_events = parsed["assistant_message_events"]
    assistant_message_contract_attempts = parsed[
        "assistant_message_contract_attempts"
    ]
    skill_load_events_by_name = parsed["skill_load_events_by_name"]
    skill_load_attempts_by_name = parsed["skill_load_attempts_by_name"]
    skill_preload_actions_by_name = parsed["skill_preload_actions_by_name"]
    skill_touch_attempt_ids_by_name = parsed["skill_touch_attempt_ids_by_name"]
    skill_touch_first_event_indexes_by_name = parsed[
        "skill_touch_first_event_indexes_by_name"
    ]
    valid_skill_read_attempt_ids_by_name = parsed[
        "valid_skill_read_attempt_ids_by_name"
    ]
    skill_location_failure_attempt_ids_by_name = parsed[
        "skill_location_failure_attempt_ids_by_name"
    ]
    skill_location_failure_action_indexes_by_name = parsed[
        "skill_location_failure_action_indexes_by_name"
    ]
    tool_attempt_order = parsed["tool_attempt_order"]
    action_event_indexes = parsed["action_event_indexes"]
    successful_tool_event_indexes = parsed["successful_tool_event_indexes"]
    assert isinstance(assistant_message_events, list)
    assert isinstance(assistant_message_contract_attempts, list)
    assert isinstance(skill_load_events_by_name, dict)
    assert isinstance(skill_load_attempts_by_name, dict)
    assert isinstance(skill_preload_actions_by_name, dict)
    assert isinstance(skill_touch_attempt_ids_by_name, dict)
    assert isinstance(skill_touch_first_event_indexes_by_name, dict)
    assert isinstance(valid_skill_read_attempt_ids_by_name, dict)
    assert isinstance(skill_location_failure_attempt_ids_by_name, dict)
    assert isinstance(skill_location_failure_action_indexes_by_name, dict)
    assert isinstance(tool_attempt_order, list)
    assert isinstance(action_event_indexes, list)
    assert isinstance(successful_tool_event_indexes, list)
    runtime_skill_name = expected_skill_name(case)
    guard_skill_name = allowed_guard_skill_name(case)
    skill_load_event_indexes = (
        skill_load_events_by_name.get(runtime_skill_name, [])
        if runtime_skill_name is not None
        else []
    )
    skill_load_attempt_event_indexes = (
        skill_load_attempts_by_name.get(runtime_skill_name, [])
        if runtime_skill_name is not None
        else []
    )
    skill_preload_action_event_indexes = (
        skill_preload_actions_by_name.get(runtime_skill_name, [])
        if runtime_skill_name is not None
        else []
    )
    skill_location_failure_action_indexes = (
        skill_location_failure_action_indexes_by_name.get(runtime_skill_name, [])
        if runtime_skill_name is not None
        else []
    )
    assert isinstance(skill_load_event_indexes, list)
    assert isinstance(skill_load_attempt_event_indexes, list)
    assert isinstance(skill_preload_action_event_indexes, list)
    assert isinstance(skill_location_failure_action_indexes, list)
    boot_sequence = boot_sequence_evidence(
        case,
        assistant_message_events,
        [int(index) for index in skill_load_event_indexes],
        [int(index) for index in action_event_indexes],
        [int(index) for index in skill_preload_action_event_indexes],
        [int(index) for index in skill_location_failure_action_indexes],
    )
    top_level_failures = parsed["top_level_failures"]
    terminal_events = parsed["terminal_events"]
    assert isinstance(top_level_failures, list)
    assert isinstance(terminal_events, list)
    recoverable_execution_warnings, fatal_top_level_failures = (
        partition_top_level_failures(
            [str(item) for item in top_level_failures],
            [str(item) for item in terminal_events],
            completed.returncode,
            timed_out,
            [int(item) for item in parsed["top_level_failure_event_indexes"]],
            [int(item) for item in parsed["terminal_event_indexes"]],
        )
    )
    failure_class = classify_external_failure(
        fatal_top_level_failures, stderr_text
    )
    fatal_execution_event = (
        bool(fatal_top_level_failures) or timed_out or failure_class is not None
    )
    if timed_out:
        failure_class = "external_case_timeout"
    if fatal_execution_event and failure_class is None:
        failure_class = "external_execution_error"
    inconclusive_external = fatal_execution_event
    schema_failures: list[str] = []
    collab_schema_failures = parsed["collab_schema_failures"]
    tool_schema_failures = parsed["tool_schema_failures"]
    assert isinstance(collab_schema_failures, list)
    assert isinstance(tool_schema_failures, list)
    schema_failures.extend(str(item) for item in collab_schema_failures)
    schema_failures.extend(str(item) for item in tool_schema_failures)
    if parsed["main_thread_id_observed"] is None:
        schema_failures.append("Codex JSONL did not expose one main thread id")
    if int(parsed["invalid_json_line_count"]) != 0:
        schema_failures.append("Codex JSONL contained malformed non-empty lines")
    if int(parsed["non_object_json_record_count"]) != 0:
        schema_failures.append("Codex JSONL contained non-object event records")
    if len(terminal_events) != 1:
        schema_failures.append(
            "Codex JSONL did not contain exactly one turn terminal event"
        )
    if int(parsed["post_terminal_event_count"]) != 0:
        schema_failures.append("Codex JSONL contained lifecycle events after turn terminal")
    if terminal_events and terminal_events[-1] == "turn.failed" and not top_level_failures:
        schema_failures.append("turn.failed lacked a structured top-level error")

    observed_case_models = rollout_identity["observed_models"]
    observed_case_providers = rollout_identity["observed_providers"]
    observed_case_efforts = rollout_identity["observed_reasoning_efforts"]
    observed_case_cli_versions = rollout_identity["observed_cli_versions"]
    rollout_schema_failures = rollout_identity["schema_failures"]
    exec_jsonl_observed_models = parsed["observed_models"]
    exec_jsonl_observed_providers = parsed["observed_providers"]
    assert isinstance(observed_case_models, list)
    assert isinstance(observed_case_providers, list)
    assert isinstance(observed_case_efforts, list)
    assert isinstance(observed_case_cli_versions, list)
    assert isinstance(rollout_schema_failures, list)
    assert isinstance(exec_jsonl_observed_models, list)
    assert isinstance(exec_jsonl_observed_providers, list)

    identity_failures: list[str] = []
    exec_json_main_message_contract_required = bool(
        case.get("require_collab_event")
        or case.get("require_collab_completion")
    )
    exec_json_main_message_contract_verified = (
        not exec_json_main_message_contract_required
    )
    if inconclusive_external:
        external_messages = {
            "external_usage_limit": (
                "external usage limit prevented conclusive behavior evaluation"
            ),
            "external_model_unavailable": (
                "requested model is unavailable for this Codex account"
            ),
            "external_model_capacity": (
                "requested model was temporarily at capacity"
            ),
            "external_client_incompatible": (
                "Codex client compatibility prevented behavior evaluation"
            ),
            "external_case_timeout": "Codex case exceeded the configured timeout",
        }
        failures = [
            external_messages.get(
                str(failure_class),
                "external execution failure prevented conclusive behavior evaluation",
            )
        ]
    else:
        failures = contract_failures(
            case,
            surface,
            assistant_messages=[str(message) for message in assistant_messages],
            collab_tool_events=int(parsed["collab_tool_attempts"]),
            assistant_message_events=assistant_message_events,
            skill_load_event_indexes=[
                int(index) for index in skill_load_event_indexes
            ],
            action_event_indexes=[int(index) for index in action_event_indexes],
            skill_preload_action_event_indexes=[
                int(index) for index in skill_preload_action_event_indexes
            ],
            skill_load_events_by_name=skill_load_events_by_name,
            skill_preload_actions_by_name=skill_preload_actions_by_name,
            skill_touch_attempt_ids_by_name=skill_touch_attempt_ids_by_name,
            skill_touch_first_event_indexes_by_name=(
                skill_touch_first_event_indexes_by_name
            ),
            valid_skill_read_attempt_ids_by_name=(
                valid_skill_read_attempt_ids_by_name
            ),
            skill_location_failure_attempt_ids_by_name=(
                skill_location_failure_attempt_ids_by_name
            ),
            skill_location_failure_action_indexes_by_name=(
                skill_location_failure_action_indexes_by_name
            ),
            tool_attempt_order=[str(value) for value in tool_attempt_order],
            context_budget_overflow=(
                int(parsed["skills_context_budget_overflow_count"]) > 0
            ),
            final_text=final_text,
            tool_events=int(parsed["tool_events"]),
            tool_attempts=int(parsed["tool_attempts"]),
        )
        failures.extend(schema_failures)
        if exec_json_main_message_contract_required:
            exec_json_main_message_contract_verified = (
                exec_json_main_message_contract_valid(
                    [
                        attempt
                        for attempt in assistant_message_contract_attempts
                        if isinstance(attempt, dict)
                    ],
                    raw_final,
                    str(case.get("expected_boot_receipt", "")),
                )
                and len(
                    [
                        attempt
                        for attempt in assistant_message_contract_attempts
                        if isinstance(attempt, dict)
                    ]
                )
                == len(assistant_message_contract_attempts)
            )
            if not exec_json_main_message_contract_verified:
                failures.append(
                    "exec JSON assistant messages violated the closed collaboration contract"
                )
        identity_failures = execution_identity_failures(
            model,
            [str(value) for value in observed_case_models],
            [str(value) for value in observed_case_providers],
            requested_reasoning_effort=reasoning_effort,
            observed_reasoning_efforts=[str(value) for value in observed_case_efforts],
            expected_cli_version=codex_version_value.removeprefix("codex-cli "),
            observed_cli_versions=[str(value) for value in observed_case_cli_versions],
            evidence_schema_failures=[str(value) for value in rollout_schema_failures],
        )
        if exec_jsonl_observed_models and exec_jsonl_observed_models != observed_case_models:
            identity_failures.append(
                "exec JSONL model identity conflicted with the bound main rollout"
            )
        if (
            exec_jsonl_observed_providers
            and exec_jsonl_observed_providers != observed_case_providers
        ):
            identity_failures.append(
                "exec JSONL provider identity conflicted with the bound main rollout"
            )
        failures.extend(identity_failures)
        if completed.returncode != 0:
            failures.append(f"codex exit code {completed.returncode}")
    if final_output_unsafe:
        failures.append("final output path was replaced by a symlink")
    if not process_group_cleanup_verified:
        failures.append("process-group cleanup was not verified")
    if not inconclusive_external:
        for marker in case.get("must_contain", []):
            if marker not in surface:
                failures.append(f"assistant output missing {marker!r}")
        for marker in case.get("must_not_contain", []):
            if marker in surface:
                failures.append(f"assistant output unexpectedly contains {marker!r}")
        if case.get("require_tool_event") and parsed["tool_events"] == 0:
            failures.append("no completed tool event observed")
        if case.get("require_collab_spawn") and (
            rollout_spawn.get("completed_spawn_count") != 1
            or rollout_spawn.get("context_isolation_requested_count") != 1
            or rollout_spawn.get("schema_failures") != []
        ):
            failures.append(
                "no unique rollout-bound native collaboration spawn was verified"
            )
        if case.get("require_collab_completion") and (
            not rollout_completion
            or rollout_completion.get("completion_chain_count") != 1
            or rollout_completion.get("schema_failures") != []
        ):
            failures.append(
                "no unique rollout-bound natural collaboration completion/adoption chain was verified"
            )
    if (
        events_leak
        or stderr_leak
        or final_leak
        or rollout_identity_leak
        or rollout_review_leak
        or rollout_completion_leak
        or rollout_auth_leak
    ):
        failures.append("exact auth value appeared in model output and was redacted")
    rollout_auth_failures = rollout_auth.get("schema_failures", [])
    if isinstance(rollout_auth_failures, list):
        failures.extend(
            f"rollout auth evidence: {failure}"
            for failure in rollout_auth_failures
        )
    if rollout_review is not None and not inconclusive_external:
        review_rollout_failures = rollout_review.get("schema_failures", [])
        if isinstance(review_rollout_failures, list):
            failures.extend(
                f"review rollout evidence: {failure}"
                for failure in review_rollout_failures
            )
    if rollout_completion is not None and not inconclusive_external:
        completion_failures = rollout_completion.get("schema_failures", [])
        if isinstance(completion_failures, list):
            failures.extend(
                f"collaboration completion evidence: {failure}"
                for failure in completion_failures
            )

    expected_file = case.get("expected_file")
    expected_text = case.get("expected_text")
    expected_file_content = case.get("expected_file_content")
    review_evidence_marker = case.get("review_evidence_marker")
    artifact_text = ""
    artifact_leak = False
    expected_relative: PurePosixPath | None = None
    if (
        not inconclusive_external
        and isinstance(expected_file, str)
        and isinstance(expected_text, str)
    ):
        expected_relative = safe_relative_artifact(expected_file, str(case["id"]))
        artifact = checked_artifact(fixture, expected_relative)
        if not artifact.is_file():
            failures.append(f"expected artifact missing: {expected_file}")
        else:
            raw_artifact_text = artifact.read_text(encoding="utf-8")
            artifact_text, artifact_leak = redact_exact_auth_values(raw_artifact_text, auth_secrets)
            if artifact_leak:
                failures.append("exact auth value appeared in expected artifact")
            if expected_text not in artifact_text:
                failures.append(f"expected artifact text missing from {expected_file}")
            if (
                isinstance(expected_file_content, str)
                and artifact_text != expected_file_content
            ):
                failures.append(f"expected artifact exact content mismatch: {expected_file}")
            for forbidden in case.get("forbidden_file_texts", []):
                if forbidden in artifact_text:
                    failures.append(
                        f"forbidden old artifact text remains in {expected_file}: {forbidden!r}"
                    )
        actual_changed = changed_paths(fixture, git_executable)
        if actual_changed != {expected_file}:
            failures.append(
                f"unexpected final changed files: expected {[expected_file]!r}, "
                f"observed {sorted(actual_changed)!r}"
            )
        diff_check = subprocess.run(
            [str(git_executable), "-C", str(fixture), "diff", "--check"],
            text=True,
            capture_output=True,
            check=False,
            env=helper_subprocess_env(),
        )
        if diff_check.returncode != 0:
            failures.append("git diff --check failed for expected artifact")

    parsed_completed_reviews = parsed["reviews_completed"]
    assert isinstance(parsed_completed_reviews, dict)
    # The public exec event surface is diagnostic only. Release evidence must
    # come from the uniquely bound main+child rollout chain.
    completed_reviews = (
        rollout_completed_reviews
        if case.get("require_collab_event")
        else parsed_completed_reviews
    )
    review_ids: list[str] = []
    different_agent_review_ids: list[str] = []
    context_verified_review_ids: list[str] = []
    isolated_hidden_marker_readback_ids: list[str] = []
    reviewer_owned_read_ids: list[str] = []
    review_prompt_self_contained = False
    review_prompt_content_verified = False
    review_marker_nonforwarding_verified = False
    review_packet_behaviorally_verified = False
    review_result_adoption_verified = False
    unsupported_reviewer_claim_detected = False
    review_chain_rejection_codes = {
        str(code)
        for code in (rollout_review or {}).get(
            "review_chain_rejection_codes", []
        )
        if isinstance(code, str)
    }
    review_evidence_tier = str(case.get("review_evidence_tier", ""))
    if not inconclusive_external and case.get("require_collab_event"):
        if not completed_reviews:
            failures.append(
                "no spawn -> child terminal/read -> bound delivery chain observed"
            )
        for receiver_id, review in completed_reviews.items():
            if not isinstance(review, dict):
                continue
            prompt = str(review.get("prompt", ""))
            message = str(review.get("message", ""))
            sender_id = review.get("sender_thread_id")
            if receiver_id == sender_id:
                continue
            if expected_text and expected_text not in message:
                continue
            if review_evidence_marker and review_evidence_marker in prompt:
                continue
            if review_evidence_marker and review_evidence_marker not in message:
                continue
            prompt_is_self_contained = review_prompt_is_self_contained(
                prompt,
                str(expected_file),
                str(expected_text),
                review_evidence_marker,
            )
            packet_behaviorally_verified = (
                review.get("review_packet_behaviorally_verified") is True
            )
            review_prompt_self_contained = (
                review_prompt_self_contained or prompt_is_self_contained
            )
            prompt_content_verified = (
                review.get("review_prompt_content_verified") is True
            )
            marker_nonforwarding_verified = (
                review.get("review_marker_nonforwarding_verified") is True
            )
            review_prompt_content_verified = (
                review_prompt_content_verified or prompt_content_verified
            )
            review_marker_nonforwarding_verified = (
                review_marker_nonforwarding_verified
                or marker_nonforwarding_verified
            )
            review_packet_behaviorally_verified = (
                review_packet_behaviorally_verified
                or packet_behaviorally_verified
            )
            if not prompt_is_self_contained and not packet_behaviorally_verified:
                continue
            if "COS_BOOT_RECEIPT" in message:
                continue
            if review.get("post_change_artifact_read_verified") is not True:
                spawn_index = int(review.get("spawn_event_index", -1))
                last_file_change = int(parsed["last_file_change_event_index"])
                if last_file_change < 0 or spawn_index <= last_file_change:
                    continue
            different_agent_review_ids.append(receiver_id)
            if review.get("reviewer_owned_file_read_verified") is True:
                reviewer_owned_read_ids.append(receiver_id)
            if review.get("context_isolation_verified") is True:
                context_verified_review_ids.append(receiver_id)
                if (
                    review.get("reviewer_owned_file_read_verified") is True
                    and marker_nonforwarding_verified
                ):
                    isolated_hidden_marker_readback_ids.append(receiver_id)
                    review_ids.append(receiver_id)
        if not different_agent_review_ids:
            failures.append(
                "different reviewer result did not prove a post-change artifact readback"
            )
            if claims_external_reviewer_result(final_text):
                unsupported_reviewer_claim_detected = True
                review_chain_rejection_codes.add(
                    "E_REVIEW_UNSUPPORTED_EXTERNAL_CLAIM"
                )
                failures.append(
                    "final answer claimed an external reviewer result without an observed review chain"
                )
        elif not final_adopts_review_evidence(
            final_text,
            str(review_evidence_marker or ""),
            str(expected_text or ""),
        ):
            review_chain_rejection_codes.add("E_REVIEW_FINAL_ADOPTION")
            failures.append(
                "final answer did not adopt the observed reviewer marker and result"
            )
        else:
            review_result_adoption_verified = True
        if review_evidence_tier == "stable" and not context_verified_review_ids:
            failures.append(
                "review spawn completion did not expose verified context isolation"
            )
        if review_evidence_tier == "stable" and not reviewer_owned_read_ids:
            failures.append(
                "reviewer-owned artifact read was not verified"
            )
        if review_evidence_tier == "stable" and not review_ids:
            failures.append("cold review was not verified")
        if different_agent_review_ids and not context_verified_review_ids:
            if COLD_CONTEXT_ISOLATION_UNVERIFIED not in final_text:
                failures.append(
                    "review context isolation was not observable and final answer did not disclose it"
                )
        if different_agent_review_ids and not reviewer_owned_read_ids:
            if "reviewer-owned read 未验证" not in final_text:
                failures.append(
                    "reviewer-owned read was not observable and final answer did not disclose it"
                )
        if different_agent_review_ids and not review_ids and claims_passing_cold_review(
            final_text
        ):
            failures.append(
                "final answer upgraded incomplete review evidence to a passing cold review"
            )

    observed_models = observed_case_models
    observed_providers = observed_case_providers
    non_identity_failures = [
        failure for failure in failures if failure not in identity_failures
    ]
    return {
        "id": case["id"],
        "status": (
            "inconclusive_external"
            if inconclusive_external
            else ("passed" if not failures else "failed")
        ),
        "failures": failures,
        "execution_identity_failures": identity_failures,
        "non_identity_failures": non_identity_failures,
        "contract_except_execution_identity_verified": (
            not inconclusive_external and not non_identity_failures
        ),
        "failure_class": failure_class,
        "inconclusive_external": inconclusive_external,
        "timed_out": timed_out,
        "process_group_cleanup_attempted": process_group_cleanup_attempted,
        "process_group_cleanup_verified": process_group_cleanup_verified,
        "process_group_residual_detected": process_group_residual_detected,
        "process_group_scope": "posix_session_process_group_excluding_independent_setsid_escapees",
        "event_schema_failures": schema_failures,
        "invalid_json_line_count": parsed["invalid_json_line_count"],
        "non_object_json_record_count": parsed["non_object_json_record_count"],
        "post_terminal_event_count": parsed["post_terminal_event_count"],
        "terminal_events": terminal_events,
        "recoverable_execution_warnings": recoverable_execution_warnings,
        "fatal_top_level_failure_count": len(fatal_top_level_failures),
        "configuration_request_accepted": parsed["main_thread_id_observed"]
        is not None,
        "exit_code": completed.returncode,
        "declared_contract": {
            "should_trigger": case["should_trigger"],
            "mode": case["mode"],
            "collaboration": case["collaboration"],
            "activation": case["activation"],
            "expected_entrypoint": case.get("expected_entrypoint"),
            "allowed_guard_bundle": case.get("allowed_guard_bundle", "none"),
            "allow_preload_announcement": case.get(
                "allow_preload_announcement", False
            ),
            "require_collab_completion": case.get(
                "require_collab_completion", False
            ),
        },
        "tool_events_completed": parsed["tool_events"],
        "tool_attempts": parsed["tool_attempts"],
        "collab_tool_attempts": parsed["collab_tool_attempts"],
        "collab_tool_events_completed": parsed["collab_tool_events_completed"],
        "collab_spawns_completed": max(
            len(parsed["spawn_completed"]),
            int(rollout_spawn.get("completed_spawn_count", 0)),
            int((rollout_review or {}).get("completed_spawn_count", 0)),
            int((rollout_completion or {}).get("completed_spawn_count", 0)),
        ),
        "collab_completion_verified": bool(
            rollout_completion
            and rollout_completion.get("completion_chain_count") == 1
            and rollout_completion.get("schema_failures") == []
        ),
        "review_evidence_tier": review_evidence_tier or None,
        "rc_review_chain_verified": bool(different_agent_review_ids),
        "different_agent_reviewer_results_completed": len(
            different_agent_review_ids
        ),
        "reviewer_results_completed": len(review_ids),
        "cold_context_isolation_verified_count": len(context_verified_review_ids),
        "isolated_hidden_marker_readback_count": len(
            isolated_hidden_marker_readback_ids
        ),
        "reviewer_owned_read_verified_count": len(reviewer_owned_read_ids),
        "reviewer_owned_tool_trace_schema_observed": bool(
            rollout_review
            and rollout_review.get("reviewer_owned_read_verified_count", 0)
        ),
        "cold_review_verified": bool(review_ids),
        "review_receiver_ids": review_ids,
        "review_prompt_self_contained": review_prompt_self_contained,
        "review_prompt_content_verified": review_prompt_content_verified,
        "review_marker_nonforwarding_verified": (
            review_marker_nonforwarding_verified
        ),
        "review_packet_behaviorally_verified": (
            review_packet_behaviorally_verified
        ),
        "review_result_adoption_verified": review_result_adoption_verified,
        "unsupported_reviewer_claim_detected": (
            unsupported_reviewer_claim_detected
        ),
        "review_chain_terminal_stage": (rollout_review or {}).get(
            "review_chain_terminal_stage"
        ),
        "review_chain_rejection_codes": sorted(review_chain_rejection_codes),
        "observed_models": observed_models,
        "observed_providers": observed_providers,
        "observed_reasoning_efforts": observed_case_efforts,
        "execution_identity_source": rollout_identity["source"],
        "rollout_identity_evidence": rollout_identity,
        "rollout_spawn_evidence": rollout_spawn,
        "rollout_review_evidence": rollout_review,
        "rollout_collab_completion_evidence": rollout_completion,
        "rollout_snapshot_evidence": rollout_snapshot_evidence,
        "raw_rollout_auth_evidence": rollout_auth,
        "exec_jsonl_observed_models": exec_jsonl_observed_models,
        "exec_jsonl_observed_providers": exec_jsonl_observed_providers,
        "exec_json_main_message_contract_required": (
            exec_json_main_message_contract_required
        ),
        "exec_json_main_message_contract_verified": (
            exec_json_main_message_contract_verified
        ),
        "exec_json_main_message_attempt_count": len(
            assistant_message_contract_attempts
        ),
        "boot_sequence_verified": boot_sequence["valid"] is True,
        "boot_message_position": boot_sequence["boot_message_position"],
        "preload_announcement_verified": boot_sequence[
            "preload_announcement_verified"
        ],
        "preload_message_count": boot_sequence["preload_message_count"],
        "canonical_skill_load_events_completed": len(
            skill_load_events_by_name.get(SKILL_NAME, [])
        ),
        "legacy_skill_load_events_completed": len(
            skill_load_events_by_name.get(LEGACY_SKILL_NAME, [])
        ),
        "expected_skill_name": runtime_skill_name,
        "expected_skill_load_events_completed": len(skill_load_event_indexes),
        "expected_skill_load_attempts_completed": len(
            skill_load_attempt_event_indexes
        ),
        "expected_skill_preload_actions_completed": len(
            skill_preload_action_event_indexes
        ),
        "expected_skill_location_failure_attempts": len(
            skill_location_failure_attempt_ids_by_name.get(runtime_skill_name, [])
            if runtime_skill_name is not None
            else []
        ),
        "guard_skill_name": guard_skill_name,
        "guard_skill_touch_attempts": len(
            skill_touch_attempt_ids_by_name.get(guard_skill_name, [])
            if guard_skill_name is not None
            else []
        ),
        "guard_skill_valid_read_attempts": len(
            valid_skill_read_attempt_ids_by_name.get(guard_skill_name, [])
            if guard_skill_name is not None
            else []
        ),
        "guard_skill_load_events_completed": len(
            skill_load_events_by_name.get(guard_skill_name, [])
            if guard_skill_name is not None
            else []
        ),
        "skill_load_verification_method": "exact_full_skill_output_match",
        "boot_receipt_is_first_assistant_message": bool(assistant_messages)
        and str(assistant_messages[0]).lstrip().startswith("COS_BOOT_RECEIPT"),
        "first_assistant_message_sha256": (
            sha256_bytes(str(assistant_messages[0]).encode())
            if assistant_messages
            else None
        ),
        "auth_exact_value_leak_detected": (
            events_leak
            or stderr_leak
            or final_leak
            or artifact_leak
            or rollout_identity_leak
            or rollout_review_leak
            or rollout_completion_leak
            or rollout_auth_leak
        ),
        "raw_rollout_auth_scan_verified": (
            rollout_auth.get("schema_failures") == []
            and rollout_auth.get("auth_exact_value_leak_detected") is False
        ),
        "review_marker_runtime_randomized": bool(
            case.get("_review_marker_runtime_randomized")
        ),
        "skills_context_budget_overflow_observed": (
            int(parsed["skills_context_budget_overflow_count"]) > 0
        ),
        "skills_context_budget_overflow_count": int(
            parsed["skills_context_budget_overflow_count"]
        ),
        "prompt_sha256": sha256_bytes(str(case["prompt"]).encode()),
        "events_sha256": sha256_bytes(events_text.encode()),
        "final_sha256": sha256_bytes(persisted_final_text.encode()),
        "expected_artifact_sha256": sha256_bytes(artifact_text.encode())
        if expected_relative is not None and artifact_text
        else None,
        "artifact_dir": case_dir.name,
    }


def agents_context_evidence(
    project_root: Path, home: Path, codex_home: Path
) -> list[dict[str, object]]:
    """Hash every plausible AGENTS context without treating it as a router."""
    candidates = (
        (project_root / "AGENTS.md", "<PROJECT>/AGENTS.md"),
        (project_root / "AGENTS.override.md", "<PROJECT>/AGENTS.override.md"),
        (codex_home / "AGENTS.md", "<CODEX_HOME>/AGENTS.md"),
        (codex_home / "AGENTS.override.md", "<CODEX_HOME>/AGENTS.override.md"),
        (home / ".codex" / "AGENTS.md", "<HOME_CODEX>/AGENTS.md"),
        (
            home / ".codex" / "AGENTS.override.md",
            "<HOME_CODEX>/AGENTS.override.md",
        ),
    )
    evidence: list[dict[str, object]] = []
    unique_candidates: dict[Path, str] = {}
    for path, label in candidates:
        unique_candidates.setdefault(path, label)
    for path, label in unique_candidates.items():
        if path.is_symlink():
            raise RuntimeError(f"refusing symlink AGENTS context: {path}")
        if not path.exists():
            evidence.append({"path": label, "exists": False})
            continue
        if not path.is_file():
            raise RuntimeError(f"AGENTS context must be a regular file: {path}")
        content = read_regular_nofollow(path)
        text = content.decode("utf-8", errors="replace")
        routing_markers = sorted(
            name
            for name in INSTALL_NAMES
            if name in text or f"BEGIN {name} routing" in text
        )
        if routing_markers:
            raise RuntimeError(
                f"contaminated AGENTS context: {path} contains {', '.join(routing_markers)}"
            )
        evidence.append(
            {
                "path": label,
                "exists": True,
                "sha256": sha256_bytes(content),
                "size_bytes": len(content),
                "routing_markers": [],
            }
        )
    return evidence


def check_contamination(root: Path) -> None:
    # This is an early package-context guard. Per-case evidence below records the
    # exact project/HOME/CODEX_HOME contexts used by the evaluated process.
    account_home = os_account_home()
    agents_context_evidence(root, account_home, account_home / ".codex")


def codex_version(codex_executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(codex_executable), "--version"],
            text=True,
            capture_output=True,
            check=True,
            env=helper_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("E_CODEX_VERSION_PROBE") from None
    version = result.stdout.strip()
    if "\n" in version or not re.fullmatch(r"codex-cli [0-9A-Za-z.+-]+", version):
        raise RuntimeError(f"unexpected Codex version output: {version!r}")
    return version


class OutputStaging:
    """Build a private receipt beside its destination and atomically promote it."""

    def __init__(self, path: Path) -> None:
        expanded = path.expanduser()
        if expanded.is_symlink():
            raise RuntimeError("E_OUTPUT_FINAL_SYMLINK")
        self.final_path = expanded.resolve(strict=False)
        if not self.final_path.name:
            raise RuntimeError("E_OUTPUT_FINAL_INVALID")
        self.final_path.parent.mkdir(parents=True, exist_ok=True)
        if self.final_path.exists() or self.final_path.is_symlink():
            raise RuntimeError("E_OUTPUT_FINAL_EXISTS")
        self.path = Path(
            tempfile.mkdtemp(
                prefix=f".{self.final_path.name}.staging-",
                dir=self.final_path.parent,
            )
        )
        self.path.chmod(0o700)
        self.promoted = False
        self.invalid_sealed = False

    def __enter__(self) -> "OutputStaging":
        return self

    def promote(self) -> None:
        summary_path = self.path / "summary.json"
        try:
            summary_bytes = read_regular_nofollow(summary_path)
            summary = json.loads(summary_bytes)
        except (RuntimeError, json.JSONDecodeError, UnicodeDecodeError):
            raise RuntimeError("E_OUTPUT_SUMMARY_INCOMPLETE") from None
        if (
            not summary_bytes.endswith(b"\n")
            or not isinstance(summary, dict)
            or summary.get("receipt_type") != "MODEL_SMOKE_RECEIPT_V2"
            or summary.get("receipt_schema_version") != 2
            or summary.get("status") not in {"passed", "passed_partial", "failed"}
            or not isinstance(summary.get("cases"), list)
        ):
            raise RuntimeError("E_OUTPUT_SUMMARY_INCOMPLETE")
        if self.final_path.exists() or self.final_path.is_symlink():
            raise RuntimeError("E_OUTPUT_FINAL_EXISTS")
        try:
            os.rename(self.path, self.final_path)
        except OSError:
            raise RuntimeError("E_OUTPUT_PROMOTE") from None
        self.promoted = True

    def abort(self) -> bool:
        if self.promoted or not self.path.exists():
            return True
        try:
            shutil.rmtree(self.path)
            return True
        except OSError:
            if not self.path.exists():
                return True
        seal = self.path / INVALID_STAGING_SEAL
        try:
            write_new_text(
                seal,
                "invalid=true\nreason=receipt_generation_interrupted\n",
            )
            self.invalid_sealed = True
            return False
        except OSError:
            raise RuntimeError("E_OUTPUT_STAGING_CLEANUP") from None

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if not self.promoted:
            self.abort()


_ACTIVE_OUTPUT_STAGING: OutputStaging | None = None


def prepare_output(path: Path) -> Path:
    global _ACTIVE_OUTPUT_STAGING
    if _ACTIVE_OUTPUT_STAGING is not None:
        raise RuntimeError("E_OUTPUT_STAGING_ALREADY_ACTIVE")
    _ACTIVE_OUTPUT_STAGING = OutputStaging(path)
    return _ACTIVE_OUTPUT_STAGING.path


def promote_prepared_output() -> None:
    global _ACTIVE_OUTPUT_STAGING
    if _ACTIVE_OUTPUT_STAGING is None:
        raise RuntimeError("E_OUTPUT_STAGING_NOT_ACTIVE")
    _ACTIVE_OUTPUT_STAGING.promote()
    _ACTIVE_OUTPUT_STAGING = None


def cleanup_prepared_output() -> None:
    global _ACTIVE_OUTPUT_STAGING
    if _ACTIVE_OUTPUT_STAGING is None:
        return
    staging = _ACTIVE_OUTPUT_STAGING
    _ACTIVE_OUTPUT_STAGING = None
    staging.abort()


def cleanup_output_on_failure(function: Any) -> Any:
    def wrapped(*args: object, **kwargs: object) -> object:
        try:
            return function(*args, **kwargs)
        except BaseException:
            cleanup_prepared_output()
            raise

    return wrapped


@cleanup_output_on_failure
def main() -> None:
    parser = argparse.ArgumentParser(description="Run real Codex model smoke cases.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--codex-executable",
        type=Path,
        required=True,
        help="Absolute native Codex binary path. Shell, Node, and provider wrappers are rejected.",
    )
    parser.add_argument("--model", help="Optional explicit model; required for release eligibility.")
    parser.add_argument(
        "--reasoning-effort",
        help=(
            "Explicit model reasoning effort (for example high, xhigh, or max); "
            "required for release eligibility."
        ),
    )
    parser.add_argument(
        "--skill-source",
        choices=(
            "source-fixture",
            "installed-global",
            "verified-installed-snapshot",
        ),
        default="source-fixture",
        help=(
            "Use a project-local source snapshot, the live global host, or a clean HOME "
            "snapshot frozen from the manifest-matched global pair. Release eligibility "
            "requires verified-installed-snapshot."
        ),
    )
    parser.add_argument(
        "--installed-root",
        type=Path,
        default=None,
        help=(
            "Skills root used with installed-global or verified-installed-snapshot. It "
            "must be the OS account's <HOME>/.agents/skills."
        ),
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this model-smoke case id. Repeat to select multiple cases.",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--require-release-tier",
        choices=("rc", "prerelease", "stable"),
        default=None,
        help=(
            "Exit non-zero unless the generated receipt is eligible for the requested "
            "release tier. The receipt is still written for audit."
        ),
    )
    parser.add_argument(
        "--source-trust",
        choices=("reviewed", "untrusted"),
        default="untrusted",
        help=(
            "Declare whether the evaluated checkout has been independently reviewed. "
            "Only reviewed source can produce trusted-source behavior RC evidence; this "
            "declaration is not a sandbox or signature."
        ),
    )
    parser.add_argument(
        "--auth-json",
        type=Path,
        required=True,
        help=(
            "Codex evaluation auth.json. Dedicated low-privilege auth is recommended; "
            "primary auth can produce RC artifact evidence only for reviewed source."
        ),
    )
    parser.add_argument(
        "--acknowledge-auth-readable-to-eval-process",
        action="store_true",
        help="Required acknowledgement that same-user evaluated code may read the temp auth copy.",
    )
    parser.add_argument(
        "--auth-credential-class",
        choices=("dedicated", "primary"),
        required=True,
        help="Declare whether auth is a dedicated eval credential or the primary account.",
    )
    args = parser.parse_args()

    if not args.acknowledge_auth_readable_to_eval_process:
        raise RuntimeError(
            "model smoke requires --acknowledge-auth-readable-to-eval-process; "
            "prefer a dedicated credential and disposable OS/container boundary"
        )
    if args.timeout <= 0:
        raise RuntimeError("--timeout must be positive")
    if args.reasoning_effort and not REASONING_EFFORT_RE.fullmatch(
        args.reasoning_effort
    ):
        raise RuntimeError("--reasoning-effort must be a safe lowercase identifier")
    if args.model and not EXECUTION_ID_RE.fullmatch(args.model):
        raise RuntimeError("--model must be a bounded safe identifier")

    root = args.root.resolve()
    check_contamination(root)
    runner_path = Path(__file__)
    installer_path = BOUND_INSTALLER_PATH
    expected_installer_path = runner_path.with_name("install_skill.py")
    if (
        runner_path.is_symlink()
        or installer_path.is_symlink()
        or installer_path.resolve(strict=True)
        != expected_installer_path.resolve(strict=True)
    ):
        raise RuntimeError("model-smoke installer helper is not the runner sibling source")
    runner_bytes = read_regular_nofollow(runner_path)
    installer_bytes = BOUND_INSTALLER_BYTES
    cases_path = root / "evals" / "behavior_cases.json"
    if cases_path.is_symlink():
        raise RuntimeError("refusing symlink behavior_cases.json")
    cases_bytes = read_regular_nofollow(cases_path)
    raw_cases = json.loads(cases_bytes)
    if not isinstance(raw_cases, list):
        raise RuntimeError("behavior_cases.json must be an array")
    cases = [validate_runtime_case(case) for case in raw_cases]
    ids = [str(case["id"]) for case in cases]
    if len(ids) != len(set(ids)):
        raise RuntimeError("behavior case ids must be unique")
    all_smoke_cases = validate_smoke_suite(cases)
    if not all_smoke_cases:
        raise RuntimeError("no model-smoke cases selected by the behavior contract")
    smoke_cases = list(all_smoke_cases)
    if args.case_ids:
        requested = set(args.case_ids)
        smoke_cases = [case for case in smoke_cases if case["id"] in requested]
        missing = requested - {str(case["id"]) for case in smoke_cases}
        if missing:
            raise RuntimeError(f"unknown or non-smoke case ids: {', '.join(sorted(missing))}")
    if not smoke_cases:
        raise RuntimeError("selected model-smoke case set is empty")

    # Validate the immutable behavior contract before probing external tools or
    # creating receipt directories. A weakened suite must fail for its own
    # reason and leave no output behind.
    codex_source_before = probe_codex_executable(args.codex_executable)
    codex_source = Path(str(codex_source_before["path"]))
    codex_source_version_before = codex_version(codex_source)
    code_mode_host_source = codex_source.parent / OPENAI_CODE_MODE_HOST_IDENTIFIER
    code_mode_host_source_before = (
        probe_codex_executable(code_mode_host_source)
        if code_mode_host_source.exists() or code_mode_host_source.is_symlink()
        else None
    )
    code_mode_host_required = (
        sys.platform == "darwin" and codex_source_before.get("format") == "mach-o"
    )

    source_manifest = runtime_manifest(root)
    expected_installed_manifests = {
        name: rendered_runtime_manifest(root, name) for name in INSTALL_NAMES
    }
    installed_binding_verified = False
    installed_pair_manifest_verified = False
    installed_tree_integrity_verified = False
    installed_cleanup_verified = False
    installed_transaction_residuals_before: list[dict[str, str]] = []
    installed_transaction_residuals_after: list[dict[str, str]] = []
    installed_manifests: dict[str, dict[str, str]] = {}
    default_installed_root = os_account_home() / ".agents" / "skills"
    installed_root = (
        args.installed_root.expanduser().resolve()
        if args.installed_root is not None
        else default_installed_root.resolve()
    )
    installed_discovery_home: Path | None = None
    installed_root_os_account_anchored = installed_root == default_installed_root.resolve()
    uses_verified_global_pair = args.skill_source in {
        "installed-global",
        "verified-installed-snapshot",
    }
    if uses_verified_global_pair:
        installed_discovery_home = installed_home_for_skills_root(installed_root)
        for name in INSTALL_NAMES:
            target = installed_root / name
            actual = installed_manifest(
                target, expected_installed_manifests[name]
            )
            installed_manifests[name] = actual
            if actual != expected_installed_manifests[name]:
                raise RuntimeError(
                    f"installed-global manifest mismatch for {name}; install the current pair first"
                )
        installed_pair_manifest_verified = True
        installed_tree_integrity_verified = True
        installed_binding_verified = installed_root_os_account_anchored
        installed_transaction_residuals_before = existing_transaction_artifacts(
            installed_root
        )
        installed_cleanup_verified = not installed_transaction_residuals_before

    auth_source = args.auth_json.expanduser()
    auth_bytes = read_regular_nofollow(auth_source)
    auth_data = json.loads(auth_bytes)
    auth_secrets = collect_auth_secrets(auth_data)
    account_home = os_account_home()
    primary_auth_path = account_home / ".codex" / "auth.json"
    primary_auth_os_bound = (
        args.auth_credential_class == "primary"
        and auth_source.resolve(strict=True) == primary_auth_path.resolve(strict=True)
    )
    credential_provenance_verified, credential_provenance_source = (
        verify_credential_provenance(
            args.auth_credential_class,
            auth_data,
            primary_auth_path,
        )
    )
    credential_claim_consistency_checked = (
        credential_provenance_source == "distinct_but_unverified_jwt_claims"
    )
    credential_assurance_level = (
        "primary_os_bound"
        if primary_auth_os_bound
        else "dedicated_declared_distinct_unverified"
        if credential_claim_consistency_checked
        else "declared_without_authoritative_provenance"
    )
    git_executable = trusted_helper_executable("git")
    helper_env = helper_subprocess_env()
    out = prepare_output(args.out)

    results: list[dict[str, object]] = []
    snapshot_manifest: dict[str, str]
    codex_executable_before: dict[str, object]
    codex_executable_after: dict[str, object] | None = None
    codex_version_before: str
    codex_version_after: str | None = None
    executable_provenance_before: dict[str, object]
    executable_provenance_after: dict[str, object] | None = None
    code_mode_host_before: dict[str, object] | None = None
    code_mode_host_after: dict[str, object] | None = None
    code_mode_host_provenance_before: dict[str, object] | None = None
    code_mode_host_provenance_after: dict[str, object] | None = None
    private_code_mode_host_drift_detected = False
    private_executable_drift_detected = True
    private_executable_recheck_error: str | None = None
    with tempfile.TemporaryDirectory(prefix="agency-model-eval-") as tmp:
        temp = Path(tmp)
        private_codex = temp / "codex-native"
        codex_executable_before = freeze_codex_executable(
            codex_source, private_codex, codex_source_before
        )
        codex_executable = Path(str(codex_executable_before["path"]))
        executable_provenance_before = verify_codex_executable_provenance(
            codex_executable, codex_executable_before.get("format")
        )
        if code_mode_host_source_before is not None:
            private_code_mode_host = temp / OPENAI_CODE_MODE_HOST_IDENTIFIER
            code_mode_host_before = freeze_codex_executable(
                code_mode_host_source,
                private_code_mode_host,
                code_mode_host_source_before,
            )
            code_mode_host_provenance_before = verify_codex_executable_provenance(
                private_code_mode_host,
                code_mode_host_before.get("format"),
                OPENAI_CODE_MODE_HOST_IDENTIFIER,
            )
        codex_version_before = codex_version(codex_executable)
        if codex_version_before != codex_source_version_before:
            raise RuntimeError("private Codex executable version did not match the source")
        shell_tool_path, ripgrep_evidence = build_private_shell_tool_path(
            temp / "trusted-tool-bin"
        )
        ripgrep_available_in_shell_tool_path = (
            shutil.which("rg", path=shell_tool_path) is not None
        )
        runtime_snapshot = temp / "runtime-snapshot"
        runtime_snapshot.mkdir()
        copy_runtime(root, runtime_snapshot)
        snapshot_manifest = runtime_manifest(runtime_snapshot)
        if snapshot_manifest != source_manifest:
            raise RuntimeError("runtime source changed while creating the evaluation snapshot")
        for case in smoke_cases:
            runtime_case = dict(case)
            case_id = str(runtime_case["id"])
            expected_boot_receipt = runtime_case.get("expected_boot_receipt")
            if isinstance(expected_boot_receipt, str):
                runtime_case["prompt"] = (
                    str(runtime_case["prompt"])
                    + "\n启动行必须精确等于以下单行，不得改写或追加：\n"
                    + expected_boot_receipt
                )
            review_marker_template = runtime_case.get("review_evidence_marker")
            if isinstance(review_marker_template, str):
                runtime_marker = review_marker_template.replace(
                    "{runtime_nonce}", secrets.token_hex(16)
                )
                if runtime_marker == review_marker_template:
                    raise RuntimeError("review marker template did not expand")
                runtime_case["review_evidence_marker"] = runtime_marker
                runtime_case["expected_file_content"] = str(
                    runtime_case["expected_file_content"]
                ).replace(review_marker_template, runtime_marker)
                runtime_case["_review_marker_runtime_randomized"] = True
                initial_readme = str(runtime_case["expected_file_content"]).replace(
                    str(runtime_case["expected_text"]),
                    "Repository name: agency-model-eval-fixture.",
                )
            else:
                initial_readme = (
                    "# Agency model-eval fixture\n\n"
                    "Repository name: agency-model-eval-fixture.\n"
                )
            (
                workspace_root,
                private_state_root,
                fixture,
                fixture_home,
                isolated_codex_home,
            ) = isolated_case_paths(temp, case_id)
            workspace_root.mkdir(parents=True, mode=0o700)
            private_state_root.mkdir(parents=True, mode=0o700)
            fixture.mkdir()
            fixture_home.mkdir(mode=0o700)
            isolated_codex_home.mkdir(mode=0o700)
            private_state_separated = True
            auth_target = isolated_codex_home / "auth.json"
            write_new_bytes(auth_target, auth_bytes)
            subprocess.run(
                [str(git_executable), "init", "-q", str(fixture)],
                check=True,
                env=helper_env,
            )
            (fixture / "README.md").write_text(
                initial_readme,
                encoding="utf-8",
            )
            case_installed_snapshot_manifests: dict[str, dict[str, str]] = {}
            if args.skill_source == "source-fixture":
                for skill_name in INSTALL_NAMES:
                    skill_target = fixture / ".agents" / "skills" / skill_name
                    skill_target.mkdir(parents=True)
                    copy_runtime(runtime_snapshot, skill_target, skill_name)
                    expected_fixture_manifest = rendered_runtime_manifest(
                        runtime_snapshot, skill_name
                    )
                    if (
                        installed_manifest(
                            skill_target, expected_fixture_manifest
                        )
                        != expected_fixture_manifest
                    ):
                        raise RuntimeError(
                            f"fixture runtime manifest mismatch for {case_id}/{skill_name}"
                        )
            elif args.skill_source == "verified-installed-snapshot":
                snapshot_root = fixture_home / ".agents" / "skills"
                for skill_name in INSTALL_NAMES:
                    case_installed_snapshot_manifests[skill_name] = (
                        copy_verified_installed_bundle(
                            installed_root / skill_name,
                            snapshot_root / skill_name,
                            installed_manifests[skill_name],
                        )
                    )
            elif (fixture / ".agents").exists():
                raise RuntimeError("installed-global fixture unexpectedly contains project skills")
            subprocess.run(
                [
                    str(git_executable),
                    "-C",
                    str(fixture),
                    "config",
                    "user.name",
                    "Model Eval",
                ],
                check=True,
                env=helper_env,
            )
            subprocess.run(
                [
                    str(git_executable),
                    "-C",
                    str(fixture),
                    "config",
                    "user.email",
                    "model-eval@example.invalid",
                ],
                check=True,
                env=helper_env,
            )
            tracked_fixture_paths = ["README.md"]
            if (fixture / ".agents").exists():
                tracked_fixture_paths.append(".agents")
            subprocess.run(
                [str(git_executable), "-C", str(fixture), "add", *tracked_fixture_paths],
                check=True,
                env=helper_env,
            )
            subprocess.run(
                [
                    str(git_executable),
                    "-C",
                    str(fixture),
                    "commit",
                    "-qm",
                    "model eval baseline",
                ],
                check=True,
                env=helper_env,
            )
            git_metadata_before = git_metadata_manifest(fixture / ".git")
            effective_home = (
                installed_discovery_home
                if args.skill_source == "installed-global"
                else fixture_home
            )
            assert effective_home is not None
            env = build_isolated_env(effective_home, isolated_codex_home)
            agents_before = agents_context_evidence(
                fixture, effective_home, isolated_codex_home
            )
            case_result = run_case(
                runtime_case,
                fixture,
                out / case_id,
                codex_executable,
                codex_version_before,
                args.model,
                args.reasoning_effort,
                args.timeout,
                env,
                auth_secrets,
                shell_tool_path,
                git_executable,
            )
            git_metadata_unchanged = False
            try:
                git_metadata_unchanged = (
                    git_metadata_manifest(fixture / ".git") == git_metadata_before
                )
            except (OSError, RuntimeError, ValueError):
                git_metadata_unchanged = False
            if not git_metadata_unchanged:
                failures = case_result.get("failures")
                assert isinstance(failures, list)
                failures.append("fixture Git metadata changed during model evaluation")
                case_result["status"] = "failed"
            case_result["git_metadata_unchanged"] = git_metadata_unchanged
            auth_file_unchanged = False
            try:
                auth_metadata = os.lstat(auth_target)
                auth_file_unchanged = (
                    stat.S_ISREG(auth_metadata.st_mode)
                    and not stat.S_ISLNK(auth_metadata.st_mode)
                    and stat.S_IMODE(auth_metadata.st_mode) == 0o600
                    and (os.name == "nt" or auth_metadata.st_uid == os.getuid())
                    and read_regular_nofollow(auth_target) == auth_bytes
                )
            except OSError:
                auth_file_unchanged = False
            if not auth_file_unchanged:
                failures = case_result.get("failures")
                assert isinstance(failures, list)
                failures.append("isolated auth file changed during model evaluation")
                case_result["status"] = "failed"
            case_result["isolated_auth_file_unchanged"] = auth_file_unchanged
            case_result["private_state_outside_project_parent_verified"] = (
                private_state_separated
            )
            snapshot_unchanged = True
            if args.skill_source == "verified-installed-snapshot":
                snapshot_root = fixture_home / ".agents" / "skills"
                snapshot_unchanged = all(
                    installed_manifest(
                        snapshot_root / skill_name,
                        case_installed_snapshot_manifests[skill_name],
                    )
                    == case_installed_snapshot_manifests[skill_name]
                    == installed_manifests[skill_name]
                    for skill_name in INSTALL_NAMES
                )
                if not snapshot_unchanged:
                    failures = case_result.get("failures")
                    assert isinstance(failures, list)
                    failures.append("verified installed Skill snapshot changed during evaluation")
                    case_result["status"] = "failed"
            case_result["installed_snapshot_unchanged"] = snapshot_unchanged
            if (
                args.skill_source == "verified-installed-snapshot"
                and case_result.get("skills_context_budget_overflow_observed") is True
            ):
                failures = case_result.get("failures")
                assert isinstance(failures, list)
                failures.append(
                    "CLI removed Skill metadata from the isolated routing context"
                )
                case_result["status"] = "failed"
            agents_after = agents_context_evidence(
                fixture, effective_home, isolated_codex_home
            )
            agents_unchanged = agents_before == agents_after
            if not agents_unchanged:
                failures = case_result.get("failures")
                assert isinstance(failures, list)
                failures.append("AGENTS context changed during model evaluation")
                case_result["status"] = "failed"
            case_result["agents_context_before"] = agents_before
            case_result["agents_context_after"] = agents_after
            case_result["agents_context_unchanged"] = agents_unchanged
            case_result["agents_routing_markers_absent"] = True
            results.append(case_result)

        try:
            codex_executable_after = probe_codex_executable(codex_executable)
            codex_version_after = codex_version(codex_executable)
            executable_provenance_after = verify_codex_executable_provenance(
                codex_executable, codex_executable_after.get("format")
            )
            if code_mode_host_before is not None:
                private_code_mode_host = temp / OPENAI_CODE_MODE_HOST_IDENTIFIER
                code_mode_host_after = probe_codex_executable(private_code_mode_host)
                code_mode_host_provenance_after = (
                    verify_codex_executable_provenance(
                        private_code_mode_host,
                        code_mode_host_after.get("format"),
                        OPENAI_CODE_MODE_HOST_IDENTIFIER,
                    )
                )
                private_code_mode_host_drift_detected = (
                    code_mode_host_after != code_mode_host_before
                    or code_mode_host_provenance_after
                    != code_mode_host_provenance_before
                )
            private_executable_drift_detected = (
                codex_executable_after != codex_executable_before
                or codex_version_after != codex_version_before
                or executable_provenance_after != executable_provenance_before
                or private_code_mode_host_drift_detected
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            private_executable_recheck_error = receipt_error_code(
                exc, "E_PRIVATE_CODEX_EXECUTABLE_RECHECK"
            )

    source_drift_detected = source_input_drift_detected(
        root,
        source_manifest,
        cases_path,
        cases_bytes,
        runner_path,
        runner_bytes,
        installer_path,
        installer_bytes,
    )

    installed_drift_detected = False
    installed_cleanup_drift_detected = False
    if uses_verified_global_pair:
        try:
            installed_drift_detected = any(
                installed_manifest(
                    installed_root / name,
                    expected_installed_manifests[name],
                )
                != installed_manifests[name]
                or installed_manifests[name] != expected_installed_manifests[name]
                for name in INSTALL_NAMES
            )
            installed_transaction_residuals_after = existing_transaction_artifacts(
                installed_root
            )
            installed_cleanup_drift_detected = (
                installed_transaction_residuals_after
                != installed_transaction_residuals_before
            )
            installed_cleanup_verified = (
                installed_cleanup_verified
                and not installed_transaction_residuals_after
                and not installed_cleanup_drift_detected
            )
        except (OSError, ValueError, RuntimeError):
            installed_drift_detected = True
            installed_cleanup_verified = False
            installed_cleanup_drift_detected = True

    codex_source_after: dict[str, object] | None = None
    codex_source_version_after: str | None = None
    code_mode_host_source_after: dict[str, object] | None = None
    source_executable_drift_detected = True
    executable_recheck_error = private_executable_recheck_error
    try:
        codex_source_after = probe_codex_executable(codex_source)
        codex_source_version_after = codex_version(codex_source)
        source_executable_drift_detected = (
            codex_source_after != codex_source_before
            or codex_source_version_after != codex_source_version_before
        )
        if code_mode_host_source_before is not None:
            code_mode_host_source_after = probe_codex_executable(
                code_mode_host_source
            )
            source_executable_drift_detected = (
                source_executable_drift_detected
                or code_mode_host_source_after != code_mode_host_source_before
            )
        elif code_mode_host_source.exists() or code_mode_host_source.is_symlink():
            source_executable_drift_detected = True
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        executable_recheck_error = receipt_error_code(
            exc, "E_CODEX_SOURCE_EXECUTABLE_RECHECK"
        )
    executable_drift_detected = (
        private_executable_drift_detected or source_executable_drift_detected
    )
    executable_provenance_verified = combined_codex_executable_provenance_verified(
        executable_provenance_before,
        executable_provenance_after,
        code_mode_host_required,
        code_mode_host_provenance_before,
        code_mode_host_provenance_after,
        private_executable_drift_detected,
    )

    manifest_json = json.dumps(snapshot_manifest, sort_keys=True).encode()
    full_run = args.case_ids is None and len(results) == len(all_smoke_cases)
    status = receipt_status(full_run, results)
    if (
        source_drift_detected
        or installed_drift_detected
        or installed_cleanup_drift_detected
        or executable_drift_detected
    ):
        status = "failed"
    observed_models = sorted(
        {
            model
            for result in results
            for model in result.get("observed_models", [])
            if isinstance(model, str)
        }
    )
    observed_providers = sorted(
        {
            provider
            for result in results
            for provider in result.get("observed_providers", [])
            if isinstance(provider, str)
        }
    )
    observed_reasoning_efforts = sorted(
        {
            effort
            for result in results
            for effort in result.get("observed_reasoning_efforts", [])
            if isinstance(effort, str)
        }
    )
    untested_capabilities = [
        "native_goal_lifecycle",
        "real_codex_task_threadops",
        "cold_review_context_isolation",
        "host_plugins_apps_compatibility",
    ]
    execution_configuration_accepted = configuration_requests_accepted(
        results, len(smoke_cases)
    )
    requested_model_observed = bool(args.model) and bool(results) and all(
        result.get("observed_models") == [args.model] for result in results
    )
    requested_provider_observed = bool(results) and all(
        result.get("observed_providers") == [LOCKED_MODEL_PROVIDER]
        for result in results
    )
    requested_reasoning_effort_observed = bool(args.reasoning_effort) and bool(
        results
    ) and all(
        result.get("observed_reasoning_efforts") == [args.reasoning_effort]
        for result in results
    )
    rollout_identity_verified = bool(results) and all(
        result.get("execution_identity_source")
        == "codex_rollout_session_meta_and_turn_context"
        and isinstance(result.get("rollout_identity_evidence"), dict)
        and result["rollout_identity_evidence"].get("schema_failures") == []
        and result["rollout_identity_evidence"].get("observed_cli_versions")
        == [codex_version_before.removeprefix("codex-cli ")]
        for result in results
    )
    agents_routing_evidence_verified = bool(results) and all(
        result.get("agents_context_unchanged") is True
        and result.get("agents_routing_markers_absent") is True
        for result in results
    )
    all_case_process_group_cleanup_verified = bool(results) and all(
        result.get("process_group_cleanup_verified") is True for result in results
    )
    all_case_auth_binding_verified = bool(results) and all(
        result.get("isolated_auth_file_unchanged") is True for result in results
    )
    all_case_private_state_separation_verified = bool(results) and all(
        result.get("private_state_outside_project_parent_verified") is True
        for result in results
    )
    all_case_git_metadata_unchanged_verified = bool(results) and all(
        result.get("git_metadata_unchanged") is True for result in results
    )
    exact_auth_output_scan_verified = bool(results) and not any(
        item.get("auth_exact_value_leak_detected") for item in results
    ) and all(item.get("raw_rollout_auth_scan_verified") is True for item in results)
    auth_handling_integrity_verified = (
        all_case_auth_binding_verified and exact_auth_output_scan_verified
    )
    required_rc_review_case_ids = [
        str(case["id"])
        for case in smoke_cases
        if case.get("review_evidence_tier") == "rc"
    ]
    results_by_id = {str(result.get("id")): result for result in results}
    all_required_rc_review_chains_verified = all(
        case_id in results_by_id
        and results_by_id[case_id].get("rc_review_chain_verified") is True
        for case_id in required_rc_review_case_ids
    )
    required_collab_completion_case_ids = [
        str(case["id"])
        for case in smoke_cases
        if case.get("require_collab_completion")
    ]
    all_required_collab_completion_chains_verified = bool(
        required_collab_completion_case_ids
    ) and all(
        case_id in results_by_id
        and results_by_id[case_id].get("collab_completion_verified") is True
        for case_id in required_collab_completion_case_ids
    )
    stable_cold_review_evidence_verified = bool(required_rc_review_case_ids) and all(
        results_by_id.get(case_id, {}).get("cold_review_verified") is True
        for case_id in required_rc_review_case_ids
    )
    routing_context_verified = (
        args.skill_source == "verified-installed-snapshot"
        and bool(results)
        and all(
            result.get("installed_snapshot_unchanged") is True
            and result.get("skills_context_budget_overflow_count") == 0
            for result in results
        )
    )
    release_installed_binding_verified = verified_installed_release_binding(
        installed_binding_verified,
        installed_pair_manifest_verified,
        installed_tree_integrity_verified,
        installed_drift_detected,
        routing_context_verified,
    )
    execution_identity_verified = (
        codex_executable_before.get("native_format_detected") is True
        and executable_provenance_verified
        and not executable_drift_detected
        and execution_configuration_accepted
        and requested_model_observed
        and requested_provider_observed
        and requested_reasoning_effort_observed
        and rollout_identity_verified
        and all_case_auth_binding_verified
    )
    legacy_comprehensive_prerelease_eligible, _ = release_eligibility(
        status,
        full_run,
        bool(args.model),
        bool(args.reasoning_effort),
        args.auth_credential_class,
        credential_provenance_verified,
        execution_identity_verified,
        release_installed_binding_verified,
        installed_cleanup_verified,
        untested_capabilities,
    )
    artifact_rc_evidence_eligible = (
        artifact_rc_evidence_eligibility(
            status,
            full_run,
            bool(args.model),
            bool(args.reasoning_effort),
            execution_identity_verified,
            release_installed_binding_verified,
            installed_cleanup_verified,
            auth_handling_integrity_verified,
        )
        and all_required_rc_review_chains_verified
        and all_required_collab_completion_chains_verified
        and all_case_private_state_separation_verified
        and all_case_git_metadata_unchanged_verified
    )
    credential_rc_handling_verified = auth_handling_integrity_verified
    rc_release_evidence_eligible = (
        artifact_rc_evidence_eligible
        and credential_rc_handling_verified
        and args.source_trust == "reviewed"
    )
    stable_supported = STABLE_RELEASE_SUPPORTED
    artifact_stable_evidence_eligible = (
        stable_supported
        and
        artifact_rc_evidence_eligible
        and stable_cold_review_evidence_verified
        and not untested_capabilities
    )
    credential_stable_assurance_verified = (
        credential_rc_handling_verified and credential_provenance_verified
    )
    stable_eligible = (
        artifact_stable_evidence_eligible
        and credential_stable_assurance_verified
        and args.source_trust == "reviewed"
    )
    if legacy_comprehensive_prerelease_eligible and not rc_release_evidence_eligible:
        raise RuntimeError(
            "legacy comprehensive prerelease evidence cannot exceed RC eligibility"
        )
    release_evidence_checks = {
        "full_suite_passed": status == "passed" and full_run,
        "source_inputs_unchanged": not source_drift_detected,
        "explicit_model": bool(args.model),
        "explicit_reasoning_effort": bool(args.reasoning_effort),
        "reviewed_source_declared": args.source_trust == "reviewed",
        "dedicated_credential_declared": args.auth_credential_class == "dedicated",
        "dedicated_credential_claims_consistent_but_unverified": (
            credential_claim_consistency_checked
        ),
        "dedicated_credential_provenance_verified": credential_provenance_verified,
        "native_executable_format_detected": (
            codex_executable_before.get("native_format_detected") is True
        ),
        "codex_executable_provenance_verified": (
            executable_provenance_verified
        ),
        "private_execution_copy_verified": (
            not private_executable_drift_detected
        ),
        "codex_executable_unchanged": not executable_drift_detected,
        "execution_configuration_accepted": execution_configuration_accepted,
        "requested_model_observed": requested_model_observed,
        "requested_openai_provider_observed": requested_provider_observed,
        "requested_reasoning_effort_observed": (
            requested_reasoning_effort_observed
        ),
        "main_rollout_identity_verified": rollout_identity_verified,
        "installed_pair_manifest_verified": (
            installed_pair_manifest_verified and not installed_drift_detected
        ),
        "installed_tree_integrity_verified": (
            installed_tree_integrity_verified and not installed_drift_detected
        ),
        "verified_installed_snapshot_routing_context": routing_context_verified,
        "skill_source_release_eligible": (
            args.skill_source == "verified-installed-snapshot"
        ),
        "installed_discovery_root_os_account_anchored": (
            installed_root_os_account_anchored
        ),
        "installed_transaction_cleanup_verified": installed_cleanup_verified,
        "agents_routing_markers_absent_and_context_unchanged": (
            agents_routing_evidence_verified
        ),
        "all_case_process_group_cleanup_verified": (
            all_case_process_group_cleanup_verified
        ),
        "all_case_isolated_auth_binding_verified": (
            all_case_auth_binding_verified
        ),
        "all_case_private_state_separation_verified": (
            all_case_private_state_separation_verified
        ),
        "all_case_git_metadata_unchanged_verified": (
            all_case_git_metadata_unchanged_verified
        ),
        "exact_auth_output_scan_verified": exact_auth_output_scan_verified,
        "all_required_rc_review_chains_verified": (
            all_required_rc_review_chains_verified
        ),
        "stable_cold_review_evidence_verified": (
            stable_cold_review_evidence_verified
        ),
        "artifact_rc_evidence_eligible": artifact_rc_evidence_eligible,
        "natural_collaboration_completion_verified": (
            all_required_collab_completion_chains_verified
        ),
        "credential_rc_handling_verified": credential_rc_handling_verified,
        "legacy_comprehensive_prerelease_evidence_eligible": (
            legacy_comprehensive_prerelease_eligible
        ),
    }
    required_release_tier_met = release_tier_requirement_met(
        args.require_release_tier,
        rc_release_evidence_eligible,
        stable_eligible,
    )
    codex_executable_receipt = dict(codex_executable_before)
    codex_executable_receipt["path"] = receipt_path(
        codex_source, account_home
    )
    code_mode_host_receipt: dict[str, object] | None = None
    if code_mode_host_before is not None:
        code_mode_host_receipt = dict(code_mode_host_before)
        code_mode_host_receipt["path"] = receipt_path(
            code_mode_host_source, account_home
        )
        code_mode_host_receipt["provenance"] = (
            code_mode_host_provenance_before
        )
        code_mode_host_receipt["provenance_reverified"] = (
            code_mode_host_provenance_after == code_mode_host_provenance_before
        )
        code_mode_host_receipt["drift_detected"] = (
            private_code_mode_host_drift_detected
            or code_mode_host_source_after != code_mode_host_source_before
        )
    residuals_before_receipt = [
        {
            **item,
            "path": receipt_path(Path(item["path"]), account_home),
        }
        for item in installed_transaction_residuals_before
    ]
    residuals_after_receipt = [
        {
            **item,
            "path": receipt_path(Path(item["path"]), account_home),
        }
        for item in installed_transaction_residuals_after
    ]
    summary = {
        "receipt_type": "MODEL_SMOKE_RECEIPT_V2",
        "receipt_schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "codex_version": codex_version_before,
        "codex_executable": {
            **codex_executable_receipt,
            "version_before": codex_version_before,
            "version_after": codex_version_after,
            "source_version_before": codex_source_version_before,
            "source_version_after": codex_source_version_after,
            "private_execution_copy": True,
            "code_mode_host_required": code_mode_host_required,
            "code_mode_host_present": code_mode_host_source_before is not None,
            "code_mode_host": code_mode_host_receipt,
            "provenance": executable_provenance_before,
            "provenance_reverified": (
                executable_provenance_after == executable_provenance_before
            ),
            "drift_detected": executable_drift_detected,
            "recheck_error": executable_recheck_error,
        },
        "provider_lock": {
            "requested_provider": LOCKED_MODEL_PROVIDER,
            "source": "cli_config_override",
            "strict_config": True,
            "request_accepted": execution_configuration_accepted,
            "observed_providers": observed_providers,
            "requested_provider_observed": requested_provider_observed,
        },
        "execution_config": {
            "requested_reasoning_effort": args.reasoning_effort or "model_default",
            "reasoning_effort_explicit": bool(args.reasoning_effort),
            "requested_multi_agent_feature": "multi_agent",
            "multi_agent_request_accepted": execution_configuration_accepted,
            "ignore_user_config_requested": True,
            "shell_environment_inherit": "none",
            "shell_tool_path_explicit": True,
            "shell_git_system_config_disabled": True,
            "shell_git_global_config_disabled": True,
            "shell_git_optional_locks_disabled": True,
            "shell_tool_path_sha256": sha256_bytes(shell_tool_path.encode()),
            "ripgrep_available_in_shell_tool_path": (
                ripgrep_available_in_shell_tool_path
            ),
            "private_ripgrep_copy": {
                "sha256": ripgrep_evidence["sha256"],
                "native_format_detected": ripgrep_evidence[
                    "native_format_detected"
                ],
            },
            "runner_git_executable": "<OS_DEFAULT_PATH>/git",
        },
        "requested_model": args.model or "host_default",
        "observed_models": observed_models,
        "requested_model_observed": requested_model_observed,
        "observed_reasoning_efforts": observed_reasoning_efforts,
        "requested_reasoning_effort_observed": (
            requested_reasoning_effort_observed
        ),
        "skill_manifest_sha256": sha256_bytes(manifest_json),
        "behavior_cases_sha256": sha256_bytes(cases_bytes),
        "runner_sha256": sha256_bytes(runner_bytes),
        "installer_sha256": sha256_bytes(installer_bytes),
        "runtime_snapshot_verified": snapshot_manifest == source_manifest,
        "source_drift_detected": source_drift_detected,
        "suite_contract_verified": True,
        "skill_source": args.skill_source,
        "installed_root": (
            receipt_path(installed_root, account_home)
            if uses_verified_global_pair
            else None
        ),
        "installed_discovery_home": (
            receipt_path(installed_discovery_home, account_home)
            if args.skill_source == "installed-global"
            else None
        ),
        "installed_source_home": (
            receipt_path(installed_discovery_home, account_home)
            if uses_verified_global_pair
            else None
        ),
        "execution_skill_discovery_mode": {
            "source-fixture": "project_source_snapshot",
            "installed-global": "live_os_account_home",
            "verified-installed-snapshot": "clean_home_verified_installed_snapshot",
        }[args.skill_source],
        "routing_context_verified": routing_context_verified,
        "installed_binding_verified": installed_binding_verified,
        "installed_pair_manifest_verified": installed_pair_manifest_verified,
        "installed_tree_integrity_policy": SEALED_TREE_POLICY,
        "installed_tree_integrity_verified": (
            installed_tree_integrity_verified and not installed_drift_detected
        ),
        "installed_root_os_account_anchored": installed_root_os_account_anchored,
        "installed_drift_detected": installed_drift_detected,
        "installed_cleanup_verified": installed_cleanup_verified,
        "installed_cleanup_drift_detected": installed_cleanup_drift_detected,
        "installed_transaction_residuals_before": residuals_before_receipt,
        "installed_transaction_residuals_after": residuals_after_receipt,
        "installed_manifests": installed_manifests,
        "agents_routing_dependency": (
            False if agents_routing_evidence_verified else None
        ),
        "agents_routing_markers_absent_verified": agents_routing_evidence_verified,
        "all_case_process_group_cleanup_verified": (
            all_case_process_group_cleanup_verified
        ),
        "all_case_isolated_auth_binding_verified": (
            all_case_auth_binding_verified
        ),
        "all_case_private_state_separation_verified": (
            all_case_private_state_separation_verified
        ),
        "all_case_git_metadata_unchanged_verified": (
            all_case_git_metadata_unchanged_verified
        ),
        "process_group_scope": (
            "posix_session_process_group_excluding_independent_setsid_escapees"
        ),
        "run_scope": "full" if full_run else "partial",
        "all_model_smoke_case_ids": [case["id"] for case in all_smoke_cases],
        "selected_case_ids": [case["id"] for case in smoke_cases],
        "selected_count": len(smoke_cases),
        "total_model_smoke_count": len(all_smoke_cases),
        "model_identity_source": (
            "codex_rollout_session_meta_and_turn_context"
            if observed_models or observed_providers
            else "not_observed_requested_cli_only"
            if args.model
            else "unknown"
        ),
        "source_trust_declaration": args.source_trust,
        "required_rc_review_case_ids": required_rc_review_case_ids,
        "all_required_rc_review_chains_verified": (
            all_required_rc_review_chains_verified
        ),
        "required_collab_completion_case_ids": (
            required_collab_completion_case_ids
        ),
        "all_required_collab_completion_chains_verified": (
            all_required_collab_completion_chains_verified
        ),
        "stable_cold_review_evidence_verified": (
            stable_cold_review_evidence_verified
        ),
        "artifact_rc_evidence_eligible": artifact_rc_evidence_eligible,
        "artifact_stable_evidence_eligible": (
            artifact_stable_evidence_eligible
        ),
        "credential_rc_handling_verified": credential_rc_handling_verified,
        "credential_stable_assurance_verified": (
            credential_stable_assurance_verified
        ),
        "rc_release_evidence_eligible": rc_release_evidence_eligible,
        "prerelease_evidence_eligible": rc_release_evidence_eligible,
        "prerelease_evidence_eligible_deprecated_alias_for": (
            "release_eligibility.rc.eligible"
        ),
        "stable_release_evidence_eligible": stable_eligible,
        "stable_supported": stable_supported,
        "release_eligibility": {
            "diagnostic": {"eligible": status in {"passed", "passed_partial"}},
            "rc": {
                "artifact_evidence": artifact_rc_evidence_eligible,
                "credential_handling": credential_rc_handling_verified,
                "reviewed_source_declared": args.source_trust == "reviewed",
                "eligible": rc_release_evidence_eligible,
            },
            "stable": {
                "artifact_evidence": artifact_stable_evidence_eligible,
                "credential_assurance": credential_stable_assurance_verified,
                "eligible": stable_eligible,
            },
        },
        "required_release_tier": args.require_release_tier,
        "required_release_tier_met": required_release_tier_met,
        "publish_policy_met": (
            required_release_tier_met
            if args.require_release_tier is not None
            else None
        ),
        "release_evidence_checks": release_evidence_checks,
        "untested_capabilities": untested_capabilities,
        "auth_safety": {
            "dedicated_low_privilege_auth_recommended": True,
            "same_os_user_is_not_a_secret_boundary": True,
            "shell_environment_inherit": "none",
            "shell_tool_path_explicit": True,
            "plugins_disabled": True,
            "apps_disabled": True,
            "declared_credential_class": args.auth_credential_class,
            "credential_assurance_level": credential_assurance_level,
            "primary_auth_os_bound": primary_auth_os_bound,
            "credential_claim_consistency_checked": (
                credential_claim_consistency_checked
            ),
            "credential_provenance_verified": credential_provenance_verified,
            "credential_provenance_source": credential_provenance_source,
            "exact_auth_value_output_scan_passed": (
                exact_auth_output_scan_verified
            ),
            "operational_credential_safety": {
                "issuer_signature_verified": credential_provenance_verified,
                "subject_identity_verified": credential_provenance_verified,
                "distinct_from_primary_verified": False,
                "least_privilege_verified": False,
                "eval_only_verified": False,
                "os_or_container_isolation_verified": False,
                "credential_handling_integrity_verified": (
                    auth_handling_integrity_verified
                ),
                "verified": False,
            },
        },
        "cases": results,
        "status": status,
    }
    write_new_text(
        out / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    promote_prepared_output()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "failed" or not required_release_tier_met:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "Model smoke interrupted; partial case artifacts are not a receipt.",
            file=sys.stderr,
        )
        raise SystemExit(130)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Model smoke failed: {safe_error_text(exc)}", file=sys.stderr)
        raise SystemExit(1)
