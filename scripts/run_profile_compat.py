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
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from validate_agent_profiles import PROFILE_NAMES, validate_profile
from inspect_codex_models import canonical_state_connection, canonical_state_database
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
    "supervisor",
}
REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
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
TOOL_SHELL_TMPDIR = "/tmp"
GIT_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GIT_TOOL_ENVIRONMENT = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_ATTR_SOURCE": GIT_EMPTY_TREE,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.fsmonitor",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
}
GIT_DIFF_PROFILES = {"codebase-researcher", "reviewer"}
RECEIPT_YIELD_TIME_MS = 10000
RECEIPT_MAX_OUTPUT_TOKENS = 50000


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a non-symlink regular file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"{label} must be a single regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def regular_file_snapshot(path: Path, label: str) -> dict[str, object]:
    """Capture content and inode identity through one no-follow descriptor."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a non-symlink regular file: {path}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(f"{label} must be a single regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            fail(f"{label} changed while it was read: {path}")
        return {
            "device": after.st_dev,
            "inode": after.st_ino,
            "mode": stat.S_IMODE(after.st_mode),
            "size": after.st_size,
            "mtime_ns": after.st_mtime_ns,
            "ctime_ns": after.st_ctime_ns,
            "sha256": sha256_bytes(data),
        }
    finally:
        os.close(descriptor)


def sha256(path: Path) -> str:
    return sha256_bytes(read_regular_bytes(path, "hash input"))


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
    try:
        return canonical_state_database(path, codex_home)
    except FileNotFoundError as exc:
        raise ValueError(f"state database does not exist: {path}") from exc


def read_packet(path: Path) -> str:
    data = read_regular_bytes(path, "worker packet")
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
            "cli-profile-compat only supports read-only profiles; developer and writer "
            "work must stay in the main outcome-owner session or an isolated worktree"
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
    artifact: Path,
    git_workdir: Path | None,
    git_diff_target: str | None,
) -> list[str]:
    def receipt_wrapper(command: str, workdir: Path) -> str:
        arguments = json.dumps(
            {
                "cmd": command,
                "workdir": str(workdir),
                "yield_time_ms": RECEIPT_YIELD_TIME_MS,
                "max_output_tokens": RECEIPT_MAX_OUTPUT_TOKENS,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            " When exec_command is exposed through functions.exec, the entire "
            "wrapper source must contain exactly these two statements and no others: "
            f"const receipt = await tools.exec_command({arguments}); "
            "text(JSON.stringify(receipt)); Do not print stdout and exit_code separately."
        )

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
    try:
        read_target = artifact.relative_to(cwd).as_posix()
    except ValueError:
        read_target = str(artifact)
    exact_read_command = f"cat -- {shlex.quote(read_target)}"
    developer_instructions += (
        "\nArtifact receipt requirement: before the final response, make one "
        "standalone exec_command call with cmd exactly "
        f"{json.dumps(exact_read_command)} and workdir exactly "
        f"{json.dumps(str(cwd))}. Do not chain, pipe, number, or truncate this "
        "command. Continue only after the tool reports exit code 0."
        + receipt_wrapper(exact_read_command, cwd)
    )
    if git_workdir is not None and git_diff_target is not None:
        exact_command = (
            "git --no-lazy-fetch -c core.fsmonitor=false --literal-pathspecs "
            "diff --no-ext-diff --no-textconv -- "
            f"{shlex.quote(git_diff_target)} 2>/dev/null"
        )
        developer_instructions += (
            "\nCompatibility receipt requirement: before the final response, make one "
            "standalone exec_command call with cmd exactly "
            f"{json.dumps(exact_command)} and workdir exactly "
            f"{json.dumps(str(git_workdir))}. Do not chain or pipe this command. "
            "Continue only after the tool reports exit code 0."
            + receipt_wrapper(exact_command, git_workdir)
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
        f"shell_environment_policy.set.TMPDIR={json.dumps(TOOL_SHELL_TMPDIR)}",
    ]
    for key, value in GIT_TOOL_ENVIRONMENT.items():
        command.extend(
            ["-c", f"shell_environment_policy.set.{key}={json.dumps(value)}"]
        )
    command.extend(
        [
            "-c",
            "developer_instructions="
            + json.dumps(developer_instructions, ensure_ascii=False),
        ]
    )
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


def hardened_git_environment() -> dict[str, str]:
    """Return the complete, non-inheriting environment for receipt Git reads."""
    return {
        "PATH": TOOL_SHELL_PATH,
        "TMPDIR": TOOL_SHELL_TMPDIR,
        "LANG": "C",
        "LC_ALL": "C",
        **GIT_TOOL_ENVIRONMENT,
    }


def run_hardened_git(
    root: Path,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a Git read with executable config surfaces disabled or fail-closed."""
    return subprocess.run(
        [
            "git",
            "--no-lazy-fetch",
            "-C",
            str(root),
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ],
        input=input_bytes,
        env=hardened_git_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def hardened_git_observation(root: Path) -> dict[str, object]:
    """Read HEAD/status without executing filters, fsmonitor, or lazy fetches."""
    revision = run_hardened_git(root, ["rev-parse", "HEAD"])
    paths = run_hardened_git(
        root,
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    )
    if revision.returncode != 0 or paths.returncode != 0:
        detail = (revision.stderr or paths.stderr).decode("utf-8", errors="replace").strip()
        fail(f"hardened Git identity read failed: {detail or 'unknown Git error'}")
    index_flags = run_hardened_git(
        root,
        ["ls-files", "-v", "-z", "--cached"],
    )
    if index_flags.returncode != 0:
        detail = index_flags.stderr.decode("utf-8", errors="replace").strip()
        fail(f"Git index-flag inventory failed: {detail or index_flags.returncode}")
    index_records = [value for value in index_flags.stdout.split(b"\0") if value]
    for record in index_records:
        if len(record) < 3 or record[1:2] != b" ":
            fail("Git index-flag inventory returned an invalid record")
        if record[:1] != b"H":
            path = os.fsdecode(record[2:])
            fail(
                "Git index flags can conceal worktree bytes; refusing "
                f"{record[:1].decode('ascii', errors='replace')} {path}"
            )
    path_records = [value for value in paths.stdout.split(b"\0") if value]
    if path_records:
        attributes = run_hardened_git(
            root,
            ["check-attr", "-z", "--stdin", "filter"],
            input_bytes=b"\0".join(path_records) + b"\0",
        )
        if attributes.returncode != 0:
            detail = attributes.stderr.decode("utf-8", errors="replace").strip()
            fail(f"Git filter inventory failed: {detail or attributes.returncode}")
        fields = attributes.stdout.split(b"\0")
        if not fields or fields[-1] != b"" or (len(fields) - 1) % 3:
            fail("Git filter inventory returned an invalid record set")
        for index in range(0, len(fields) - 1, 3):
            value = fields[index + 2]
            if value not in {b"unspecified", b"unset"}:
                path = os.fsdecode(fields[index])
                fail(f"Git state read refuses executable clean filter on {path}: {os.fsdecode(value)}")
    status = run_hardened_git(
        root,
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=all",
        ],
    )
    if status.returncode != 0:
        detail = status.stderr.decode("utf-8", errors="replace").strip()
        fail(f"hardened Git status failed: {detail or status.returncode}")
    try:
        head = revision.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Git HEAD was not ASCII") from exc
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        fail("Git HEAD did not resolve to an object id")
    return {
        "head": head,
        "status_bytes": status.stdout,
        "filter_paths_checked": len(path_records),
        "index_flags_checked": len(index_records),
        "index_flags_verified": True,
        "fsmonitor_disabled": True,
        "lazy_fetch_disabled": True,
        "replace_objects_disabled": True,
        "submodules_ignored": True,
    }


