#!/usr/bin/env python3
"""Run real Codex smoke cases in an isolated project/config fixture.

This is not a credential-security boundary. The evaluated process runs as the
current OS user and can theoretically read its temporary auth file. Use only a
reviewed checkout and a dedicated low-privilege evaluation credential, ideally
inside a disposable OS user or container.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from install_skill import SKILL_NAME, copy_runtime, runtime_manifest


TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "computer_use",
}
ASSISTANT_ITEM_TYPES = {"agent_message", "assistant_message"}
CASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
MODEL_RE = re.compile(r"\bmodel=([A-Za-z0-9._-]+)")
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
ALLOWED_MODES = {"direct", "structured", "goal", "worker"}
ALLOWED_COLLABORATION = {
    "none",
    "native_subagents",
    "native_subagents_optional",
    "real_task",
}
ALLOWED_ACTIVATION = {"explicit", "implicit", "ordinary", "worker"}
REQUIRED_SMOKE_CONTRACT = {
    "explicit-small-direct": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
    },
    "explicit-readonly-structured": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "native_subagents_optional",
        "activation": "explicit",
    },
    "delegated-worker-bypass": {
        "should_trigger": False,
        "mode": "worker",
        "collaboration": "none",
        "activation": "worker",
    },
    "invalid-worker-marker-main-session": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "explicit",
    },
    "explicit-write-execute": {
        "should_trigger": True,
        "mode": "structured",
        "collaboration": "native_subagents",
        "activation": "explicit",
        "sandbox": "workspace-write",
        "require_collab_event": True,
    },
    "implicit-chief-of-staff-read": {
        "should_trigger": True,
        "mode": "direct",
        "collaboration": "none",
        "activation": "implicit",
    },
    "ordinary-small-answer": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
    },
    "ordinary-readiness-phrase": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
    },
    "ordinary-rescue-phrase": {
        "should_trigger": False,
        "mode": "direct",
        "collaboration": "none",
        "activation": "ordinary",
    },
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_nofollow(path: Path) -> bytes:
    """Read one regular file without following a final-component symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot safely open regular file: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"expected a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def receipt_status(full_run: bool, results: list[dict[str, object]]) -> str:
    if not results or not all(item.get("status") == "passed" for item in results):
        return "failed"
    return "passed" if full_run else "passed_partial"


def release_eligibility(
    status: str,
    full_run: bool,
    explicit_model: bool,
    credential_class: str,
    untested_capabilities: list[str],
) -> tuple[bool, bool]:
    prerelease = (
        status == "passed"
        and full_run
        and explicit_model
        and credential_class == "dedicated"
    )
    stable = prerelease and not untested_capabilities
    return prerelease, stable


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
    env["PATH"] = parent.get("PATH", os.defpath)
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def collect_auth_secrets(value: object) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            secrets.update(collect_auth_secrets(child))
    elif isinstance(value, list):
        for child in value:
            secrets.update(collect_auth_secrets(child))
    elif isinstance(value, str) and len(value) >= 16:
        secrets.add(value)
    return secrets


def redact_exact_auth_values(text: str, secrets: set[str]) -> tuple[str, bool]:
    matched = False
    redacted = text
    for secret in sorted(secrets, key=len, reverse=True):
        if secret in redacted:
            matched = True
            redacted = redacted.replace(secret, "[REDACTED_EVAL_AUTH_VALUE]")
    return redacted, matched


def is_valid_worker_packet(prompt: str) -> bool:
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


