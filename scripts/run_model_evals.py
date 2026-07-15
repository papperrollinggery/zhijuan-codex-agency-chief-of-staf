#!/usr/bin/env -S python3 -I -S
"""Run real Codex smoke cases in an isolated project/config fixture.

This is not a credential-security boundary. The evaluated process runs as the
current OS user and can theoretically read its temporary auth file. Use only a
reviewed checkout and a dedicated low-privilege evaluation credential, ideally
inside a disposable OS user or container.
"""

from __future__ import annotations

import sys

if __name__ == "__main__" and (
    not sys.flags.isolated or not sys.flags.no_site
):
    print(
        "run_model_evals.py must be launched with: python3 -I -S",
        file=sys.stderr,
    )
    raise SystemExit(2)

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True


def _bootstrap_local_module_preflight() -> None:
    """Bind the complete local-import tree before adding scripts/ to sys.path."""
    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent
    git = Path("/usr/bin/git")
    if not git.is_file() or not os.access(git, os.X_OK):
        raise RuntimeError("isolated model-smoke bootstrap requires /usr/bin/git")
    environment = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
    }

    def git_read(arguments: list[str]) -> bytes:
        result = subprocess.run(
            [str(git), "--no-lazy-fetch", "-C", str(root), *arguments],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "isolated model-smoke bootstrap Git read failed: "
                + (detail or str(result.returncode))
            )
        return result.stdout

    object_format = git_read(["rev-parse", "--show-object-format"]).decode(
        "ascii", errors="strict"
    ).strip()
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError("unsupported Git object format for isolated bootstrap")
    expected: dict[str, str] = {}
    expected_directories: set[str] = set()
    for record in git_read(
        ["ls-tree", "-r", "-z", "--full-tree", "HEAD", "--", "scripts"]
    ).split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            _mode, object_type, object_id = metadata.split(b" ", 2)
        except ValueError as exc:
            raise RuntimeError("invalid Git tree record during isolated bootstrap") from exc
        path = os.fsdecode(raw_path)
        if object_type != b"blob":
            raise RuntimeError(f"local import-tree entry is not a Git blob: {path}")
        expected[path] = object_id.decode("ascii", errors="strict")
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("scripts"):
            expected_directories.add(parent.as_posix())
            parent = parent.parent

    observed: dict[str, str] = {}
    observed_directories: set[str] = set()

    def visit(directory: Path) -> None:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for entry in entries:
            candidate = directory / entry.name
            relative = candidate.relative_to(root).as_posix()
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                observed_directories.add(relative)
                visit(candidate)
                after = entry.stat(follow_symlinks=False)
                if (
                    not stat.S_ISDIR(after.st_mode)
                    or (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise RuntimeError(
                        f"local import-tree directory changed during preflight: {relative}"
                    )
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError(
                    f"local import-tree entry must be a single regular file: {relative}"
                )
            flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(candidate, flags)
            except OSError as exc:
                raise RuntimeError(
                    f"local import-tree file cannot be opened safely: {relative}"
                ) from exc
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                ):
                    raise RuntimeError(
                        f"local import-tree file changed before read: {relative}"
                    )
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    data = handle.read()
            finally:
                os.close(descriptor)
            digest = hashlib.new(object_format)
            digest.update(f"blob {len(data)}\0".encode("ascii"))
            digest.update(data)
            observed[relative] = digest.hexdigest()

    visit(script_dir)
    if observed != expected or observed_directories != expected_directories:
        extra = sorted(set(observed) - set(expected))
        missing = sorted(set(expected) - set(observed))
        drifted = sorted(
            path for path in set(observed) & set(expected) if observed[path] != expected[path]
        )
        extra_directories = sorted(observed_directories - expected_directories)
        missing_directories = sorted(expected_directories - observed_directories)
        raise RuntimeError(
            "isolated model-smoke local import tree differs from clean HEAD "
            f"(extra={extra}, missing={missing}, drifted={drifted}, "
            f"extra_directories={extra_directories}, "
            f"missing_directories={missing_directories})"
        )


if __name__ == "__main__":
    try:
        _bootstrap_local_module_preflight()
    except (OSError, RuntimeError, UnicodeError) as exc:
        print(f"model-smoke bootstrap refused execution: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from install_skill import RUNTIME_FILES, SKILL_NAME, copy_runtime, runtime_manifest
from protocol_contract import REVIEW_FIELDS, parse_reviewer_terminal
from resolve_role_route import verify_live_catalog
from run_profile_compat import (
    hardened_git_observation,
    kill_remaining_process_group,
    run_hardened_git,
    stop_process_group,
)
from validate_package import (
    REQUIRED_VISUAL_SURFACES,
    REVIEW_OUTCOME_RE,
    SKILL_SLUG_RE,
    valid_worker_packet as package_valid_worker_packet,
    worker_packet_fields,
)


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
THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
EVAL_TOOL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
PROGRESS_RE = re.compile(r"(?:MAIN_PROGRESS|\bprogress\b|进度)", re.IGNORECASE)
BOOT_PREFIX_RE = re.compile(
    r"^(?:<!--\s*(?:可选：)?COS_BOOT_RECEIPT[^>]*-->\s*\n)?任务已接管｜"
)
ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
ALLOWED_MODES = {"direct", "structured", "goal", "worker"}
ALLOWED_COLLABORATION = {
    "none",
    "native_subagents",
    "native_subagents_optional",
    "real_task",
}
ALLOWED_ACTIVATION = {"explicit", "implicit", "ordinary", "worker"}
ALLOWED_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
EVALUATOR_DEPENDENCIES = (
    "scripts/install_skill.py",
    "scripts/validate_package.py",
)
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
    "explicit-full-cycle": {
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
    "role-model-balanced-budget": {
        "should_trigger": True,
        "mode": "structured",
        "collaboration": "native_subagents_optional",
        "activation": "explicit",
    },
    "role-model-route-unavailable": {
        "should_trigger": True,
        "mode": "structured",
        "collaboration": "native_subagents",
        "activation": "explicit",
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


def native_executable_format(path: Path) -> str | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        header = os.read(descriptor, 4)
    finally:
        os.close(descriptor)
    if header == b"\x7fELF":
        return "elf"
    if header[:2] == b"MZ":
        return "pe"
    if header in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }:
        return "macho"
    return None


def sha256_regular_nofollow(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot safely open regular file: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"expected a regular file: {path}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def source_git_state(root: Path) -> dict[str, object]:
    """Fingerprint the evaluated worktree without embedding its diff in a receipt."""
    probe = run_hardened_git(root, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0:
        detail = probe.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"release source must be a readable Git worktree: {detail or probe.returncode}"
        )
    if probe.stdout.strip() != b"true":
        raise RuntimeError("release source did not identify as a Git worktree")
    observation = hardened_git_observation(root)
    status = bytes(observation["status_bytes"])
    return {
        "available": True,
        "head": observation["head"],
        "worktree_dirty": bool(status.strip()),
        "worktree_status_sha256": sha256_bytes(status),
        "filter_paths_checked": observation["filter_paths_checked"],
        "index_flags_checked": observation["index_flags_checked"],
        "index_flags_verified": observation["index_flags_verified"],
        "fsmonitor_disabled": observation["fsmonitor_disabled"],
        "lazy_fetch_disabled": observation["lazy_fetch_disabled"],
        "replace_objects_disabled": observation["replace_objects_disabled"],
        "submodules_ignored": observation["submodules_ignored"],
    }


def require_hardened_git(
    root: Path, arguments: list[str], operation: str
) -> bytes:
    result = run_hardened_git(root, arguments)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"hardened Git {operation} failed: {detail or result.returncode}"
        )
    return result.stdout


def source_head_manifest(root: Path, relative_paths: set[str]) -> dict[str, str]:
    """Require evaluated source bytes to equal the real, non-replaced HEAD blobs."""
    manifest: dict[str, str] = {}
    for relative in sorted(relative_paths):
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or "\\" in relative
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise RuntimeError(f"unsafe source HEAD path: {relative!r}")
        actual = read_regular_nofollow(root.joinpath(*path.parts))
        expected = require_hardened_git(
            root,
            ["cat-file", "blob", f"HEAD:{relative}"],
            f"HEAD blob read for {relative}",
        )
        if actual != expected:
            raise RuntimeError(
                f"release source bytes differ from the real HEAD blob: {relative}"
            )
        manifest[relative] = sha256_bytes(actual)
    return manifest


def initialize_fixture_repository(fixture: Path) -> None:
    """Create the eval baseline without inheriting templates, hooks, or Git config."""
    template = fixture.parent / f"empty-git-template-{fixture.name}"
    template.mkdir(mode=0o700)
    try:
        require_hardened_git(
            fixture,
            ["init", "-q", f"--template={template}", "."],
            "fixture init",
        )
        require_hardened_git(
            fixture,
            ["config", "user.name", "Model Eval"],
            "fixture user.name config",
        )
        require_hardened_git(
            fixture,
            ["config", "user.email", "model-eval@example.invalid"],
            "fixture user.email config",
        )
        require_hardened_git(
            fixture,
            ["-c", "core.hooksPath=/dev/null", "add", "--", "README.md", ".agents"],
            "fixture add",
        )
        require_hardened_git(
            fixture,
            [
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-qm",
                "model eval baseline",
            ],
            "fixture commit",
        )
    finally:
        template.rmdir()


def receipt_status(full_run: bool, results: list[dict[str, object]]) -> str:
    if not results or not all(item.get("status") == "passed" for item in results):
        return "failed"
    return "passed" if full_run else "passed_partial"


def verify_release_catalog(
    path: Path,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
    *,
    codex_bin: str | None = None,
    codex_home: Path | None = None,
    state_db: Path | None = None,
    thread_id: str | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    if requested_model is None or requested_reasoning_effort is None:
        raise RuntimeError("--catalog requires explicit --model and --reasoning-effort")
    raw = read_regular_nofollow(path.expanduser())
    try:
        catalog = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"release catalog is not valid UTF-8 JSON: {exc}") from exc
    if (
        not isinstance(catalog, dict)
        or set(catalog) != {"schema_version", "provenance", "models"}
        or catalog.get("schema_version") != 2
    ):
        raise RuntimeError(
            "release catalog must use schema 2 with provenance and models"
        )
    provenance = catalog.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "source",
        "source_id",
        "observed_for_requested_thread",
        "requested_thread_id",
        "root_provider",
        "canonical_state_store_bound",
        "model_provider_evidence",
    }:
        raise RuntimeError("release catalog provenance is missing")
    root_provider = provenance.get("root_provider")
    requested_thread_id = provenance.get("requested_thread_id")
    source_id = provenance.get("source_id")
    if (
        provenance.get("source") != "active-host-catalog"
        or provenance.get("observed_for_requested_thread") is not True
        or not isinstance(requested_thread_id, str)
        or THREAD_ID_RE.fullmatch(requested_thread_id) is None
        or provenance.get("canonical_state_store_bound") is not True
        or not isinstance(source_id, str)
        or re.fullmatch(r"codex-app-server:model/list:[0-9a-f]{64}", source_id)
        is None
        or root_provider != "openai"
        or provenance.get("model_provider_evidence")
        not in {"catalog-advertised", "root-state-inferred"}
    ):
        raise RuntimeError(
            "release catalog must be a canonical active-host requested-thread OpenAI readback"
        )
    models = catalog.get("models")
    if not isinstance(models, list):
        raise RuntimeError("release catalog models must be an array")
    matches = [
        item
        for item in models
        if isinstance(item, dict) and item.get("id") == requested_model
    ]
    if len(matches) != 1:
        raise RuntimeError("requested release model must appear exactly once in the catalog")
    model = matches[0]
    efforts = model.get("supported_reasoning")
    if (
        model.get("provider") != root_provider
        or model.get("model_class") != "judgment"
        or model.get("available") is not True
        or not isinstance(efforts, list)
        or requested_reasoning_effort not in efforts
        or requested_model.lower().startswith("claude-")
        or model.get("provider_evidence")
        not in {"catalog-advertised", "root-state-inferred"}
        or model.get("provider_evidence")
        != provenance.get("model_provider_evidence")
    ):
        raise RuntimeError(
            "release model must be an available current-catalog OpenAI judgment model "
            "supporting the requested effort"
        )
    live_arguments = (codex_bin, state_db, thread_id, cwd)
    if any(value is not None for value in live_arguments) and not all(
        value is not None for value in live_arguments
    ):
        raise RuntimeError(
            "live release catalog verification requires codex_bin, state_db, thread_id, and cwd"
        )
    live_verified = all(value is not None for value in live_arguments)
    if live_verified:
        if thread_id != requested_thread_id:
            raise RuntimeError(
                "release catalog thread does not match the explicit live thread"
            )
        assert codex_bin is not None
        assert state_db is not None
        assert thread_id is not None
        assert cwd is not None
        verify_live_catalog(
            catalog,
            codex_bin=codex_bin,
            codex_home=codex_home,
            cwd=cwd,
            state_db=state_db,
            thread_id=thread_id,
            root_provider=str(root_provider),
            timeout_seconds=20,
        )
    return {
        "verified": live_verified,
        "schema_validated": True,
        "live_readback_verified": live_verified,
        "sha256": sha256_bytes(raw),
        "source_id": source_id,
        "provider": root_provider,
        "model": requested_model,
        "model_class": "judgment",
        "reasoning_effort": requested_reasoning_effort,
        "requested_thread_id": requested_thread_id,
        "model_provider_evidence": model["provider_evidence"],
        "same_provider_independently_advertised": (
            model["provider_evidence"] == "catalog-advertised"
        ),
    }


def release_eligibility(
    status: str,
    full_run: bool,
    requested_model: str | None,
    requested_reasoning_effort: str | None,
    model_identity_verified: bool,
    release_catalog_verified: bool,
    source_git_state_verified: bool,
    credential_class: str,
    untested_capabilities: list[str],
) -> tuple[bool, bool]:
    prerelease = (
        status == "passed"
        and full_run
        and isinstance(requested_model, str)
        and bool(requested_model)
        and requested_reasoning_effort in ALLOWED_REASONING_EFFORTS
        and model_identity_verified
        and release_catalog_verified
        and source_git_state_verified
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
    env["PATH"] = EVAL_TOOL_PATH
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def resolve_codex_executable(value: str | None) -> Path:
    if value is None:
        raise RuntimeError("--codex-executable is required")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise RuntimeError("--codex-executable must be an absolute path")
    if candidate.is_symlink() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError("codex executable must be one executable non-symlink file")
    resolved = candidate.resolve()
    if native_executable_format(resolved) is None:
        raise RuntimeError("codex executable must use a native executable format")
    return resolved


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
    return package_valid_worker_packet(prompt)


def is_passive_skill_read(
    item: dict[str, object], installed_skill_path: Path | None, fixture_root: Path | None
) -> bool:
    """Allow only the host's one passive direct read of the installed skill."""
    if item.get("type") != "command_execution" or installed_skill_path is None:
        return False
    command = item.get("command")
    if not isinstance(command, str):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    candidate = Path(parts[1]) if len(parts) == 2 else None
    if candidate is not None and not candidate.is_absolute() and fixture_root is not None:
        candidate = fixture_root / candidate
    return (
        len(parts) == 2
        and Path(parts[0]).name == "cat"
        and candidate is not None
        and candidate.resolve(strict=False) == installed_skill_path.resolve(strict=False)
    )


def safe_relative_artifact(value: object, case_id: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"case {case_id} expected_file is not a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"case {case_id} expected_file escapes the fixture")
    return path


def observed_execution_identity(codex_home: Path, fixture: Path) -> dict[str, object]:
    expected_cwd = str(fixture.resolve())
    models: set[str] = set()
    providers: set[str] = set()
    efforts: set[str] = set()
    thread_ids: set[str] = set()
    session_count = 0
    turn_count = 0
    task_complete_count = 0
    parse_errors = 0
    session_observations: list[dict[str, object]] = []
    sessions_root = codex_home / "sessions"
    if not sessions_root.is_dir():
        return {
            "models": [],
            "providers": [],
            "reasoning_efforts": [],
            "thread_ids": [],
            "session_count": 0,
            "turn_count": 0,
            "task_complete_count": 0,
            "parse_errors": 0,
            "session_observations": [],
        }
    for path in sorted(sessions_root.rglob("*.jsonl")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        file_models: set[str] = set()
        file_providers: set[str] = set()
        file_efforts: set[str] = set()
        file_thread_ids: set[str] = set()
        file_context_turn_ids: set[str] = set()
        file_completion_turn_ids: set[str] = set()
        file_session_count = 0
        file_turn_count = 0
        file_parse_errors = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                file_parse_errors += 1
                continue
            if not isinstance(record, dict):
                file_parse_errors += 1
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            record_type = record.get("type")
            if (
                record_type == "session_meta"
                and str(payload.get("cwd", "")) == expected_cwd
            ):
                session_count += 1
                file_session_count += 1
                thread_id = payload.get("id")
                if isinstance(thread_id, str):
                    thread_ids.add(thread_id)
                    file_thread_ids.add(thread_id)
                provider = payload.get("model_provider")
                if isinstance(provider, str) and provider:
                    providers.add(provider)
                    file_providers.add(provider)
            if (
                record_type == "turn_context"
                and str(payload.get("cwd", "")) == expected_cwd
            ):
                turn_count += 1
                file_turn_count += 1
                turn_id = payload.get("turn_id")
                if isinstance(turn_id, str) and turn_id:
                    file_context_turn_ids.add(turn_id)
                model = payload.get("model")
                effort = payload.get("effort")
                if isinstance(model, str) and model:
                    models.add(model)
                    file_models.add(model)
                if isinstance(effort, str) and effort:
                    efforts.add(effort)
                    file_efforts.add(effort)
            if record_type == "event_msg" and payload.get("type") == "task_complete":
                turn_id = payload.get("turn_id")
                if isinstance(turn_id, str) and turn_id:
                    file_completion_turn_ids.add(turn_id)
        if file_session_count or file_turn_count:
            task_complete_count += len(file_completion_turn_ids)
            parse_errors += file_parse_errors
            session_observations.append(
                {
                    "providers": sorted(file_providers),
                    "models": sorted(file_models),
                    "reasoning_efforts": sorted(file_efforts),
                    "thread_ids": sorted(file_thread_ids),
                    "session_count": file_session_count,
                    "turn_count": file_turn_count,
                    "task_complete_count": len(file_completion_turn_ids),
                    "context_turn_ids": sorted(file_context_turn_ids),
                    "completion_turn_ids": sorted(file_completion_turn_ids),
                    "parse_errors": file_parse_errors,
                }
            )
    return {
        "models": sorted(models),
        "providers": sorted(providers),
        "reasoning_efforts": sorted(efforts),
        "thread_ids": sorted(thread_ids),
        "session_count": session_count,
        "turn_count": turn_count,
        "task_complete_count": task_complete_count,
        "parse_errors": parse_errors,
        "session_observations": session_observations,
    }


def execution_identity_matches(
    identity: dict[str, object],
    model: str | None,
    reasoning_effort: str | None,
    thread_id: str | None = None,
) -> bool:
    raw_session_observations = identity.get("session_observations", [])
    session_observations = (
        [item for item in raw_session_observations if isinstance(item, dict)]
        if isinstance(raw_session_observations, list)
        else []
    )
    root_observations = (
        [
            observation
            for observation in session_observations
            if observation.get("thread_ids") == [thread_id]
        ]
        if thread_id is not None
        else session_observations
    )
    return len(root_observations) == 1 and all(
        observation.get("providers") == ["openai"]
        and isinstance(observation.get("models"), list)
        and len(observation["models"]) == 1
        and isinstance(observation.get("reasoning_efforts"), list)
        and len(observation["reasoning_efforts"]) == 1
        and (model is None or observation["models"] == [model])
        and (
            reasoning_effort is None
            or observation["reasoning_efforts"] == [reasoning_effort]
        )
        and observation.get("turn_count") == 1
        and observation.get("session_count") == 1
        and observation.get("task_complete_count") == 1
        and observation.get("parse_errors") == 0
        and isinstance(observation.get("thread_ids"), list)
        and len(observation["thread_ids"]) == 1
        and THREAD_ID_RE.fullmatch(str(observation["thread_ids"][0])) is not None
        and (thread_id is None or observation["thread_ids"] == [thread_id])
        and observation.get("context_turn_ids")
        == observation.get("completion_turn_ids")
        and isinstance(observation.get("context_turn_ids"), list)
        and len(observation["context_turn_ids"]) == 1
        for observation in root_observations
    )


def child_execution_identity_matches(
    observation: dict[str, object], thread_id: str
) -> bool:
    return (
        observation.get("providers") == ["openai"]
        and observation.get("thread_ids") == [thread_id]
        and observation.get("session_count") == 1
        and observation.get("turn_count") == 1
        and observation.get("task_complete_count") == 1
        and observation.get("parse_errors") == 0
        and observation.get("context_turn_ids")
        == observation.get("completion_turn_ids")
        and isinstance(observation.get("context_turn_ids"), list)
        and len(observation["context_turn_ids"]) == 1
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
    if "visualization" in case:
        visual = case["visualization"]
        expected_keys = {"surface", "fallback", "must_not_claim", "must_contain_any", "must_not_contain"}
        if not isinstance(visual, dict) or set(visual) != expected_keys:
            raise RuntimeError(f"case {case_id} visualization contract is invalid")
        if visual["surface"] not in REQUIRED_VISUAL_SURFACES:
            raise RuntimeError(f"case {case_id} visualization surface is unsupported")
        if not isinstance(visual["fallback"], str) or not visual["fallback"]:
            raise RuntimeError(f"case {case_id} visualization fallback is required")
        for key in ("must_not_claim", "must_contain_any", "must_not_contain"):
            if not isinstance(visual[key], list) or not visual[key] or any(
                not isinstance(item, str) or not item for item in visual[key]
            ):
                raise RuntimeError(f"case {case_id} visualization {key} is invalid")
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
    if case.get("require_collab_event"):
        if (
            not has_file
            or not isinstance(case.get("expected_file_content"), str)
            or not case["expected_file_content"]
        ):
            raise RuntimeError(
                f"case {case_id} cold review needs one exact expected artifact"
            )
        if case["collaboration"] != "native_subagents" or not case.get("model_smoke"):
            raise RuntimeError(
                f"case {case_id} cold review must be a native-subagent model smoke"
            )
        if "review_evidence_marker" not in case:
            raise RuntimeError(f"case {case_id} cold review needs an undisclosed evidence marker")
        prompt = str(case["prompt"])
        if str(case["expected_text"]) in prompt:
            raise RuntimeError(f"case {case_id} cold review discloses the expected target")
        if str(case["review_evidence_marker"]) in prompt:
            raise RuntimeError(f"case {case_id} cold review discloses the evidence marker")
        if REVIEW_OUTCOME_RE.search(prompt):
            raise RuntimeError(f"case {case_id} cold review discloses the reviewer verdict")
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


def event_surface(
    events_text: str,
    final_text: str,
    installed_skill_path: Path | None = None,
    fixture_root: Path | None = None,
) -> dict[str, object]:
    messages: list[str] = []
    message_events: list[dict[str, object]] = []
    tool_item_ids: set[str] = set()
    spawns: dict[str, dict[str, object]] = {}
    waits: dict[str, dict[str, object]] = {}
    spawn_counts: dict[str, int] = {}
    wait_counts: dict[str, int] = {}
    successful_tool_event_indexes: list[int] = []
    task_action_event_indexes: list[int] = []
    collaboration_event_indexes: list[int] = []
    last_file_change_event_index = -1
    passive_skill_read_ids: set[str] = set()
    jsonl_parse_errors = 0
    thread_started_ids: list[str] = []
    turn_started_count = 0
    turn_completed_count = 0
    turn_failed_count = 0
    top_level_error_count = 0
    for index, line in enumerate(events_text.splitlines()):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            jsonl_parse_errors += 1
            continue
        if not isinstance(event, dict):
            jsonl_parse_errors += 1
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            thread_started_ids.append(thread_id if isinstance(thread_id, str) else "")
        elif event_type == "turn.started":
            turn_started_count += 1
        elif event_type == "turn.completed":
            turn_completed_count += 1
        elif event_type == "turn.failed":
            turn_failed_count += 1
        elif event_type == "error":
            top_level_error_count += 1
        if event_type not in {
            "item.started",
            "item.completed",
        }:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        completed = event.get("type") == "item.completed"
        if completed and item_type in ASSISTANT_ITEM_TYPES:
            for key in ("text", "content", "message"):
                value = item.get(key)
                if isinstance(value, str):
                    messages.append(value)
                    message_events.append({"event_index": index, "text": value})
                    break
        if item_type in TOOL_ITEM_TYPES:
            status = item.get("status")
            exit_code = item.get("exit_code")
            if item_type == "command_execution":
                tool_success = (
                    status == "completed"
                    and type(exit_code) is int
                    and exit_code == 0
                )
            else:
                tool_success = status == "completed"
            passive_skill_read = is_passive_skill_read(
                item, installed_skill_path, fixture_root
            )
            # The startup contract is about attempted task actions, not only
            # successful ones: a started or failed edit/read before boot is still an action.
            item_id = item.get("id")
            if (
                passive_skill_read
                and isinstance(item_id, str)
                and (not passive_skill_read_ids or item_id in passive_skill_read_ids)
            ):
                passive_skill_read_ids.add(item_id)
            else:
                task_action_event_indexes.append(index)
            if completed and tool_success:
                tool_item_ids.add(str(item.get("id", f"event-{index}")))
                successful_tool_event_indexes.append(index)
                if item_type == "file_change":
                    last_file_change_event_index = index
        if item_type == "collab_tool_call":
            # Any collaboration attempt, including wait/follow-up and a failed
            # dispatch, is a task action and is forbidden for a worker.
            task_action_event_indexes.append(index)
            collaboration_event_indexes.append(index)
        if item_type != "collab_tool_call" or not completed or item.get("status") != "completed":
            continue
        receiver_ids = item.get("receiver_thread_ids")
        if not isinstance(receiver_ids, list):
            receiver_ids = []
        if item.get("tool") == "spawn_agent":
            for receiver_id in receiver_ids:
                if isinstance(receiver_id, str) and receiver_id:
                    spawn_counts[receiver_id] = spawn_counts.get(receiver_id, 0) + 1
                    spawns[receiver_id] = {
                        "spawn_event_index": index,
                        "prompt": item.get("prompt") if isinstance(item.get("prompt"), str) else "",
                        "sender_thread_id": item.get("sender_thread_id"),
                        # Requested isolation is not a readback. Only an explicit
                        # tool-returned verification may establish this fact.
                        "context_isolation_verified": item.get("context_isolation_verified") is True,
                    }
        if item.get("tool") in {"wait", "wait_agent"}:
            states = item.get("agents_states")
            if not isinstance(states, dict):
                continue
            for receiver_id, state in states.items():
                if not isinstance(receiver_id, str) or not isinstance(state, dict):
                    continue
                message = state.get("message")
                if state.get("status") == "completed" and isinstance(message, str) and message.strip():
                    wait_counts[receiver_id] = wait_counts.get(receiver_id, 0) + 1
                    waits[receiver_id] = {
                        "wait_event_index": index,
                        "message": message,
                        "sender_thread_id": item.get("sender_thread_id"),
                        "receiver_declared": receiver_id in receiver_ids,
                    }

    root_thread_id = (
        thread_started_ids[0]
        if len(thread_started_ids) == 1
        and THREAD_ID_RE.fullmatch(thread_started_ids[0]) is not None
        else None
    )
    collaboration_identity_errors: list[str] = []
    valid_spawns: dict[str, dict[str, object]] = {}
    for receiver_id, spawn in spawns.items():
        if (
            root_thread_id is None
            or THREAD_ID_RE.fullmatch(receiver_id) is None
            or receiver_id == root_thread_id
            or spawn.get("sender_thread_id") != root_thread_id
            or spawn_counts.get(receiver_id) != 1
        ):
            collaboration_identity_errors.append(
                f"invalid root spawn identity for receiver {receiver_id!r}"
            )
            continue
        valid_spawns[receiver_id] = spawn
    valid_waits: dict[str, dict[str, object]] = {}
    for receiver_id, wait in waits.items():
        if (
            root_thread_id is None
            or THREAD_ID_RE.fullmatch(receiver_id) is None
            or receiver_id == root_thread_id
            or wait.get("sender_thread_id") != root_thread_id
            or wait.get("receiver_declared") is not True
            or wait_counts.get(receiver_id) != 1
        ):
            collaboration_identity_errors.append(
                f"invalid root wait identity for receiver {receiver_id!r}"
            )
            continue
        valid_waits[receiver_id] = wait
    spawns = valid_spawns
    waits = valid_waits
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
        "assistant_messages": message_events,
        "tool_events": len(tool_item_ids),
        "spawn_completed": spawns,
        "reviews_completed": completed_reviews,
        "successful_tool_event_indexes": successful_tool_event_indexes,
        "task_action_event_indexes": task_action_event_indexes,
        "collaboration_event_indexes": collaboration_event_indexes,
        "last_file_change_event_index": last_file_change_event_index,
        "jsonl_parse_errors": jsonl_parse_errors,
        "thread_started_ids": thread_started_ids,
        "turn_started_count": turn_started_count,
        "turn_completed_count": turn_completed_count,
        "turn_failed_count": turn_failed_count,
        "top_level_error_count": top_level_error_count,
        "collaboration_identity_errors": collaboration_identity_errors,
    }


def atomic_boot_block(text: str) -> bool:
    """Require a visible takeover line, optionally preceded by one hidden marker."""
    stripped = text.lstrip()
    match = re.match(r"<!--\s*(?:可选：)?COS_BOOT_RECEIPT[^>]*-->\s*\n", stripped)
    remainder = stripped[match.end() :] if match is not None else stripped
    first_visible = next((line.strip() for line in remainder.splitlines() if line.strip()), "")
    return first_visible.startswith("任务已接管｜")


def is_platform_skill_announcement(text: str) -> bool:
    """Recognize one narrow, pre-boot host-required Skill usage notice."""
    normalized = " ".join(text.strip().split()).lower()
    return normalized == (
        "我会使用 agency-chief-of-staff skill，因为本任务匹配它的职责；"
        "先完整读取 skill 说明。"
    )


def contract_failures(
    case: dict[str, Any], surface_or_events: str | dict[str, object]
) -> list[str]:
    failures: list[str] = []
    if isinstance(surface_or_events, str):
        surface = surface_or_events
        message_events: list[dict[str, object]] = []
        spawns: dict[str, dict[str, object]] = {}
    else:
        surface = str(surface_or_events["surface"])
        raw_messages = surface_or_events.get("assistant_messages", [])
        message_events = [
            item for item in raw_messages if isinstance(item, dict)
        ] if isinstance(raw_messages, list) else []
        raw_spawns = surface_or_events.get("spawn_completed", {})
        spawns = raw_spawns if isinstance(raw_spawns, dict) else {}
        raw_actions = surface_or_events.get("task_action_event_indexes", [])
        task_actions = [int(item) for item in raw_actions] if isinstance(raw_actions, list) else []
        raw_collaboration = surface_or_events.get("collaboration_event_indexes", [])
        collaboration_actions = (
            [int(item) for item in raw_collaboration]
            if isinstance(raw_collaboration, list)
            else []
        )
    if isinstance(surface_or_events, str):
        task_actions = []
        collaboration_actions = []
    boot_indexes = [
        int(item["event_index"])
        for item in message_events
        if BOOT_PREFIX_RE.match(str(item.get("text", "")).lstrip())
    ]
    booted = (
        "任务已接管｜" in surface
        if isinstance(surface_or_events, str)
        else len(boot_indexes) == 1
    )
    if case["should_trigger"] and not booted:
        failures.append("should_trigger=true but no takeover line was observed")
    if not case["should_trigger"] and booted:
        failures.append("should_trigger=false but COS_BOOT_RECEIPT was observed")
    if not case["should_trigger"]:
        if case["activation"] == "worker" and len(message_events) != 1:
            failures.append("worker must return exactly one terminal message")
        if case["activation"] == "worker" and PROGRESS_RE.search(surface):
            failures.append("worker or ordinary case emitted main-thread progress")
        if collaboration_actions:
            failures.append("worker or ordinary case attempted collaboration")
        return failures

    boot_message = ""
    if boot_indexes:
        boot_event = next(
            item for item in message_events if int(item["event_index"]) == boot_indexes[0]
        )
        boot_message = str(boot_event.get("text", ""))
    elif isinstance(surface_or_events, str):
        boot_message = surface
    if booted and not atomic_boot_block(boot_message):
        failures.append("boot marker and first visible takeover line are not atomic")

    if message_events and len(boot_indexes) != 1:
        failures.append("main session must emit exactly one takeover line")
    if boot_indexes:
        boot_index = boot_indexes[0]
        preboot_messages = [
            item for item in message_events if int(item["event_index"]) < boot_index
        ]
        if preboot_messages and not (
            len(preboot_messages) == 1
            and is_platform_skill_announcement(str(preboot_messages[0].get("text", "")))
        ):
            failures.append("assistant message preceded COS_BOOT_RECEIPT")
        progress_indexes = [
            int(item["event_index"])
            for item in message_events
            if PROGRESS_RE.search(str(item.get("text", "")))
        ]
        if any(index <= boot_index for index in progress_indexes):
            failures.append("main progress preceded COS_BOOT_RECEIPT")
        if any(index <= boot_index for index in task_actions):
            failures.append("task action preceded COS_BOOT_RECEIPT")
        if any(
            int(spawn.get("spawn_event_index", -1)) <= boot_index
            for spawn in spawns.values()
            if isinstance(spawn, dict)
        ):
            failures.append("reviewer spawn preceded COS_BOOT_RECEIPT")

    has_compat_marker = "COS_BOOT_RECEIPT" in boot_message
    mode_markers = {
        "direct": "模式：直接",
        "structured": "模式：结构化",
        "goal": "模式：Goal",
    }
    marker = mode_markers.get(str(case["mode"]))
    if has_compat_marker and marker and marker not in boot_message:
        failures.append(f"boot receipt does not declare expected {marker}")

    collaboration = case["collaboration"]
    accepted = {
        "none": ("协作：无",),
        "native_subagents": ("协作：原生子代理",),
        "native_subagents_optional": ("协作：无", "协作：原生子代理"),
        "real_task": ("协作：真实任务",),
    }[collaboration]
    if has_compat_marker and not any(value in boot_message for value in accepted):
        failures.append(
            "boot receipt does not declare expected collaboration: " + " or ".join(accepted)
        )
    visual = case.get("visualization")
    if isinstance(visual, dict):
        surface_markers = {
            "task-stage": ("阶段", "步骤", "::codex-inline-vis"),
            "decision": ("选择", "决定", "推荐"),
            "impact": ("影响", "保留", "需要复核"),
            "evidence-list": ("证据", "请上传", "尚无", "尚未提供", "当前版本"),
            "numeric-trend": ("趋势", "曲线", "图表", "数据表"),
            "image-review": ("图片", "预览", "页面", "幻灯片"),
        }
        fallback_markers = {
            "markdown-step-list": ("阶段", "步骤"),
            "comparison-table": ("选择", "方案", "推荐"),
            "mermaid": ("```mermaid",),
            "markdown-list": ("- ", "请上传", "尚无", "尚未提供"),
            "data-table": ("|", "数据表"),
            "numbered-findings": ("1.", "问题", "发现"),
        }
        surface_kind = visual.get("surface")
        expected_surface = surface_markers.get(str(surface_kind), ())
        if expected_surface and not any(marker in surface for marker in expected_surface):
            failures.append(f"visualization output does not represent surface {surface_kind!r}")
        fallback_kind = visual.get("fallback")
        expected_fallback = fallback_markers.get(str(fallback_kind), ())
        if "::codex-inline-vis" not in surface and expected_fallback and not any(
            marker in surface for marker in expected_fallback
        ):
            failures.append(f"visualization fallback {fallback_kind!r} was not represented")
        required_any = visual.get("must_contain_any", [])
        if isinstance(required_any, list) and not any(
            isinstance(marker, str) and marker in surface for marker in required_any
        ):
            failures.append("visualization output did not match any required surface marker")
        forbidden = visual.get("must_not_contain", [])
        if isinstance(forbidden, list):
            for marker in forbidden:
                if isinstance(marker, str) and marker in surface:
                    failures.append(f"visualization output contains forbidden marker {marker!r}")
        forbidden_claims = visual.get("must_not_claim", [])
        if isinstance(forbidden_claims, list):
            for claim in forbidden_claims:
                if isinstance(claim, str) and claim in surface:
                    failures.append(f"visualization output makes forbidden claim {claim!r}")
    return failures


def expected_reviewer_packet_fields(expected_file: str) -> dict[str, str]:
    return {
        "委派目标": f"独立复核当前 {expected_file} 是否完成本次最小修改。",
        "读取范围": f"{expected_file}；git diff -- {expected_file}；git diff --check。",
        "写入范围": "无。",
        "期望产物": "REVIEW_TARGET、REVIEW_READBACK、REVIEW_FINDINGS、REVIEW_RESIDUAL_RISK、REVIEW_VERDICT，均填实际读回值。",
        "验证要求": "直接读取当前 artifact 与相关 diff 后返回实际读回及判定；不得使用主线程提供的值。",
        "停止条件": "返回唯一终态；不启动、不派发。",
    }


def review_prompt_is_self_contained(
    prompt: str, expected_file: str, expected_text: str, evidence_marker: str
) -> bool:
    fields = worker_packet_fields(prompt)
    return (
        fields == expected_reviewer_packet_fields(expected_file)
        and expected_text not in prompt
        and evidence_marker not in prompt
        and SKILL_SLUG_RE.search(prompt) is None
        and REVIEW_OUTCOME_RE.search(prompt) is None
        and "guard" not in prompt.lower()
        and "启动幕僚长" not in prompt
        and "使用本 skill" not in prompt.lower()
        and "COS_BOOT_RECEIPT" not in prompt
    )


def reviewer_terminal_fields(message: str) -> dict[str, str] | None:
    """Accept only the runtime's shared five-field reviewer terminal."""
    try:
        return parse_reviewer_terminal(message)
    except ValueError:
        return None


def verified_reviewer_terminal(
    message: str, expected_file: str, expected_text: str, evidence_marker: str
) -> dict[str, str] | None:
    fields = reviewer_terminal_fields(message)
    if fields is None:
        return None
    if tuple(fields) != REVIEW_FIELDS or fields["REVIEW_TARGET"] != expected_file:
        return None
    if (
        expected_text not in fields["REVIEW_READBACK"]
        or evidence_marker not in fields["REVIEW_READBACK"]
    ):
        return None
    if fields["REVIEW_VERDICT"] != "PASS":
        return None
    return fields


def independent_review_final_failures(
    final_text: str,
    completed_reviews: dict[str, object],
    reviewer_terminals: dict[str, dict[str, str]],
) -> list[str]:
    """Reject a claimed reviewer result when the host never proved one."""
    failures: list[str] = []
    if not reviewer_terminals:
        if "独立审核未验证" not in final_text:
            failures.append("final answer did not disclose independent review unverified")
        if not completed_reviews and (
            "REVIEW_READBACK" in final_text
            or "采纳" in final_text
            or "reviewer 已返回" in final_text.lower()
            or "reviewer 结论" in final_text.lower()
        ):
            failures.append("final answer claimed reviewer evidence without a completed spawn chain")
        return failures
    adopted = any(
        "采纳" in final_text
        and all(
            label in final_text and value in final_text
            for label, value in terminal.items()
        )
        for terminal in reviewer_terminals.values()
    )
    if not adopted:
        failures.append("final answer did not adopt or report the independent review result")
    return failures


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
    observation = hardened_git_observation(fixture)
    status = bytes(observation["status_bytes"]).decode("utf-8", errors="strict")
    paths: set[str] = set()
    for line in status.splitlines():
        if len(line) >= 4:
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            paths.add(path)
    return paths


def fixture_file_manifest(fixture: Path) -> dict[str, str]:
    """Hash the visible fixture tree without trusting its Git index or status."""
    root = fixture.resolve(strict=True)
    root_info = root.lstat()
    if root.is_symlink() or not stat.S_ISDIR(root_info.st_mode):
        raise RuntimeError(f"fixture root must be a non-symlink directory: {fixture}")
    manifest: dict[str, str] = {}

    def visit(directory: Path) -> None:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for entry in entries:
            if directory == root and entry.name == ".git":
                continue
            path = directory / entry.name
            relative = path.relative_to(root).as_posix()
            before = path.lstat()
            mode = stat.S_IMODE(before.st_mode)
            if stat.S_ISLNK(before.st_mode):
                target = os.readlink(path)
                after = path.lstat()
                if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                    raise RuntimeError(f"fixture symlink changed during manifest read: {relative}")
                manifest[relative] = f"symlink:{mode:o}:{target}"
                continue
            if stat.S_ISDIR(before.st_mode):
                manifest[relative] = f"directory:{mode:o}"
                visit(path)
                after = path.lstat()
                if (
                    not stat.S_ISDIR(after.st_mode)
                    or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                ):
                    raise RuntimeError(
                        f"fixture directory changed during manifest read: {relative}"
                    )
                continue
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise RuntimeError(
                    f"fixture contains a non-regular or multiply-linked entry: {relative}"
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                ):
                    raise RuntimeError(
                        f"fixture file changed before manifest read: {relative}"
                    )
                digest = hashlib.sha256()
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
            finally:
                os.close(descriptor)
            after = path.lstat()
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_nlink != 1
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise RuntimeError(f"fixture file changed during manifest read: {relative}")
            manifest[relative] = f"file:{mode:o}:{digest.hexdigest()}"

    visit(root)
    return manifest


def fixture_scope_failures(
    baseline_manifest: dict[str, str],
    final_manifest: dict[str, str],
    baseline_head: object,
    final_head: object,
    expected_file: str | None,
) -> tuple[list[str], list[str]]:
    changed = sorted(
        path
        for path in set(baseline_manifest) | set(final_manifest)
        if baseline_manifest.get(path) != final_manifest.get(path)
    )
    allowed_paths: set[str] = set()
    if expected_file is not None:
        allowed_paths.add(expected_file)
        expected_path = PurePosixPath(expected_file)
        for parent in expected_path.parents:
            if parent == PurePosixPath("."):
                continue
            parent_text = parent.as_posix()
            if (
                parent_text not in baseline_manifest
                and str(final_manifest.get(parent_text, "")).startswith("directory:")
            ):
                allowed_paths.add(parent_text)
    allowed = sorted(allowed_paths)
    failures: list[str] = []
    if changed != allowed:
        failures.append(
            f"fixture manifest scope mismatch: expected {allowed!r}, observed {changed!r}"
        )
    if final_head != baseline_head:
        failures.append("fixture HEAD changed during model execution")
    return failures, changed


def run_evaluated_codex(
    command: list[str],
    *,
    timeout: int | float,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], bool]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        kill_remaining_process_group(process.pid)
        return (
            subprocess.CompletedProcess(command, process.returncode, stdout, stderr),
            False,
        )
    except subprocess.TimeoutExpired:
        stdout, stderr = stop_process_group(process)
        return (
            subprocess.CompletedProcess(command, process.returncode, stdout, stderr),
            True,
        )
    except BaseException:
        stop_process_group(process)
        raise


def run_case(
    case: dict[str, Any],
    fixture: Path,
    case_dir: Path,
    codex_executable: Path,
    model: str | None,
    reasoning_effort: str | None,
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
    expected_file_value = case.get("expected_file")
    expected_manifest_file = (
        safe_relative_artifact(expected_file_value, str(case["id"])).as_posix()
        if isinstance(expected_file_value, str)
        else None
    )
    baseline_manifest = fixture_file_manifest(fixture)
    baseline_git = hardened_git_observation(fixture)
    if bytes(baseline_git["status_bytes"]).strip():
        raise RuntimeError(f"case {case['id']} fixture baseline is not clean")
    if fixture_file_manifest(fixture) != baseline_manifest:
        raise RuntimeError(f"case {case['id']} fixture changed during baseline observation")
    command = [
        str(codex_executable),
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--enable",
        "multi_agent",
        "-c",
        "shell_environment_policy.inherit=none",
        "-c",
        f"shell_environment_policy.set.PATH={json.dumps(EVAL_TOOL_PATH)}",
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
        command.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"])
    command.append(str(case["prompt"]))

    completed, timed_out = run_evaluated_codex(
        command,
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

    parsed = event_surface(
        events_text,
        final_text,
        fixture / ".agents" / "skills" / SKILL_NAME / "SKILL.md",
        fixture,
    )
    surface = str(parsed["surface"])
    final_lower = final_text.lower()
    failures = contract_failures(case, parsed)
    thread_started_ids = parsed["thread_started_ids"]
    assert isinstance(thread_started_ids, list)
    lifecycle_thread_id = (
        str(thread_started_ids[0])
        if len(thread_started_ids) == 1
        and THREAD_ID_RE.fullmatch(str(thread_started_ids[0])) is not None
        else None
    )
    if parsed["jsonl_parse_errors"]:
        failures.append(
            f"codex --json emitted {parsed['jsonl_parse_errors']} malformed non-empty JSONL record(s)"
        )
    if lifecycle_thread_id is None:
        failures.append("codex --json did not emit exactly one valid thread.started id")
    if parsed["turn_started_count"] != 1:
        failures.append("codex --json did not emit exactly one turn.started")
    if parsed["turn_completed_count"] != 1:
        failures.append("codex --json did not emit exactly one turn.completed")
    if parsed["turn_failed_count"] != 0:
        failures.append("codex --json emitted turn.failed")
    if parsed["top_level_error_count"] != 0:
        failures.append("codex --json emitted a top-level error")
    raw_collaboration_identity_errors = parsed["collaboration_identity_errors"]
    assert isinstance(raw_collaboration_identity_errors, list)
    failures.extend(
        f"collaboration event identity invalid: {error}"
        for error in raw_collaboration_identity_errors
    )
    if timed_out:
        failures.append(f"codex exceeded the {timeout}-second case limit")
    final_manifest = fixture_file_manifest(fixture)
    final_git = hardened_git_observation(fixture)
    if fixture_file_manifest(fixture) != final_manifest:
        raise RuntimeError(f"case {case['id']} fixture changed during final observation")
    scope_failures, manifest_changed_paths = fixture_scope_failures(
        baseline_manifest,
        final_manifest,
        baseline_git["head"],
        final_git["head"],
        expected_manifest_file,
    )
    failures.extend(scope_failures)
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

    execution_identity = observed_execution_identity(Path(env["CODEX_HOME"]), fixture)
    observed_models = execution_identity["models"]
    observed_providers = execution_identity["providers"]
    observed_efforts = execution_identity["reasoning_efforts"]
    raw_session_observations = execution_identity.get("session_observations", [])
    session_observations = (
        [item for item in raw_session_observations if isinstance(item, dict)]
        if isinstance(raw_session_observations, list)
        else []
    )
    model_identity_verified = execution_identity_matches(
        execution_identity, model, reasoning_effort, lifecycle_thread_id
    )
    if not model_identity_verified:
        failures.append(
            "isolated session did not bind OpenAI provider, model, and reasoning effort together"
        )

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
        diff_check = run_hardened_git(
            fixture,
            [
                "--literal-pathspecs",
                "diff",
                "--check",
                "--no-ext-diff",
                "--no-textconv",
            ],
        )
        if diff_check.returncode != 0:
            failures.append("git diff --check failed for expected artifact")

    completed_reviews = parsed["reviews_completed"]
    assert isinstance(completed_reviews, dict)
    review_ids: list[str] = []
    review_session_identity_ids: list[str] = []
    context_verified_review_ids: list[str] = []
    reviewer_terminals: dict[str, dict[str, str]] = {}
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
            child_observations = [
                observation
                for observation in session_observations
                if observation.get("thread_ids") == [receiver_id]
            ]
            if len(child_observations) != 1 or not child_execution_identity_matches(
                child_observations[0], receiver_id
            ):
                continue
            if expected_file and expected_file not in message:
                continue
            if expected_text and expected_text not in message:
                continue
            if review_evidence_marker and review_evidence_marker in prompt:
                continue
            review_prompt_self_contained = review_prompt_is_self_contained(
                prompt,
                str(expected_file),
                str(expected_text),
                str(review_evidence_marker),
            )
            if not review_prompt_self_contained:
                continue
            terminal = verified_reviewer_terminal(
                message,
                str(expected_file),
                str(expected_text),
                str(review_evidence_marker),
            )
            if terminal is None:
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
            review_session_identity_ids.append(receiver_id)
            reviewer_terminals[receiver_id] = terminal
            if review.get("context_isolation_verified") is True:
                context_verified_review_ids.append(receiver_id)
        if not review_ids:
            failures.append(
                "reviewer result did not prove post-change artifact readback with fresh evidence"
            )
        failures.extend(
            independent_review_final_failures(
                final_text, completed_reviews, reviewer_terminals
            )
        )
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
        "reviewer_session_identities_verified": len(review_session_identity_ids),
        "cold_context_isolation_verified_count": len(context_verified_review_ids),
        "review_receiver_ids": review_ids,
        "review_prompt_self_contained": review_prompt_self_contained,
        "observed_models": observed_models,
        "observed_model_providers": observed_providers,
        "observed_reasoning_efforts": observed_efforts,
        "model_identity_verified": model_identity_verified,
        "model_identity_session_count": len(session_observations),
        "event_thread_id": lifecycle_thread_id,
        "event_jsonl_parse_errors": parsed["jsonl_parse_errors"],
        "event_turn_started_count": parsed["turn_started_count"],
        "event_turn_completed_count": parsed["turn_completed_count"],
        "event_turn_failed_count": parsed["turn_failed_count"],
        "event_top_level_error_count": parsed["top_level_error_count"],
        "fixture_head_unchanged": final_git["head"] == baseline_git["head"],
        "fixture_manifest_changed_paths": manifest_changed_paths,
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


def codex_version(codex_executable: Path) -> str:
    result = subprocess.run(
        [str(codex_executable), "--version"], text=True, capture_output=True, check=True
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
    parser.add_argument(
        "--codex-executable",
        required=True,
        help="Absolute native Codex executable used for every evaluated case.",
    )
    parser.add_argument("--model", help="Optional explicit model; required for release eligibility.")
    parser.add_argument(
        "--reasoning-effort",
        choices=sorted(ALLOWED_REASONING_EFFORTS),
        help="Explicit reasoning effort for the requested model.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help=(
            "Requested-thread catalog receipt from inspect_codex_models.py; a live-verified "
            "judgment-class match is required for release eligibility."
        ),
    )
    parser.add_argument(
        "--catalog-state-db",
        type=Path,
        help="Canonical state_5.sqlite entry; required with --catalog.",
    )
    parser.add_argument(
        "--catalog-codex-home",
        type=Path,
        help="Optional non-default Codex home used by the live catalog App Server.",
    )
    parser.add_argument(
        "--catalog-thread-id",
        help="Requested root task id; required with --catalog and must match its provenance.",
    )
    parser.add_argument(
        "--catalog-cwd",
        type=Path,
        help="Existing project directory for live App Server readback; required with --catalog.",
    )
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
    if args.reasoning_effort and not args.model:
        raise RuntimeError("--reasoning-effort requires --model")
    codex_executable = resolve_codex_executable(args.codex_executable)
    codex_executable_sha256 = sha256_regular_nofollow(codex_executable)

    root = args.root.resolve()
    if args.catalog is not None and (
        args.catalog_state_db is None
        or args.catalog_thread_id is None
        or args.catalog_cwd is None
    ):
        raise RuntimeError(
            "--catalog requires --catalog-state-db, --catalog-thread-id, and --catalog-cwd for live readback"
        )
    release_catalog = (
        verify_release_catalog(
            args.catalog,
            args.model,
            args.reasoning_effort,
            codex_bin=str(codex_executable),
            codex_home=args.catalog_codex_home,
            state_db=args.catalog_state_db,
            thread_id=args.catalog_thread_id,
            cwd=args.catalog_cwd,
        )
        if args.catalog is not None
        else {"verified": False, "reason": "no requested-thread catalog supplied"}
    )
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
    evaluator_dependency_hashes = {
        relative: sha256_regular_nofollow(root / relative)
        for relative in EVALUATOR_DEPENDENCIES
    }
    source_git_state_start = source_git_state(root)
    if source_git_state_start.get("worktree_dirty") is not False:
        raise RuntimeError("auth-bearing model smoke requires a clean source worktree")
    source_head_paths = set(RUNTIME_FILES) | set(EVALUATOR_DEPENDENCIES) | {
        "evals/behavior_cases.json",
        "scripts/run_model_evals.py",
    }
    source_head_manifest_start = source_head_manifest(root, source_head_paths)
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
            initialize_fixture_repository(fixture)
            env = build_isolated_env(fixture_home, isolated_codex_home)
            results.append(
                run_case(
                    case,
                    fixture,
                    out / case_id,
                    codex_executable,
                    args.model,
                    args.reasoning_effort,
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
            or any(
                sha256_regular_nofollow(root / relative) != digest
                for relative, digest in evaluator_dependency_hashes.items()
            )
            or source_git_state(root) != source_git_state_start
            or source_head_manifest(root, source_head_paths)
            != source_head_manifest_start
        )
    except (OSError, ValueError, RuntimeError):
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
    model_identity_verified = all(
        item.get("model_identity_verified") is True for item in results
    )
    prerelease_eligible, stable_eligible = release_eligibility(
        status,
        full_run,
        args.model,
        args.reasoning_effort,
        model_identity_verified,
        release_catalog.get("verified") is True,
        source_git_state_start.get("available") is True
        and source_git_state_start.get("worktree_dirty") is False,
        args.auth_credential_class,
        untested_capabilities,
    )
    summary = {
        "receipt_type": "MODEL_SMOKE_RECEIPT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "codex_version": codex_version(codex_executable),
        "codex_executable": str(codex_executable),
        "codex_executable_sha256": codex_executable_sha256,
        "codex_executable_format": native_executable_format(codex_executable),
        "requested_model": args.model or "host_default",
        "requested_reasoning_effort": args.reasoning_effort or "host_default",
        "prerelease_model_requirement": "current-catalog-openai-judgment",
        "release_catalog": release_catalog,
        "observed_models": observed_models,
        "observed_model_providers": sorted(
            {
                provider
                for result in results
                for provider in result.get("observed_model_providers", [])
                if isinstance(provider, str)
            }
        ),
        "observed_reasoning_efforts": sorted(
            {
                effort
                for result in results
                for effort in result.get("observed_reasoning_efforts", [])
                if isinstance(effort, str)
            }
        ),
        "model_identity_verified": model_identity_verified,
        "skill_manifest_sha256": sha256_bytes(manifest_json),
        "behavior_cases_sha256": sha256_bytes(cases_bytes),
        "runner_sha256": sha256_bytes(runner_bytes),
        "evaluator_dependencies_sha256": evaluator_dependency_hashes,
        "source_git_state": source_git_state_start,
        "source_head_manifest_sha256": sha256_bytes(
            json.dumps(source_head_manifest_start, sort_keys=True).encode("utf-8")
        ),
        "source_head_path_count": len(source_head_manifest_start),
        "runtime_snapshot_verified": snapshot_manifest == source_manifest,
        "source_drift_detected": source_drift_detected,
        "suite_contract_verified": True,
        "agents_routing_dependency": False,
        "run_scope": "full" if full_run else "partial",
        "all_model_smoke_case_ids": [case["id"] for case in all_smoke_cases],
        "selected_case_ids": [case["id"] for case in smoke_cases],
        "selected_count": len(smoke_cases),
        "total_model_smoke_count": len(all_smoke_cases),
        "model_identity_source": "isolated_codex_session_metadata",
        "prerelease_evidence_eligible": prerelease_eligible,
        "stable_release_evidence_eligible": stable_eligible,
        "release_evidence_eligible": stable_eligible,
        "untested_capabilities": untested_capabilities,
        "auth_safety": {
            "dedicated_low_privilege_auth_recommended": True,
            "same_os_user_is_not_a_secret_boundary": True,
            "shell_environment_inherit": "none",
            "process_path": EVAL_TOOL_PATH,
            "tool_shell_path": EVAL_TOOL_PATH,
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
