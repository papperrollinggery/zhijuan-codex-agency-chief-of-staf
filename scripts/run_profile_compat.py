#!/usr/bin/env python3
"""Run a bounded read-only profile without relying on named custom-agent dispatch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import shlex
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from validate_agent_profiles import PROFILE_NAMES, validate_profile
from protocol_contract import (
    REVIEW_FIELDS as CONTRACT_REVIEW_FIELDS,
    WORKER_FIELDS as CONTRACT_WORKER_FIELDS,
    parse_reviewer_terminal,
    parse_worker_packet,
)


THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
PACKET_LABELS = CONTRACT_WORKER_FIELDS
REVIEW_FIELDS = tuple(f"{field}:" for field in CONTRACT_REVIEW_FIELDS)
READ_ONLY_PROFILES = {
    "codebase-researcher",
    "technical-architect",
    "reviewer",
    "test-debugger",
}
REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}
PROCESS_ENV_ALLOWLIST = {
    "CODEX_HOME",
    "COLORTERM",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "TMPDIR",
    "USER",
}
TOOL_SHELL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
GIT_DIFF_PROFILES = {"codebase-researcher", "reviewer"}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def file_hash_snapshot(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        regular = require_regular_file(path, "immutable execution input")
        result[str(regular)] = sha256(regular)
    return result


def require_regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        fail(f"{label} must be a regular file: {path}")
    return path


def resolve_state_database(path: Path, codex_home: Path) -> Path:
    home = codex_home.resolve()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"state database does not exist: {path}") from exc
    if not resolved.is_relative_to(home):
        fail("state database must resolve inside CODEX_HOME")
    if not resolved.is_file():
        fail(f"state database target must be a regular file: {resolved}")
    return resolved


def read_packet(path: Path) -> str:
    require_regular_file(path, "worker packet")
    data = path.read_bytes()
    if len(data) > 64 * 1024:
        fail("worker packet exceeds 64 KiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("worker packet must be UTF-8") from exc
    try:
        parse_worker_packet(text)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return text.rstrip("\r\n")


def resolve_profile(root: Path, profile_name: str) -> tuple[Path, dict[str, object]]:
    if profile_name not in PROFILE_NAMES:
        fail(f"unknown profile: {profile_name}")
    if profile_name not in READ_ONLY_PROFILES:
        fail(
            "cli-profile-compat only supports read-only profiles; developer work must "
            "stay in the main outcome-owner session or an isolated worktree"
        )
    if root.is_symlink() or not root.is_dir():
        fail(f"profile root must be a regular directory: {root}")
    path = require_regular_file(root / f"{profile_name}.toml", "agent profile")
    parsed = validate_profile(path, profile_name, allow_bindings=True)
    if parsed["sandbox_mode"] != "read-only":
        fail("cli-profile-compat refuses non-read-only sandbox profiles")
    return path, parsed


def resolve_executable(raw: str | None) -> Path:
    candidate = raw or shutil.which("codex")
    if not candidate:
        fail("codex executable was not found")
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        fail("--codex-executable must be an absolute path")
    path = path.resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        fail(f"codex executable is not an executable regular file: {path}")
    return path


def sanitized_codex_environment(source: dict[str, str]) -> dict[str, str]:
    environment = {key: source[key] for key in PROCESS_ENV_ALLOWLIST if key in source}
    if "HOME" not in environment or "PATH" not in environment:
        fail("sanitized Codex environment requires HOME and PATH")
    environment.update(
        {
            "GH_PAGER": "cat",
            "GIT_PAGER": "cat",
            "NO_COLOR": "1",
            "PAGER": "cat",
        }
    )
    return environment


def toml_skills_config(entries: object) -> str | None:
    if not isinstance(entries, list) or not entries:
        return None
    rendered: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("invalid skills.config entry")
        path = require_regular_file(
            Path(str(entry["path"])).expanduser().resolve(), "bound skill"
        )
        rendered.append(f"{{path={json.dumps(str(path))},enabled=true}}")
    return "[" + ",".join(rendered) + "]"


def build_command(
    *,
    executable: Path,
    cwd: Path,
    model: str,
    reasoning_effort: str,
    profile: dict[str, object],
    git_workdir: Path | None,
    git_diff_target: str | None,
) -> list[str]:
    developer_instructions = str(profile["developer_instructions"])
    if profile.get("name") == "reviewer":
        developer_instructions += (
            "\nReviewer terminal contract: return exactly five non-empty lines in this "
            "order: REVIEW_TARGET, REVIEW_READBACK, REVIEW_FINDINGS, "
            "REVIEW_RESIDUAL_RISK, REVIEW_VERDICT. Use no Markdown fences, headings, "
            "commentary, or extra lines. The REVIEW_VERDICT value must be exactly PASS "
            "or FAIL with no punctuation, explanation, suffix, or translation. Set "
            "REVIEW_TARGET to the project-relative required artifact and include every "
            "required current artifact fact in REVIEW_READBACK."
        )
    if git_workdir is not None and git_diff_target is not None:
        exact_command = f"git diff -- {shlex.quote(git_diff_target)}"
        developer_instructions += (
            "\nCompatibility receipt requirement: before the final response, make one "
            "standalone exec_command call with cmd exactly "
            f"{json.dumps(exact_command)} and workdir exactly "
            f"{json.dumps(str(git_workdir))}. Do not chain or pipe this command. "
            "Continue only after the tool reports exit code 0."
        )
    command = [
        str(executable),
        "exec",
        "--json",
        "--color",
        "never",
        "--strict-config",
        "--ignore-user-config",
        "--disable",
        "apps",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
        "--disable",
        "remote_plugin",
        "--disable",
        "plugin_sharing",
        "-s",
        "read-only",
        "-C",
        str(cwd),
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={json.dumps(reasoning_effort)}",
        "-c",
        "shell_environment_policy.inherit=\"none\"",
        "-c",
        f"shell_environment_policy.set.PATH={json.dumps(TOOL_SHELL_PATH)}",
        "-c",
        "developer_instructions="
        + json.dumps(developer_instructions, ensure_ascii=False),
    ]
    skills = toml_skills_config(profile["skills.config"])
    if skills is not None:
        command.extend(["-c", f"skills.config={skills}"])
    command.append("-")
    return command


def parse_exec_events(stdout: str) -> tuple[str, str]:
    thread_ids: list[str] = []
    messages: list[str] = []
    completed_turns = 0
    for number, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"codex exec emitted invalid JSONL at line {number}") from exc
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str):
                thread_ids.append(thread_id)
        elif event.get("type") == "item.completed":
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                messages.append(item["text"])
        elif event.get("type") == "turn.completed":
            completed_turns += 1
    unique_ids = list(dict.fromkeys(thread_ids))
    if len(unique_ids) != 1 or not THREAD_ID_RE.fullmatch(unique_ids[0]):
        fail("codex exec did not emit exactly one valid thread.started id")
    if completed_turns != 1:
        fail("codex exec did not emit exactly one turn.completed event")
    if not messages or not messages[-1].strip():
        fail("codex exec did not emit a final agent_message")
    return unique_ids[0], messages[-1]


def started_thread_id(stdout: str) -> str | None:
    thread_ids: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str):
                thread_ids.append(thread_id)
    unique_ids = list(dict.fromkeys(thread_ids))
    if not unique_ids:
        return None
    if len(unique_ids) != 1 or not THREAD_ID_RE.fullmatch(unique_ids[0]):
        fail("codex exec emitted ambiguous thread.started ids")
    return unique_ids[0]


def file_state(path: Path) -> str:
    if path.is_symlink():
        fail(f"protected AGENTS path must not be a symlink: {path}")
    if not path.exists():
        return "ABSENT"
    if not path.is_file():
        fail(f"protected AGENTS path must be a regular file or absent: {path}")
    return "FILE:" + sha256(path)


def git_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        fail("compat profile cwd must be inside a Git worktree")
    return Path(result.stdout.strip()).resolve()


def agents_snapshot(cwd: Path, codex_home: Path) -> dict[str, str]:
    project_root = git_root(cwd)
    locations = {codex_home.resolve(), project_root, cwd.resolve()}
    paths = {
        directory / filename
        for directory in locations
        for filename in ("AGENTS.md", "AGENTS.override.md")
    }
    return {str(path): file_state(path) for path in sorted(paths)}


def rollout_records(path: Path) -> list[dict[str, Any]]:
    require_regular_file(path, "rollout")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rollout JSON at line {number}") from exc
        if isinstance(value, dict):
            records.append(value)
    return records


def string_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(string_content(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(string_content(item) for item in value.values())
    return ""


def command_candidates(call_input: str) -> list[tuple[str, Path | None]]:
    try:
        parsed = json.loads(call_input)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("cmd"), str):
        raw_cwd = parsed.get("workdir")
        cwd = Path(raw_cwd).expanduser().absolute() if isinstance(raw_cwd, str) else None
        return [(parsed["cmd"], cwd)]

    wrapper = re.fullmatch(
        r"\s*(?://\s*@exec:[^\r\n]*\r?\n)?"
        r"const\s+(?P<result>[A-Za-z_]\w*)\s*=\s*await\s+"
        r"tools\.exec_command\((?P<arguments>\{.*\})\);\s*"
        r"text\(JSON\.stringify\((?P=result)\)\)\s*;?\s*",
        call_input,
        re.DOTALL,
    )
    if wrapper is None:
        if re.search(r"\b(?:tools|exec_command)\b", call_input):
            return []
        return [(call_input, None)]

    raw_arguments = wrapper.group("arguments")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        arguments = None
    if isinstance(arguments, dict) and isinstance(arguments.get("cmd"), str):
        raw_cwd = arguments.get("workdir")
        cwd = Path(raw_cwd).expanduser().absolute() if isinstance(raw_cwd, str) else None
        return [(arguments["cmd"], cwd)]

    string_literal = r'"(?:\\.|[^"\\])*"'
    object_pattern = re.compile(
        rf"\{{\s*cmd:\s*(?P<cmd>{string_literal})\s*,\s*"
        rf"workdir:\s*(?P<workdir>{string_literal})"
        rf"(?:\s*,\s*(?:yield_time_ms|max_output_tokens):\s*\d+)*\s*\}}",
        re.DOTALL,
    )
    match = object_pattern.fullmatch(raw_arguments)
    if match is None:
        return []
    try:
        command = json.loads(match.group("cmd"))
        raw_cwd = json.loads(match.group("workdir"))
    except json.JSONDecodeError:
        return []
    return [(command, Path(raw_cwd).expanduser().absolute())]


def has_unquoted_shell_control(command: str) -> bool:
    single = False
    double = False
    escaped = False
    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue
        if character == "\\" and not single:
            escaped = True
            continue
        if character == "'" and not double:
            single = not single
            continue
        if character == '"' and not single:
            double = not double
            continue
        if character == "`" or (
            character == "$" and index + 1 < len(command) and command[index + 1] == "("
        ):
            return True
        if not single and not double and character in "#|><;\n\r":
            return True
    return single or double or escaped


def command_reads_artifact(call_input: str, artifact: Path) -> bool:
    candidates = command_candidates(call_input)
    if len(candidates) != 1:
        return False
    command, cwd = candidates[0]
    if has_unquoted_shell_control(command):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    allowed_executables = {
        "cat": "cat",
        "/bin/cat": "cat",
        "head": "head",
        "/usr/bin/head": "head",
        "sed": "sed",
        "/usr/bin/sed": "sed",
        "tail": "tail",
        "/usr/bin/tail": "tail",
    }
    reader = allowed_executables.get(argv[0]) if argv else None
    if reader is None:
        return False

    if reader == "cat":
        path_arguments = argv[2:] if len(argv) == 3 and argv[1] == "--" else argv[1:]
    elif reader == "sed":
        if len(argv) != 4 or argv[1] != "-n" or re.fullmatch(r"\d+(?:,\d+)?p", argv[2]) is None:
            return False
        path_arguments = argv[3:]
    else:
        if len(argv) != 4 or argv[1] != "-n" or not argv[2].isdigit():
            return False
        path_arguments = argv[3:]
    if len(path_arguments) != 1:
        return False

    artifact = artifact.resolve()
    candidate = Path(path_arguments[0]).expanduser()
    if not candidate.is_absolute():
        if cwd is None:
            return False
        candidate = cwd / candidate
    try:
        return candidate.resolve(strict=True) == artifact
    except (FileNotFoundError, OSError):
        return False


def exec_pairs_before_completion(
    records: list[dict[str, Any]],
) -> dict[str, tuple[str, str, object]]:
    completion_indexes = [
        index
        for index, record in enumerate(records)
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completion_indexes) != 1:
        fail("rollout must have exactly one task_complete before read verification")
    calls: dict[str, str] = {}
    outputs: dict[str, str] = {}
    raw_outputs: dict[str, object] = {}
    for record in records[: completion_indexes[0]]:
        payload = record.get("payload")
        if not isinstance(payload, dict) or record.get("type") != "response_item":
            continue
        call_id = payload.get("call_id")
        if not isinstance(call_id, str):
            continue
        if payload.get("type") in {"custom_tool_call", "function_call"}:
            name = payload.get("name")
            if name in {"exec", "exec_command"}:
                if call_id in calls:
                    fail("rollout reuses an exec call id")
                raw = payload.get("input", payload.get("arguments", ""))
                calls[call_id] = string_content(raw)
        elif payload.get("type") in {"custom_tool_call_output", "function_call_output"}:
            if call_id in outputs:
                fail("rollout reuses an exec output call id")
            raw_outputs[call_id] = payload.get("output")
            outputs[call_id] = string_content(raw_outputs[call_id])
    return {
        call_id: (call_input, outputs[call_id], raw_outputs[call_id])
        for call_id, call_input in calls.items()
        if call_id in outputs
    }


def command_reads_git_diff(
    call_input: str, project_root: Path, artifact: Path
) -> bool:
    candidates = command_candidates(call_input)
    if len(candidates) != 1:
        return False
    for command, workdir in candidates:
        if workdir is None or has_unquoted_shell_control(command):
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            continue
        if (
            len(argv) != 4
            or argv[0] != "git"
            or argv[1:3] != ["diff", "--"]
            or workdir.resolve() != project_root
        ):
            continue
        target = Path(argv[3]).expanduser()
        if not target.is_absolute():
            target = workdir / target
        if target.resolve() == artifact:
            return True
    return False


def structured_tool_result(raw_output: object) -> dict[str, object] | None:
    if not isinstance(raw_output, list) or not raw_output:
        return None
    candidates: list[dict[str, object]] = []
    for item in raw_output:
        if not isinstance(item, dict) or item.get("type") != "input_text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "exit_code" in parsed:
            candidates.append(parsed)
    if len(candidates) != 1:
        return None
    result = candidates[0]
    if (
        type(result.get("exit_code")) is not int
        or not isinstance(result.get("output"), str)
        or type(result.get("wall_time_seconds")) not in (int, float)
    ):
        return None
    return result


def output_proves_exit_zero(raw_output: object) -> bool:
    result = structured_tool_result(raw_output)
    return result is not None and result["exit_code"] == 0


def verify_git_diff_read(
    records: list[dict[str, Any]], project_root: Path, artifact: Path
) -> dict[str, object]:
    pairs = exec_pairs_before_completion(records)
    matched = [
        call_id
        for call_id, (call_input, _output, raw_output) in pairs.items()
        if command_reads_git_diff(call_input, project_root, artifact)
        and output_proves_exit_zero(raw_output)
    ]
    if not matched:
        fail("no successful standalone git diff/output pair proves current diff access")
    return {
        "required": True,
        "project_root": str(project_root),
        "artifact": str(artifact),
        "bound_read_calls": len(matched),
        "bound_output_sha256": [
            sha256_bytes(pairs[call_id][1].encode("utf-8")) for call_id in matched
        ],
        "exit_code_zero": True,
    }


def verify_direct_read(
    records: list[dict[str, Any]], artifact: Path, markers: list[str]
) -> dict[str, object]:
    require_regular_file(artifact, "required read artifact")
    pairs = exec_pairs_before_completion(records)
    artifact_bytes = artifact.read_bytes()
    artifact_hash = sha256_bytes(artifact_bytes)
    try:
        artifact_text = artifact_bytes.decode("utf-8")
    except UnicodeDecodeError:
        artifact_text = None
        artifact_text_json = None
    else:
        artifact_text_json = json.dumps(artifact_text, ensure_ascii=False)[1:-1]
    if artifact_text is None and markers:
        fail("required read markers need a UTF-8 artifact")
    if artifact_text is not None and any(marker not in artifact_text for marker in markers):
        fail("required read marker is not present in the artifact bytes")
    matched = [
        call_id
        for call_id, (call_input, output, _raw_output) in pairs.items()
        if command_reads_artifact(call_input, artifact)
        and all(marker in output for marker in markers)
        and output_proves_exit_zero(_raw_output)
        and (
            artifact_hash in output
            or (artifact_text is not None and artifact_text in output)
            or (artifact_text_json is not None and artifact_text_json in output)
        )
    ]
    if not matched:
        fail("no single direct exec/output pair proves the required artifact bytes or hash")
    return {
        "artifact": str(artifact),
        "artifact_sha256": artifact_hash,
        "read_markers_sha256": [sha256_bytes(marker.encode("utf-8")) for marker in markers],
        "bound_read_calls": len(matched),
        "bound_output_sha256": [
            sha256_bytes(pairs[call_id][1].encode("utf-8")) for call_id in matched
        ],
        "artifact_bytes_or_hash_observed": True,
    }


def completed_message(records: list[dict[str, Any]]) -> str:
    messages = [
        record["payload"].get("last_agent_message")
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(messages) != 1 or not isinstance(messages[0], str) or not messages[0].strip():
        fail("rollout task completion message is not unique")
    return messages[0]


def verify_reviewer_schema(
    final_message: str,
    *,
    artifact: Path,
    project_root: Path,
    markers: list[str],
) -> dict[str, str]:
    parsed = parse_reviewer_terminal(final_message)
    try:
        expected_target = artifact.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("reviewer artifact must stay inside the project root") from exc
    if parsed["REVIEW_TARGET"] != expected_target:
        fail("reviewer final target does not match the required artifact")
    if any(marker not in parsed["REVIEW_READBACK"] for marker in markers):
        fail("reviewer readback does not contain every required artifact marker")
    return {key.lower(): value for key, value in parsed.items()}


def thread_row(database_path: Path, thread_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        fail(f"compat thread is missing from state database: {thread_id}")
    return dict(row)


def verify_read_only_sandbox(raw_policy: object) -> dict[str, object]:
    if not isinstance(raw_policy, str) or not raw_policy.strip():
        fail("compat thread has no persisted sandbox policy")
    try:
        policy = json.loads(raw_policy)
    except json.JSONDecodeError as exc:
        raise ValueError("compat thread sandbox policy is not structured JSON") from exc
    if not isinstance(policy, dict):
        fail("compat thread sandbox policy must be an object")
    if policy.get("type") != "managed" or policy.get("network") != "restricted":
        fail("compat thread did not persist a restricted managed sandbox")
    file_system = policy.get("file_system")
    if not isinstance(file_system, dict) or file_system.get("type") != "restricted":
        fail("compat thread filesystem sandbox is not restricted")
    entries = file_system.get("entries")
    if not isinstance(entries, list) or not entries:
        fail("compat thread filesystem sandbox has no bounded entries")
    if any(not isinstance(entry, dict) or entry.get("access") != "read" for entry in entries):
        fail("compat thread filesystem sandbox grants non-read access")
    return policy


def verify_rollout_identity(
    records: list[dict[str, Any]], thread_id: str, model: str, effort: str
) -> None:
    metas = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == thread_id
    ]
    if len(metas) != 1 or metas[0].get("model_provider") != "openai":
        fail("rollout session identity is not uniquely bound to OpenAI")
    contexts = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("model") == model
        and record["payload"].get("effort") == effort
    ]
    if not contexts:
        fail("rollout does not bind the requested model and reasoning effort")


def archive_thread(executable: Path, thread_id: str, env: dict[str, str]) -> None:
    try:
        result = subprocess.run(
            [str(executable), "archive", thread_id],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("compat thread archive exceeded the 30-second limit") from exc
    if result.returncode != 0:
        fail(f"compat thread archive failed with exit code {result.returncode}")


def stop_process_group(
    process: subprocess.Popen[str], *, grace_seconds: int = 5
) -> tuple[str, str]:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return process.communicate()


def run_codex(
    *,
    command: list[str],
    packet: str,
    environment: dict[str, str],
    timeout_seconds: int,
    executable: Path,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(packet, timeout=timeout_seconds)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), False
    except subprocess.TimeoutExpired:
        stdout, stderr = stop_process_group(process)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), True
    except KeyboardInterrupt as exc:
        stdout, _ = stop_process_group(process)
        thread_id = started_thread_id(stdout)
        if thread_id is not None:
            archive_thread(executable, thread_id, environment)
        raise ValueError("compat execution was interrupted; started thread was archived") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--codex-executable")
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True, choices=sorted(REASONING_EFFORTS))
    parser.add_argument("--required-read", type=Path, required=True)
    parser.add_argument("--required-read-marker", action="append", default=[])
    parser.add_argument("--required-final-marker", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    if not MODEL_RE.fullmatch(args.model) or "luna" in args.model.lower():
        fail("model must be an explicit non-Luna model slug")
    if not args.required_read_marker:
        fail("at least one --required-read-marker is required")
    if not args.required_final_marker:
        fail("at least one --required-final-marker is required")
    if any(len(marker.strip()) < 8 for marker in args.required_read_marker):
        fail("required read markers must contain at least eight characters")
    if any(len(marker.strip()) < 8 for marker in args.required_final_marker):
        fail("required final markers must contain at least eight characters")
    if not 1 <= args.timeout_seconds <= 1800:
        fail("--timeout-seconds must be between 1 and 1800")

    source_root = Path(__file__).resolve().parents[1]
    profile_root = (
        args.profile_root.expanduser()
        if args.profile_root is not None
        else source_root / "assets" / "codex_agents"
    )
    if args.profile_root is not None and not profile_root.is_absolute():
        fail("--profile-root must be absolute")
    profile_candidate = require_regular_file(
        profile_root / f"{args.profile}.toml", "agent profile"
    )
    profile_before_parse = sha256(profile_candidate)
    profile_path, profile = resolve_profile(profile_root, args.profile)
    if sha256(profile_path) != profile_before_parse:
        fail("agent profile changed while it was parsed")
    packet_path = args.packet.expanduser()
    if not packet_path.is_absolute():
        fail("--packet must be absolute")
    packet_before_parse = sha256(require_regular_file(packet_path, "worker packet"))
    packet = read_packet(packet_path)
    if sha256(packet_path) != packet_before_parse:
        fail("worker packet changed while it was parsed")
    cwd = args.cwd.expanduser()
    if not cwd.is_absolute() or cwd.is_symlink() or not cwd.is_dir():
        fail("--cwd must be an absolute regular directory")
    cwd = cwd.resolve()
    artifact = args.required_read.expanduser()
    if not artifact.is_absolute():
        fail("--required-read must be absolute")
    artifact = require_regular_file(artifact, "required read artifact").resolve()
    executable = resolve_executable(args.codex_executable)
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    state_db = (
        args.state_db.expanduser()
        if args.state_db is not None
        else codex_home / "state_5.sqlite"
    )
    if not state_db.is_absolute():
        fail("--state-db must be absolute")
    state_db = resolve_state_database(state_db, codex_home)

    runner_path = Path(__file__).resolve()
    bound_skill_paths = [
        Path(str(entry["path"])).expanduser().resolve()
        for entry in profile["skills.config"]
        if isinstance(entry, dict) and "path" in entry
    ]
    immutable_paths = [runner_path, profile_path, packet_path, artifact, *bound_skill_paths]
    immutable_before = file_hash_snapshot(immutable_paths)
    if immutable_before[str(packet_path)] != packet_before_parse:
        fail("worker packet changed before execution")

    project_root = git_root(cwd)
    git_diff_target: str | None = None
    if args.profile in GIT_DIFF_PROFILES:
        try:
            git_diff_target = artifact.relative_to(project_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "reviewer and codebase-researcher artifacts must be inside the Git worktree"
            ) from exc
    before_agents = agents_snapshot(cwd, codex_home)
    command = build_command(
        executable=executable,
        cwd=cwd,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        profile=profile,
        git_workdir=project_root if git_diff_target is not None else None,
        git_diff_target=git_diff_target,
    )
    env = sanitized_codex_environment(os.environ)
    result, timed_out = run_codex(
        command=command,
        packet=packet,
        environment=env,
        timeout_seconds=args.timeout_seconds,
        executable=executable,
    )

    thread_id = started_thread_id(result.stdout)
    if thread_id is not None:
        archive_thread(executable, thread_id, env)
    after_agents = agents_snapshot(cwd, codex_home)
    if before_agents != after_agents:
        fail("protected AGENTS.md state changed during compat execution")
    immutable_after = file_hash_snapshot(immutable_paths)
    if immutable_before != immutable_after:
        fail("immutable execution input changed during compat execution")
    if timed_out:
        if thread_id is not None and thread_row(state_db, thread_id).get("archived") != 1:
            fail(f"timed-out compat thread cleanup is incomplete: {thread_id}")
        suffix = f"; archived thread: {thread_id}" if thread_id is not None else ""
        fail(f"codex exec exceeded the {args.timeout_seconds}-second limit{suffix}")
    if result.returncode != 0:
        if thread_id is not None and thread_row(state_db, thread_id).get("archived") != 1:
            fail(f"failed compat thread cleanup is incomplete: {thread_id}")
        suffix = f"; archived thread: {thread_id}" if thread_id is not None else ""
        fail(f"codex exec failed with exit code {result.returncode}{suffix}")
    parsed_thread_id, stdout_final = parse_exec_events(result.stdout)
    if thread_id != parsed_thread_id:
        fail("codex exec thread identity changed during event parsing")
    assert thread_id is not None

    row = thread_row(state_db, thread_id)
    required_columns = {
        "rollout_path",
        "model_provider",
        "model",
        "reasoning_effort",
        "cwd",
        "archived",
        "sandbox_policy",
        "source",
        "first_user_message",
    }
    missing = sorted(required_columns - set(row))
    if missing:
        fail("state database lacks required thread columns: " + ", ".join(missing))
    if row["model_provider"] != "openai":
        fail("compat thread provider is not OpenAI")
    if row["source"] != "exec":
        fail("compat thread source is not codex exec")
    if row["first_user_message"] != packet:
        fail("compat thread is not bound to the worker packet")
    if row["model"] != args.model or row["reasoning_effort"] != args.reasoning_effort:
        fail("compat thread model identity mismatch")
    if Path(str(row["cwd"])).resolve() != cwd:
        fail("compat thread cwd mismatch")
    if row["archived"] != 1:
        fail("compat thread cleanup is incomplete")
    sandbox_policy = verify_read_only_sandbox(row["sandbox_policy"])
    native_role = row.get("agent_role")
    if native_role not in {None, ""}:
        fail("cli-profile-compat must not masquerade as a native custom-agent role")

    rollout = Path(str(row["rollout_path"])).expanduser()
    records = rollout_records(rollout)
    verify_rollout_identity(records, thread_id, args.model, args.reasoning_effort)
    final_message = completed_message(records)
    if final_message != stdout_final:
        fail("stdout final does not match the persisted task completion")
    for marker in args.required_final_marker:
        if marker not in final_message:
            fail("persisted final is missing a required marker")
    read_receipt = verify_direct_read(records, artifact, args.required_read_marker)
    git_diff_receipt = (
        verify_git_diff_read(records, project_root, artifact)
        if args.profile in GIT_DIFF_PROFILES
        else None
    )
    review_schema = (
        verify_reviewer_schema(
            final_message,
            artifact=artifact,
            project_root=project_root,
            markers=args.required_read_marker,
        )
        if args.profile == "reviewer"
        else None
    )

    receipt = {
        "status": "verified",
        "execution_mode": "cli-profile-compat",
        "profile": args.profile,
        "runner_sha256": immutable_before[str(runner_path)],
        "profile_sha256": immutable_before[str(profile_path)],
        "packet_sha256": immutable_before[str(packet_path)],
        "submitted_packet_sha256": sha256_bytes(packet.encode("utf-8")),
        "immutable_inputs": immutable_before,
        "sandbox_mode": "read-only",
        "native_custom_agent_selected": False,
        "native_agent_role": None,
        "context_mode": "standalone-cli-session",
        "context_injection_surfaces": [
            "codex-base-instructions",
            "profile-developer-instructions",
            "applicable-AGENTS",
            "optional-bound-skills",
            "stdin-worker-packet",
        ],
        "parent_context_inheritance_verified": False,
        "cold_context_isolation": "unverified",
        "subagent_recursion_disabled": True,
        "shell_dispatch": False,
        "tool_shell_path": TOOL_SHELL_PATH,
        "timeout_seconds": args.timeout_seconds,
        "process_environment_keys": sorted(env),
        "secret_like_process_environment_forwarded": False,
        "command_contract_sha256": sha256_bytes("\0".join(command).encode("utf-8")),
        "thread": {
            "id": thread_id,
            "provider": row["model_provider"],
            "model": row["model"],
            "reasoning_effort": row["reasoning_effort"],
            "cwd": row["cwd"],
            "source": row["source"],
            "archived": True,
            "sandbox_policy": sandbox_policy,
            "rollout_sha256": sha256(rollout),
            "final_sha256": sha256_bytes(final_message.encode("utf-8")),
        },
        "artifact_read": read_receipt,
        "git_diff_read": git_diff_receipt,
        "review_schema": review_schema,
        "agents_md": {
            "unchanged": True,
            "states": before_agents,
        },
    }
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"Profile compatibility run failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