def git_root(cwd: Path) -> Path:
    result = run_hardened_git(cwd, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0 or not result.stdout.strip():
        fail("compat profile cwd must be inside a Git worktree")
    return Path(os.fsdecode(result.stdout.strip())).resolve()


def git_filter_safety(project_root: Path, artifact: Path) -> dict[str, str]:
    root = project_root.resolve()
    try:
        target = artifact.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("git safety artifact must stay inside the worktree") from exc
    result = run_hardened_git(
        root,
        ["--literal-pathspecs", "check-attr", "-z", "filter", "--", target],
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        fail(f"git clean-filter preflight failed: {detail or result.returncode}")
    fields = result.stdout.split(b"\0")
    if len(fields) != 4 or fields[-1] != b"":
        fail("git clean-filter preflight returned an invalid record")
    if fields[0] != os.fsencode(target) or fields[1] != b"filter":
        fail("git clean-filter preflight was not bound to the artifact")
    value = fields[2].decode("utf-8", errors="strict")
    if value not in {"unspecified", "unset"}:
        fail(f"artifact has an executable Git clean filter: {value}")
    return {
        "artifact": target,
        "filter_attribute": value,
        "attribute_source": GIT_EMPTY_TREE,
        "system_attributes_disabled": "true",
        "system_and_global_config_disabled": "true",
    }


def agents_snapshot(cwd: Path, codex_home: Path) -> dict[str, str]:
    project_root = git_root(cwd)
    locations = {codex_home.resolve(), project_root, cwd.resolve()}
    paths = {
        directory / filename
        for directory in locations
        for filename in ("AGENTS.md", "AGENTS.override.md")
    }
    return {str(path): file_state(path) for path in sorted(paths)}


def rollout_records(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    data = read_regular_bytes(path, "rollout")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("rollout must be UTF-8 JSONL") from exc
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid rollout JSON at line {number}") from exc
        if isinstance(value, dict):
            records.append(value)
    return records, data


def string_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(string_content(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(string_content(item) for item in value.values())
    return ""


def structured_exec_candidate(
    value: object,
) -> tuple[str, Path, int | None, int | None] | None:
    if not isinstance(value, dict) or set(value) - {
        "cmd",
        "workdir",
        "yield_time_ms",
        "max_output_tokens",
    }:
        return None
    if set(value) < {"cmd", "workdir"}:
        return None
    if not isinstance(value.get("cmd"), str) or not isinstance(
        value.get("workdir"), str
    ):
        return None
    for key in ("yield_time_ms", "max_output_tokens"):
        if key in value and (type(value[key]) is not int or value[key] < 0):
            return None
    workdir = Path(value["workdir"]).expanduser()
    if not workdir.is_absolute():
        return None
    return (
        value["cmd"],
        workdir,
        value.get("yield_time_ms"),
        value.get("max_output_tokens"),
    )


def command_candidates(
    call_input: str,
) -> list[tuple[str, Path, int | None, int | None]]:
    try:
        parsed = json.loads(call_input)
    except json.JSONDecodeError:
        parsed = None
    candidate = structured_exec_candidate(parsed)
    if candidate is not None:
        return [candidate]

    wrapper = re.fullmatch(
        r"\s*(?://\s*@exec:[^\r\n]*\r?\n)?"
        r"const\s+(?P<result>[A-Za-z_]\w*)\s*=\s*await\s+"
        r"tools\.exec_command\((?P<arguments>\{.*\})\);\s*"
        r"text\(JSON\.stringify\((?P=result)\)\)\s*;?\s*",
        call_input,
        re.DOTALL,
    )
    if wrapper is None:
        return []

    raw_arguments = wrapper.group("arguments")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        arguments = None
    candidate = structured_exec_candidate(arguments)
    if candidate is not None:
        return [candidate]

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
    candidate = structured_exec_candidate({"cmd": command, "workdir": raw_cwd})
    return [candidate] if candidate is not None else []


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


def command_reads_artifact(
    call_input: str, artifact: Path, expected_workdir: Path
) -> bool:
    candidates = command_candidates(call_input)
    if len(candidates) != 1:
        return False
    command, cwd, _yield_time_ms, _max_output_tokens = candidates[0]
    workdir = expected_workdir.resolve()
    if cwd is None or cwd.resolve() != workdir:
        return False
    try:
        read_target = artifact.resolve().relative_to(workdir).as_posix()
    except ValueError:
        read_target = str(artifact.resolve())
    expected = f"cat -- {shlex.quote(read_target)}"
    return command == expected


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
    command, workdir, yield_time_ms, max_output_tokens = candidates[0]
    project_root = project_root.resolve()
    if (
        workdir.resolve() != project_root
        or yield_time_ms != RECEIPT_YIELD_TIME_MS
        or max_output_tokens != RECEIPT_MAX_OUTPUT_TOKENS
    ):
        return False
    try:
        target = artifact.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return False
    return command == (
        "git --no-lazy-fetch -c core.fsmonitor=false --literal-pathspecs "
        "diff --no-ext-diff --no-textconv -- "
        f"{shlex.quote(target)} 2>/dev/null"
    )


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
    records: list[dict[str, Any]],
    project_root: Path,
    artifact: Path,
    filter_safety: dict[str, str],
) -> dict[str, object]:
    project_root = project_root.resolve()
    artifact = artifact.resolve()
    try:
        target = artifact.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise ValueError("git diff artifact must stay inside the project root") from exc
    target_before = regular_file_snapshot(artifact, "git diff artifact")
    source_before = hardened_git_observation(project_root)
    expected = run_hardened_git(
        project_root,
        [
            "--literal-pathspecs",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--",
            target,
        ],
    )
    if expected.returncode != 0:
        detail = expected.stderr.decode("utf-8", errors="replace").strip()
        fail(f"hardened Git diff read failed: {detail or expected.returncode}")
    try:
        expected_output = expected.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("hardened Git diff output must be UTF-8") from exc
    target_after = regular_file_snapshot(artifact, "git diff artifact")
    source_after = hardened_git_observation(project_root)
    if target_before != target_after:
        fail("git diff artifact changed during receipt verification")
    if source_before != source_after:
        fail("Git source state changed during receipt verification")

    pairs = exec_pairs_before_completion(records)
    matched: list[str] = []
    for call_id, (call_input, _output, raw_output) in pairs.items():
        if not command_reads_git_diff(call_input, project_root, artifact):
            continue
        result = structured_tool_result(raw_output)
        if (
            result is not None
            and result["exit_code"] == 0
            and result["output"] == expected_output
        ):
            matched.append(call_id)
    if not matched:
        fail(
            "no complete standalone git diff/output pair matches the hardened host read"
        )
    return {
        "required": True,
        "project_root": str(project_root),
        "artifact": str(artifact),
        "bound_read_calls": len(matched),
        "bound_output_sha256": [
            sha256_bytes(
                str(structured_tool_result(pairs[call_id][2])["output"]).encode("utf-8")
            )
            for call_id in matched
        ],
        "expected_output_sha256": sha256_bytes(expected.stdout),
        "exact_output_match": True,
        "required_yield_time_ms": RECEIPT_YIELD_TIME_MS,
        "required_max_output_tokens": RECEIPT_MAX_OUTPUT_TOKENS,
        "target_snapshot": target_before,
        "source_head": source_before["head"],
        "source_status_sha256": sha256_bytes(source_before["status_bytes"]),
        "source_state_unchanged": True,
        "exit_code_zero": True,
        "clean_filter_safety": filter_safety,
    }


def verify_direct_read(
    records: list[dict[str, Any]],
    artifact: Path,
    markers: list[str],
    expected_workdir: Path,
) -> dict[str, object]:
    require_regular_file(artifact, "required read artifact")
    pairs = exec_pairs_before_completion(records)
    artifact_bytes = read_regular_bytes(artifact, "required read artifact")
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
        if command_reads_artifact(call_input, artifact, expected_workdir)
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


def completion_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    completions = [
        record["payload"]
        for record in records
        if record.get("type") == "event_msg"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("type") == "task_complete"
    ]
    if len(completions) != 1:
        fail("rollout task completion message is not unique")
    completion = completions[0]
    if (
        not isinstance(completion.get("turn_id"), str)
        or not completion["turn_id"]
        or not isinstance(completion.get("last_agent_message"), str)
        or not completion["last_agent_message"].strip()
    ):
        fail("rollout task completion lacks a bound turn or non-empty message")
    return completion


def completed_message(records: list[dict[str, Any]]) -> str:
    return str(completion_payload(records)["last_agent_message"])


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


def thread_row(
    database_path: Path, thread_id: str, codex_home: Path
) -> dict[str, Any]:
    with canonical_state_connection(
        database_path, codex_home
    ) as (connection, _state_identity):
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
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
) -> str:
    metas = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "session_meta"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("id") == thread_id
    ]
    if len(metas) != 1 or metas[0].get("model_provider") != "openai":
        fail("rollout session identity is not uniquely bound to OpenAI")
    completion = completion_payload(records)
    contexts = [
        record.get("payload", {})
        for record in records
        if record.get("type") == "turn_context"
        and isinstance(record.get("payload"), dict)
        and record["payload"].get("turn_id") == completion["turn_id"]
    ]
    if len(contexts) != 1:
        fail("rollout completion turn does not have exactly one turn context")
    if contexts[0].get("model") != model or contexts[0].get("effort") != effort:
        fail(
            "rollout completion turn does not bind the requested model and reasoning effort"
        )
    return str(completion["last_agent_message"])


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
        output = process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        output = process.communicate()
    finally:
        kill_remaining_process_group(process.pid)
    return output


def kill_remaining_process_group(process_group_id: int) -> None:
    """Kill processes still in the original group or fail if cleanup is observable."""
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            # The group disappeared between kill and verification.
            return
        except PermissionError as probe_exc:
            raise ValueError(
                "process-group cleanup could not be verified after permission denial"
            ) from probe_exc
        raise ValueError(
            "process-group cleanup was denied while the group still existed"
        ) from exc


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
        kill_remaining_process_group(process.pid)
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

    if not MODEL_RE.fullmatch(args.model):
        fail("model must be an explicit model slug")
    if args.model.lower().startswith("claude-"):
        fail("external Claude models are disabled in the core Codex route")
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
    resolve_state_database(state_db, codex_home)

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
    git_filter_before = (
        git_filter_safety(project_root, artifact)
        if args.profile in GIT_DIFF_PROFILES
        else None
    )
    before_agents = agents_snapshot(cwd, codex_home)
    command = build_command(
        executable=executable,
        cwd=cwd,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        profile=profile,
        artifact=artifact,
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
    git_filter_after = (
        git_filter_safety(project_root, artifact)
        if args.profile in GIT_DIFF_PROFILES
        else None
    )
    if git_filter_before != git_filter_after:
        fail("Git clean-filter safety changed during compat execution")
    if timed_out:
        if thread_id is not None and thread_row(state_db, thread_id, codex_home).get("archived") != 1:
            fail(f"timed-out compat thread cleanup is incomplete: {thread_id}")
        suffix = f"; archived thread: {thread_id}" if thread_id is not None else ""
        fail(f"codex exec exceeded the {args.timeout_seconds}-second limit{suffix}")
    if result.returncode != 0:
        if thread_id is not None and thread_row(state_db, thread_id, codex_home).get("archived") != 1:
            fail(f"failed compat thread cleanup is incomplete: {thread_id}")
        suffix = f"; archived thread: {thread_id}" if thread_id is not None else ""
        fail(f"codex exec failed with exit code {result.returncode}{suffix}")
    parsed_thread_id, stdout_final = parse_exec_events(result.stdout)
    if thread_id != parsed_thread_id:
        fail("codex exec thread identity changed during event parsing")
    assert thread_id is not None

    row = thread_row(state_db, thread_id, codex_home)
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
    records, rollout_bytes = rollout_records(rollout)
    final_message = verify_rollout_identity(
        records, thread_id, args.model, args.reasoning_effort
    )
    if final_message != stdout_final:
        fail("stdout final does not match the persisted task completion")
    for marker in args.required_final_marker:
        if marker not in final_message:
            fail("persisted final is missing a required marker")
    read_receipt = verify_direct_read(
        records, artifact, args.required_read_marker, cwd
    )
    git_diff_receipt = (
        verify_git_diff_read(
            records, project_root, artifact, git_filter_before or {}
        )
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
        "tool_shell_tmpdir": TOOL_SHELL_TMPDIR,
        "tool_shell_git_environment": GIT_TOOL_ENVIRONMENT,
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
            "rollout_sha256": sha256_bytes(rollout_bytes),
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