def safe_relative_artifact(value: object, case_id: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"case {case_id} expected_file is not a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"case {case_id} expected_file escapes the fixture")
    return path


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
    sandbox = case.get("sandbox", "read-only")
    if sandbox not in ALLOWED_SANDBOXES:
        raise RuntimeError(f"case {case_id} requests unsafe sandbox {sandbox!r}")
    if "model_smoke" in case and type(case["model_smoke"]) is not bool:
        raise RuntimeError(f"case {case_id} model_smoke must be boolean")
    for key in ("require_tool_event", "require_collab_event"):
        if key in case and type(case[key]) is not bool:
            raise RuntimeError(f"case {case_id} {key} must be boolean")
    for key in ("must_contain", "must_not_contain", "forbidden_file_texts"):
        if key in case and (
            not isinstance(case[key], list)
            or any(not isinstance(item, str) or not item for item in case[key])
        ):
            raise RuntimeError(f"case {case_id} {key} must contain non-empty strings")
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
    return case


def validate_smoke_suite(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    smoke = {str(case["id"]): case for case in cases if case.get("model_smoke")}
    missing = sorted(set(REQUIRED_SMOKE_CONTRACT) - set(smoke))
    if missing:
        raise RuntimeError(f"model-smoke suite missing required cases: {', '.join(missing)}")
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
    if marker in str(write_case["prompt"]):
        raise RuntimeError("write smoke review marker must not be disclosed in the main prompt")
    return [case for case in cases if case.get("model_smoke")]


def event_surface(events_text: str, final_text: str) -> dict[str, object]:
    messages: list[str] = []
    tool_item_ids: set[str] = set()
    spawns: dict[str, dict[str, object]] = {}
    waits: dict[str, dict[str, object]] = {}
    successful_tool_event_indexes: list[int] = []
    last_file_change_event_index = -1
    for index, line in enumerate(events_text.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in ASSISTANT_ITEM_TYPES:
            for key in ("text", "content", "message"):
                value = item.get(key)
                if isinstance(value, str):
                    messages.append(value)
                    break
        if item_type in TOOL_ITEM_TYPES:
            status = item.get("status")
            exit_code = item.get("exit_code")
            command_ok = item_type != "command_execution" or exit_code in {None, 0}
            status_ok = status not in {"failed", "cancelled"}
            if command_ok and status_ok:
                tool_item_ids.add(str(item.get("id", f"event-{index}")))
                successful_tool_event_indexes.append(index)
                if item_type == "file_change":
                    last_file_change_event_index = index
        if item_type != "collab_tool_call" or item.get("status") != "completed":
            continue
        receiver_ids = item.get("receiver_thread_ids")
        if not isinstance(receiver_ids, list):
            receiver_ids = []
        if item.get("tool") == "spawn_agent":
            for receiver_id in receiver_ids:
                if isinstance(receiver_id, str) and receiver_id:
                    spawns[receiver_id] = {
                        "spawn_event_index": index,
                        "prompt": item.get("prompt") if isinstance(item.get("prompt"), str) else "",
                        "sender_thread_id": item.get("sender_thread_id"),
                        "context_isolation_verified": (
                            item.get("fork_turns") == "none"
                            or item.get("context_mode") in {"none", "isolated"}
                        ),
                    }
        if item.get("tool") == "wait":
            states = item.get("agents_states")
            if not isinstance(states, dict):
                continue
            for receiver_id, state in states.items():
                if not isinstance(receiver_id, str) or not isinstance(state, dict):
                    continue
                message = state.get("message")
                if state.get("status") == "completed" and isinstance(message, str) and message.strip():
                    waits[receiver_id] = {
                        "wait_event_index": index,
                        "message": message,
                    }

    completed_reviews = {
        receiver_id: {**spawns[receiver_id], **waits[receiver_id]}
        for receiver_id in sorted(set(spawns) & set(waits))
        if waits[receiver_id]["wait_event_index"]
        > spawns[receiver_id]["spawn_event_index"]
    }
    if final_text and final_text not in messages:
        messages.append(final_text)
    return {
        "surface": "\n".join(messages),
        "tool_events": len(tool_item_ids),
        "spawn_completed": spawns,
        "reviews_completed": completed_reviews,
        "successful_tool_event_indexes": successful_tool_event_indexes,
        "last_file_change_event_index": last_file_change_event_index,
    }


def contract_failures(case: dict[str, Any], surface: str) -> list[str]:
    failures: list[str] = []
    booted = "COS_BOOT_RECEIPT" in surface
    if case["should_trigger"] and not booted:
        failures.append("should_trigger=true but no COS_BOOT_RECEIPT was observed")
    if not case["should_trigger"] and booted:
        failures.append("should_trigger=false but COS_BOOT_RECEIPT was observed")
    if not case["should_trigger"]:
        return failures

    mode_markers = {
        "direct": "模式：直接",
        "structured": "模式：结构化",
        "goal": "模式：Goal",
    }
    marker = mode_markers.get(str(case["mode"]))
    if marker and marker not in surface:
        failures.append(f"boot receipt does not declare expected {marker}")

    collaboration = case["collaboration"]
    accepted = {
        "none": ("协作：无",),
        "native_subagents": ("协作：原生子代理",),
        "native_subagents_optional": ("协作：无", "协作：原生子代理"),
        "real_task": ("协作：真实任务",),
    }[collaboration]
    if not any(value in surface for value in accepted):
        failures.append(
            "boot receipt does not declare expected collaboration: " + " or ".join(accepted)
        )
    return failures


def review_prompt_is_self_contained(
    prompt: str, expected_file: str, expected_text: str
) -> bool:
    prompt_lower = prompt.lower()
    has_goal = any(marker in prompt_lower for marker in ("目标", "goal:", "objective:"))
    has_scope = any(
        marker in prompt_lower for marker in ("范围", "scope:", "read scope", "write scope")
    )
    return (
        is_valid_worker_packet(prompt)
        and has_goal
        and has_scope
        and expected_file in prompt
        and expected_text in prompt
    )


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


def changed_paths(fixture: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(fixture), "status", "--porcelain=v1"],
        text=True,
        capture_output=True,
        check=True,
    )
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            paths.add(path)
    return paths


def run_case(
    case: dict[str, Any],
    fixture: Path,
    case_dir: Path,
    model: str | None,
    timeout: int,
    env: dict[str, str],
    auth_secrets: set[str],
) -> dict[str, object]:
    if case_dir.exists() or case_dir.is_symlink():
        raise RuntimeError(f"refusing to overwrite model-smoke case directory: {case_dir}")
    case_dir.mkdir(parents=True, mode=0o700)
    final_path = case_dir / "final.txt"
    write_new_text(final_path, "")
    sandbox = str(case.get("sandbox", "read-only"))
    if sandbox not in ALLOWED_SANDBOXES:
        raise RuntimeError(f"case {case['id']} requests unsafe sandbox {sandbox!r}")
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "-c",
        "shell_environment_policy.inherit=none",
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
    command.append(str(case["prompt"]))

    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
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
    events_text, events_leak = redact_exact_auth_values(raw_events, auth_secrets)
    stderr_text, stderr_leak = redact_exact_auth_values(raw_stderr, auth_secrets)
    final_text, final_leak = redact_exact_auth_values(raw_final, auth_secrets)
    if final_path.exists():
        final_path.write_text(final_text, encoding="utf-8")
    write_new_text(case_dir / "events.jsonl", events_text)
    write_new_text(case_dir / "stderr.txt", stderr_text)

    parsed = event_surface(events_text, final_text)
    surface = str(parsed["surface"])
    failures = contract_failures(case, surface)
    if completed.returncode != 0:
        failures.append(f"codex exit code {completed.returncode}")
    if final_output_unsafe:
        failures.append("final output path was replaced by a symlink")
    for marker in case.get("must_contain", []):
        if marker not in surface:
            failures.append(f"assistant output missing {marker!r}")
    for marker in case.get("must_not_contain", []):
        if marker in surface:
            failures.append(f"assistant output unexpectedly contains {marker!r}")
    if case.get("require_tool_event") and parsed["tool_events"] == 0:
        failures.append("no completed tool event observed")
    if events_leak or stderr_leak or final_leak:
        failures.append("exact auth value appeared in model output and was redacted")

    expected_file = case.get("expected_file")
    expected_text = case.get("expected_text")
    expected_file_content = case.get("expected_file_content")
    review_evidence_marker = case.get("review_evidence_marker")
    artifact_text = ""
    artifact_leak = False
    expected_relative: PurePosixPath | None = None
    if isinstance(expected_file, str) and isinstance(expected_text, str):
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
        actual_changed = changed_paths(fixture)
        if actual_changed != {expected_file}:
            failures.append(
                f"unexpected final changed files: expected {[expected_file]!r}, "
                f"observed {sorted(actual_changed)!r}"
            )
        diff_check = subprocess.run(
            ["git", "-C", str(fixture), "diff", "--check"],
            text=True,
            capture_output=True,
            check=False,
        )
        if diff_check.returncode != 0:
            failures.append("git diff --check failed for expected artifact")

    completed_reviews = parsed["reviews_completed"]
    assert isinstance(completed_reviews, dict)
    review_ids: list[str] = []
    context_verified_review_ids: list[str] = []
    review_prompt_self_contained = False
    if case.get("require_collab_event"):
        if not completed_reviews:
            failures.append("no spawn -> completed wait -> reviewer message chain observed")
        for receiver_id, review in completed_reviews.items():
            if not isinstance(review, dict):
                continue
            prompt = str(review.get("prompt", ""))
            message = str(review.get("message", ""))
            sender_id = review.get("sender_thread_id")
            if receiver_id == sender_id:
                continue
            if expected_file and expected_file not in message:
                continue
            if expected_text and expected_text not in message:
                continue
            if review_evidence_marker and review_evidence_marker in prompt:
                continue
            if review_evidence_marker and review_evidence_marker not in message:
                continue
            review_prompt_self_contained = review_prompt_is_self_contained(
                prompt, str(expected_file), str(expected_text)
            )
            if not review_prompt_self_contained:
                continue
            if "COS_BOOT_RECEIPT" in message:
                continue
            spawn_index = int(review.get("spawn_event_index", -1))
            last_file_change = int(parsed["last_file_change_event_index"])
            successful_indexes = parsed["successful_tool_event_indexes"]
            assert isinstance(successful_indexes, list)
            if last_file_change < 0 or spawn_index <= last_file_change:
                continue
            if not any(last_file_change < int(index) < spawn_index for index in successful_indexes):
                continue
            review_ids.append(receiver_id)
            if review.get("context_isolation_verified") is True:
                context_verified_review_ids.append(receiver_id)
        if not review_ids:
            failures.append(
                "reviewer result did not prove post-change artifact readback with fresh evidence"
            )
        final_lower = final_text.lower()
        if not (
            "独立" in final_text
            and ("审核" in final_text or "review" in final_lower)
            and any(
                marker in final_text
                for marker in ("结论", "采纳", "未发现", "发现", "满足", "残余")
            )
        ):
            failures.append("final answer did not adopt or report the independent review result")
        if review_ids and not context_verified_review_ids:
            isolation_disclosed = (
                "未验证" in final_text
                and (
                    "cold-context isolation" in final_lower
                    or "context isolation" in final_lower
                    or "上下文隔离" in final_text
                )
            )
            if not isolation_disclosed:
                failures.append(
                    "review context isolation was not observable and final answer did not disclose it"
                )

    observed_models = sorted(set(MODEL_RE.findall(raw_stderr)))
    return {
        "id": case["id"],
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "exit_code": completed.returncode,
        "declared_contract": {
            "should_trigger": case["should_trigger"],
            "mode": case["mode"],
            "collaboration": case["collaboration"],
            "activation": case["activation"],
        },
        "tool_events_completed": parsed["tool_events"],
        "collab_spawns_completed": len(parsed["spawn_completed"]),
        "reviewer_results_completed": len(review_ids),
        "cold_context_isolation_verified_count": len(context_verified_review_ids),
        "review_receiver_ids": review_ids,
        "review_prompt_self_contained": review_prompt_self_contained,
        "observed_models": observed_models,
        "auth_exact_value_leak_detected": (
            events_leak or stderr_leak or final_leak or artifact_leak
        ),
        "prompt_sha256": sha256_bytes(str(case["prompt"]).encode()),
        "events_sha256": sha256_bytes(events_text.encode()),
        "final_sha256": sha256_bytes(final_text.encode()),
        "expected_artifact_sha256": sha256_bytes(artifact_text.encode())
        if expected_relative is not None and artifact_text
        else None,
        "artifact_dir": str(case_dir),
    }


def check_contamination(root: Path) -> None:
    candidates = [root / "AGENTS.md", Path.home() / ".codex" / "AGENTS.md"]
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if SKILL_NAME in text or f"BEGIN {SKILL_NAME} routing" in text:
            raise RuntimeError(f"contaminated AGENTS context: {path}")


def codex_version() -> str:
    result = subprocess.run(
        ["codex", "--version"], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def prepare_output(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise RuntimeError(f"refusing symlink output directory: {expanded}")
    output = expanded.resolve()
    if output.exists():
        raise RuntimeError(f"model-smoke output must not already exist: {output}")
    output.mkdir(parents=True, mode=0o700)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run real Codex model smoke cases.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", help="Optional explicit model; required for release eligibility.")
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this model-smoke case id. Repeat to select multiple cases.",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--auth-json",
        type=Path,
        required=True,
        help="Codex evaluation auth.json; dedicated low-privilege auth is required for releases.",
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
        help="Record whether auth is a dedicated eval credential or the user's primary account.",
    )
    args = parser.parse_args()

    if not args.acknowledge_auth_readable_to_eval_process:
        raise RuntimeError(
            "model smoke requires --acknowledge-auth-readable-to-eval-process; "
            "prefer a dedicated credential and disposable OS/container boundary"
        )
    if args.timeout <= 0:
        raise RuntimeError("--timeout must be positive")

    root = args.root.resolve()
    out = prepare_output(args.out)
    check_contamination(root)
    runner_bytes = Path(__file__).read_bytes()
    cases_path = root / "evals" / "behavior_cases.json"
    if cases_path.is_symlink():
        raise RuntimeError("refusing symlink behavior_cases.json")
    cases_bytes = cases_path.read_bytes()
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
    source_manifest = runtime_manifest(root)

    auth_source = args.auth_json.expanduser()
    auth_bytes = read_regular_nofollow(auth_source)
    auth_data = json.loads(auth_bytes)
    auth_secrets = collect_auth_secrets(auth_data)

    results: list[dict[str, object]] = []
    snapshot_manifest: dict[str, str]
    with tempfile.TemporaryDirectory(prefix="agency-model-eval-") as tmp:
        temp = Path(tmp)
        runtime_snapshot = temp / "runtime-snapshot"
        runtime_snapshot.mkdir()
        copy_runtime(root, runtime_snapshot)
        snapshot_manifest = runtime_manifest(runtime_snapshot)
        if snapshot_manifest != source_manifest:
            raise RuntimeError("runtime source changed while creating the evaluation snapshot")
        for case in smoke_cases:
            case_id = str(case["id"])
            fixture = temp / f"fixture-{case_id}"
            fixture_home = temp / f"home-{case_id}"
            isolated_codex_home = temp / f"codex-{case_id}"
            fixture.mkdir()
            fixture_home.mkdir(mode=0o700)
            isolated_codex_home.mkdir(mode=0o700)
            auth_target = isolated_codex_home / "auth.json"
            write_new_bytes(auth_target, auth_bytes)
            subprocess.run(["git", "init", "-q", str(fixture)], check=True)
            (fixture / "README.md").write_text(
                "# Agency model-eval fixture\n\n"
                "Repository name: agency-model-eval-fixture.\n",
                encoding="utf-8",
            )
            skill_target = fixture / ".agents" / "skills" / SKILL_NAME
            skill_target.mkdir(parents=True)
            copy_runtime(runtime_snapshot, skill_target)
            if runtime_manifest(skill_target) != snapshot_manifest:
                raise RuntimeError(f"fixture runtime manifest mismatch for case {case_id}")
            subprocess.run(
                ["git", "-C", str(fixture), "config", "user.name", "Model Eval"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(fixture),
                    "config",
                    "user.email",
                    "model-eval@example.invalid",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(fixture), "add", "README.md", ".agents"], check=True
            )
            subprocess.run(
                ["git", "-C", str(fixture), "commit", "-qm", "model eval baseline"],
                check=True,
            )
            env = build_isolated_env(fixture_home, isolated_codex_home)
            results.append(
                run_case(
                    case,
                    fixture,
                    out / case_id,
                    args.model,
                    args.timeout,
                    env,
                    auth_secrets,
                )
            )

    source_drift_detected = False
    try:
        source_drift_detected = (
            runtime_manifest(root) != source_manifest
            or cases_path.read_bytes() != cases_bytes
            or Path(__file__).read_bytes() != runner_bytes
        )
    except (OSError, ValueError):
        source_drift_detected = True

    manifest_json = json.dumps(snapshot_manifest, sort_keys=True).encode()
    full_run = args.case_ids is None and len(results) == len(all_smoke_cases)
    status = receipt_status(full_run, results)
    if source_drift_detected:
        status = "failed"
    observed_models = sorted(
        {
            model
            for result in results
            for model in result.get("observed_models", [])
            if isinstance(model, str)
        }
    )
    untested_capabilities = [
        "native_goal_lifecycle",
        "real_codex_task_threadops",
        "cold_review_context_isolation",
        "host_plugins_apps_compatibility",
    ]
    prerelease_eligible, stable_eligible = release_eligibility(
        status,
        full_run,
        bool(args.model),
        args.auth_credential_class,
        untested_capabilities,
    )
    summary = {
        "receipt_type": "MODEL_SMOKE_RECEIPT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "codex_version": codex_version(),
        "requested_model": args.model or "host_default",
        "observed_models": observed_models,
        "skill_manifest_sha256": sha256_bytes(manifest_json),
        "behavior_cases_sha256": sha256_bytes(cases_bytes),
        "runner_sha256": sha256_bytes(runner_bytes),
        "runtime_snapshot_verified": snapshot_manifest == source_manifest,
        "source_drift_detected": source_drift_detected,
        "suite_contract_verified": True,
        "agents_routing_dependency": False,
        "run_scope": "full" if full_run else "partial",
        "all_model_smoke_case_ids": [case["id"] for case in all_smoke_cases],
        "selected_case_ids": [case["id"] for case in smoke_cases],
        "selected_count": len(smoke_cases),
        "total_model_smoke_count": len(all_smoke_cases),
        "model_identity_source": (
            "explicit_cli" if args.model else "diagnostic_stderr" if observed_models else "unknown"
        ),
        "prerelease_evidence_eligible": prerelease_eligible,
        "stable_release_evidence_eligible": stable_eligible,
        "release_evidence_eligible": stable_eligible,
        "untested_capabilities": untested_capabilities,
        "auth_safety": {
            "dedicated_low_privilege_auth_recommended": True,
            "same_os_user_is_not_a_secret_boundary": True,
            "shell_environment_inherit": "none",
            "plugins_disabled": True,
            "apps_disabled": True,
            "credential_class": args.auth_credential_class,
            "exact_auth_value_output_scan_passed": not any(
                item.get("auth_exact_value_leak_detected") for item in results
            ),
        },
        "cases": results,
        "status": status,
    }
    write_new_text(
        out / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Model smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
