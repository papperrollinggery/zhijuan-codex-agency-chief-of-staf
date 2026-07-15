#!/usr/bin/env python3
"""Preview, enable, inspect, or disable Codex-native role routing controls.

This owns four routing fields required to expose routed child metadata. A legacy
boolean `multi_agent_v2` value is temporarily represented as a table with its
`enabled` value preserved exactly, then restored to the original scalar on disable.
It never selects a model or enables an external provider. Without --apply it does
not create CODEX_HOME or mutate routing config/journal. Operations lock the existing
CODEX_HOME directory inode before App Server initialization so status and mutations
cannot observe each other midway.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True

from inspect_codex_models import CodexAppServer, resolve_executable


STATE_SCHEMA = 2
STATE_FILENAME = ".agency-chief-native-routing.json"
MANAGED_BY = "agency-chief-of-staff"
MARKER = "[managed by agency-chief-of-staff native routing v1]"
TOOL_NAMESPACE = "agents"
PROBE_CONFIG_OVERRIDES = (
    "features.multi_agent_v2.hide_spawn_agent_metadata=false",
    'features.multi_agent_v2.tool_namespace="agents"',
    'features.multi_agent_v2.multi_agent_mode_hint_text="probe-mode"',
    'features.multi_agent_v2.usage_hint_text="probe-usage"',
)
PROBE_EXPECTED = {
    "metadata": False,
    "namespace": "agents",
    "mode": "probe-mode",
    "usage": "probe-usage",
}
PROBE_ENV_ALLOWLIST = {
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
DESKTOP_CODEX_CANDIDATES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
    Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
    Path.home() / "Applications/Codex.app/Contents/Resources/codex",
)
MISSING = object()
FIELD_PATHS = {
    "metadata": "features.multi_agent_v2.hide_spawn_agent_metadata",
    "namespace": "features.multi_agent_v2.tool_namespace",
    "mode": "features.multi_agent_v2.multi_agent_mode_hint_text",
    "usage": "features.multi_agent_v2.usage_hint_text",
}
MODE_HINT = f"""{MARKER}
The root task model is the outcome owner. It decides whether delegation helps, chooses the smallest bounded role set, integrates every handoff, and performs final verification. Use current-host catalog evidence for exact child models; never invent an ID or route to an external provider by default. Children receive self-contained packets with fork_turns=\"none\" and never spawn descendants. This policy does not create a Goal, change permissions, force delegation, or approve delivery.
"""
USAGE_HINT = f"""{MARKER}
For an exact direct child route, use the current role plan's model and reasoning_effort with fork_turns=\"none\". For a loaded custom-agent route, use agent_type with fork_turns=\"none\". If this tool surface does not accept the required metadata, report the route unavailable and use the documented Codex-only fallback; never silently claim the target model ran. After completion, confirm provider, model, and effort from persisted child state and rollout before reporting route_state=confirmed.
"""


class RoutingError(RuntimeError):
    pass


@contextmanager
def routing_operation_lock(codex_home: Path, *, exclusive: bool):
    """Lock the persistent CODEX_HOME inode for one complete transaction."""

    home = codex_home.expanduser().resolve(strict=True)
    if not home.is_dir():
        raise RoutingError(f"CODEX_HOME must resolve to a directory: {codex_home}")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(home, flags)
    except OSError as exc:
        raise RoutingError(f"could not open CODEX_HOME coordination lock: {home}") from exc
    locked = False
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise RoutingError(
                f"CODEX_HOME lock target must be a user-owned non-writable directory: {home}"
            )
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RoutingError(
                "another native-routing operation is in progress; retry after it completes"
            ) from exc
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def prepare_codex_home(raw: Path | None, *, allow_create: bool) -> Path:
    configured = raw or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    candidate = configured.expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).absolute()
    if candidate.is_symlink():
        raise RoutingError(f"CODEX_HOME must not be a symlink: {candidate}")
    if not candidate.exists():
        if not allow_create:
            raise RoutingError(
                f"CODEX_HOME does not exist and was not created without --apply: {candidate}"
            )
        parent = candidate.parent.resolve(strict=True)
        parent_info = parent.stat()
        if (
            not parent.is_dir()
            or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o022
        ):
            raise RoutingError(
                f"CODEX_HOME parent must be user-owned and not group/world writable: {parent}"
            )
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if candidate.is_symlink() or not candidate.is_dir():
        raise RoutingError(f"CODEX_HOME must be a regular directory: {candidate}")
    info = candidate.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise RoutingError(
            f"CODEX_HOME must be user-owned and not group/world writable: {candidate}"
        )
    return candidate.resolve(strict=True)


def nested_get(config: dict[str, Any], *segments: str) -> Any:
    current: Any = config
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return MISSING
        current = current[segment]
    return current


def user_layer(read_result: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    layers = read_result.get("layers")
    if not isinstance(layers, list):
        raise RoutingError("config/read did not return configuration layers")
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = layer.get("name")
        if isinstance(name, dict) and name.get("type") == "user" and name.get("profile") is None:
            config = layer.get("config")
            version = layer.get("version")
            return (
                config if isinstance(config, dict) else {},
                version if isinstance(version, str) else None,
            )
    return {}, None


def values(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature": nested_get(config, "features", "multi_agent_v2"),
        "metadata": nested_get(config, "features", "multi_agent_v2", "hide_spawn_agent_metadata"),
        "namespace": nested_get(config, "features", "multi_agent_v2", "tool_namespace"),
        "mode": nested_get(config, "features", "multi_agent_v2", "multi_agent_mode_hint_text"),
        "usage": nested_get(config, "features", "multi_agent_v2", "usage_hint_text"),
    }


def managed_values() -> dict[str, Any]:
    return {
        "metadata": False,
        "namespace": TOOL_NAMESPACE,
        "mode": MODE_HINT,
        "usage": USAGE_HINT,
    }


def snapshot(value: Any) -> dict[str, Any]:
    return {"present": value is not MISSING, "value": None if value is MISSING else value}


def snapshot_edit(key: str, saved: dict[str, Any]) -> dict[str, Any]:
    return {
        "keyPath": key,
        "value": saved.get("value") if saved.get("present") else None,
        "mergeStrategy": "replace",
    }


def state_path(app: CodexAppServer) -> Path:
    return app.codex_home / STATE_FILENAME


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RoutingError(f"routing state is not a non-symlink regular file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise RoutingError(
                f"routing state must be a private single regular file: {path}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            result = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingError(f"could not read routing state: {exc}") from exc
    finally:
        os.close(descriptor)
    if not isinstance(result, dict) or set(result) != {
        "schema",
        "managed_by",
        "phase",
        "recovery_target",
        "config_file",
        "managed",
        "previous",
        "scalar_origin",
    }:
        raise RoutingError("routing state fields are invalid")
    if result.get("schema") != STATE_SCHEMA:
        raise RoutingError("routing state schema is unsupported")
    if result.get("managed_by") != MANAGED_BY:
        raise RoutingError("routing state is not owned by this Skill")
    if result.get("managed") != managed_values():
        raise RoutingError("routing state managed values are invalid")
    previous = result.get("previous")
    if not isinstance(previous, dict) or set(previous) != {
        "metadata",
        "namespace",
        "mode",
        "usage",
    }:
        raise RoutingError("routing state is missing restore data")
    for key, saved in previous.items():
        if (
            not isinstance(saved, dict)
            or set(saved) != {"present", "value"}
            or type(saved.get("present")) is not bool
            or (saved["present"] is False and saved.get("value") is not None)
        ):
            raise RoutingError(f"routing state restore value is invalid: {key}")
    scalar_origin = result.get("scalar_origin")
    if scalar_origin is not None and type(scalar_origin) is not bool:
        raise RoutingError("routing state scalar origin is invalid")
    config_file = result.get("config_file")
    if (
        not isinstance(config_file, str)
        or not config_file
        or not Path(config_file).expanduser().is_absolute()
    ):
        raise RoutingError("routing state config path is invalid")
    if result.get("phase") not in {
        "pending-enable",
        "active",
        "pending-disable",
        "recovery-needed",
    }:
        raise RoutingError("routing state phase is invalid")
    if result.get("recovery_target") not in {"previous", "managed"}:
        raise RoutingError("routing recovery target is invalid")
    if (
        result["phase"] != "recovery-needed"
        and result["recovery_target"] != "previous"
    ):
        raise RoutingError("routing recovery target is inconsistent with journal phase")
    return result


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        read_state(path)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def remove_state(path: Path) -> None:
    if path.exists() or path.is_symlink():
        read_state(path)
        path.unlink()
        directory_flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def current_matches(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(current.get(key, MISSING) == expected[key] for key in expected)


def managed_state_matches(config: dict[str, Any], state: dict[str, Any]) -> bool:
    current = values(config)
    if not current_matches(current, state["managed"]):
        return False
    scalar_origin = state.get("scalar_origin")
    if not isinstance(scalar_origin, bool):
        return True
    managed = state["managed"]
    return current["feature"] == {
        "enabled": scalar_origin,
        "hide_spawn_agent_metadata": managed["metadata"],
        "tool_namespace": managed["namespace"],
        "multi_agent_mode_hint_text": managed["mode"],
        "usage_hint_text": managed["usage"],
    }


def require_state_config(state: dict[str, Any], config_path: Path) -> None:
    saved_path = Path(str(state["config_file"])).expanduser().resolve()
    if saved_path != config_path.expanduser().resolve():
        raise RoutingError("routing state belongs to a different Codex config")


def batch_write(
    app: CodexAppServer,
    edits: list[dict[str, Any]],
    version: str | None,
) -> dict[str, Any]:
    if not isinstance(version, str) or not version.strip():
        raise RoutingError(
            "config/read returned no user-layer version; refusing mutation without CAS"
        )
    return app.request(
        "config/batchWrite",
        {
            "edits": edits,
            "expectedVersion": version,
            "reloadUserConfig": True,
        },
    )


def supports_native_policy(binary: Path) -> tuple[bool, str]:
    """Write no user config; require exact effective readback of all four probe fields."""

    with tempfile.TemporaryDirectory(prefix="agency-native-routing-probe-") as raw_home:
        home = Path(raw_home).resolve()
        try:
            with CodexAppServer(
                binary,
                cwd=Path.cwd(),
                codex_home=home,
                timeout_seconds=15,
                process_environment=probe_environment(home),
                config_overrides=PROBE_CONFIG_OVERRIDES,
            ) as app:
                if app.codex_home != home:
                    return False, "probe App Server returned a different CODEX_HOME"
                result = app.request(
                    "config/read", {"includeLayers": True, "cwd": str(Path.cwd())}
                )
                effective = result.get("config")
                if not isinstance(effective, dict):
                    return False, "probe config/read returned no effective config"
                observed = values(effective)
                mismatches = [
                    key for key, expected in PROBE_EXPECTED.items()
                    if observed.get(key) != expected
                ]
                if mismatches:
                    return False, "probe semantic readback mismatch: " + ", ".join(mismatches)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            return False, str(exc)
    return True, "supported and read back"


def probe_environment(codex_home: Path) -> dict[str, str]:
    """Keep compatibility probes isolated from credentials in the parent process."""

    environment = {
        key: os.environ[key] for key in PROBE_ENV_ALLOWLIST if key in os.environ
    }
    environment.setdefault("HOME", str(Path.home()))
    environment.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    environment["CODEX_HOME"] = str(codex_home)
    environment["NO_COLOR"] = "1"
    return environment


def probe_binary_version(binary: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="agency-native-version-probe-") as raw_home:
        try:
            result = subprocess.run(
                [str(binary), "--version"],
                env=probe_environment(Path(raw_home)),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RoutingError(f"could not inspect Codex version for {binary}: {exc}") from exc
    detail = " ".join(result.stdout.strip().split())
    if result.returncode != 0:
        raise RoutingError(
            f"could not inspect Codex version for {binary}: {detail or result.returncode}"
        )
    return detail or "unknown"


def discover_compatibility_binaries(
    target: Path,
    explicit: list[str],
    *,
    path_cwd: Path | None = None,
) -> list[Path]:
    """Return every discoverable Codex client that may share the user config."""

    candidates = [target]
    candidates.extend(resolve_executable(value) for value in explicit)
    current_directory = (path_cwd or Path.cwd()).resolve()
    for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_directory:
            implicit = current_directory / "codex"
            if implicit.is_file() and os.access(implicit, os.X_OK):
                raise RoutingError(
                    "PATH contains an empty segment resolving to an executable ./codex; "
                    "remove the ambiguous segment, then list every intended client explicitly"
                )
            continue
        path_codex = Path(raw_directory).expanduser() / "codex"
        if path_codex.is_file() and os.access(path_codex, os.X_OK):
            candidates.append(resolve_executable(str(path_codex)))
    for candidate in DESKTOP_CODEX_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            candidates.append(candidate.resolve())

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def select_control_binary(
    requested: Path,
    report: list[dict[str, Any]],
    *,
    recovery_operation: bool,
) -> Path:
    """Use a compatible parser for disable/recover when the requested client is old."""

    if not recovery_operation:
        return requested
    requested_entry = next(
        (item for item in report if item.get("path") == str(requested)),
        None,
    )
    if requested_entry is not None and requested_entry.get("compatible") is True:
        return requested
    fallback = next(
        (item for item in report if item.get("compatible") is True),
        None,
    )
    if fallback is None:
        raise RoutingError(
            "disable/recover requires at least one compatible Codex client to read and restore config"
        )
    return Path(str(fallback["path"]))


def compatibility_report(binaries: list[Path]) -> list[dict[str, Any]]:
    """Capability-test all known shared-config clients without reading user config."""

    report = []
    for binary in binaries:
        compatible, detail = supports_native_policy(binary)
        report.append(
            {
                "path": str(binary),
                "version": probe_binary_version(binary),
                "compatible": compatible,
                "detail": detail,
            }
        )
    return report


def require_compatible_clients(
    report: list[dict[str, Any]], *, allow_incompatible: bool
) -> None:
    incompatible = [
        f"{item['path']} ({item['version']})"
        for item in report
        if item.get("compatible") is not True
    ]
    if incompatible and not allow_incompatible:
        raise RoutingError(
            "native routing would make a shared Codex config unreadable to: "
            + ", ".join(incompatible)
            + "; update those clients, use task-local routing, or proceed only after "
            "separate explicit approval with --allow-incompatible-client"
        )


def prepare_setup(
    config: dict[str, Any],
    existing_state: dict[str, Any] | None,
    config_path: Path,
    replace_existing: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    current = values(config)
    expected = managed_values()
    if existing_state is not None:
        require_state_config(existing_state, config_path)
        if existing_state.get("phase") != "active":
            raise RoutingError("routing journal requires --recover before setup")
        if not managed_state_matches(config, existing_state):
            raise RoutingError("managed routing fields changed outside this Skill; refusing overwrite")
        return existing_state, [], []
    for key in ("metadata", "namespace", "mode", "usage"):
        existing = current[key]
        if (
            existing is not MISSING
            and existing != expected[key]
            and not replace_existing
        ):
            raise RoutingError(
                f"user-authored {key} routing field exists; review and use --replace-existing-policy"
            )
    previous = {key: snapshot(current[key]) for key in ("metadata", "namespace", "mode", "usage")}
    scalar_origin = current["feature"] if isinstance(current["feature"], bool) else None
    if scalar_origin is not None:
        replacement = {
            "enabled": scalar_origin,
            "hide_spawn_agent_metadata": False,
            "tool_namespace": TOOL_NAMESPACE,
            "multi_agent_mode_hint_text": MODE_HINT,
            "usage_hint_text": USAGE_HINT,
        }
        edits = [{"keyPath": "features.multi_agent_v2", "value": replacement, "mergeStrategy": "replace"}]
        rollback = [{"keyPath": "features.multi_agent_v2", "value": scalar_origin, "mergeStrategy": "replace"}]
    else:
        edits = [
            {"keyPath": FIELD_PATHS[key], "value": expected[key], "mergeStrategy": "replace"}
            for key in ("metadata", "namespace", "mode", "usage")
        ]
        rollback = [snapshot_edit(FIELD_PATHS[key], previous[key]) for key in ("metadata", "namespace", "mode", "usage")]
    state = {
        "schema": STATE_SCHEMA,
        "managed_by": MANAGED_BY,
        "phase": "pending-enable",
        "recovery_target": "previous",
        "config_file": str(config_path),
        "managed": expected,
        "previous": previous,
        "scalar_origin": scalar_origin,
    }
    return state, edits, rollback


def disable_edits(state: dict[str, Any]) -> list[dict[str, Any]]:
    scalar_origin = state.get("scalar_origin")
    if isinstance(scalar_origin, bool):
        return [{"keyPath": "features.multi_agent_v2", "value": scalar_origin, "mergeStrategy": "replace"}]
    previous = state["previous"]
    return [snapshot_edit(FIELD_PATHS[key], previous[key]) for key in ("metadata", "namespace", "mode", "usage")]


def enable_edits(state: dict[str, Any]) -> list[dict[str, Any]]:
    scalar_origin = state.get("scalar_origin")
    managed = state["managed"]
    if isinstance(scalar_origin, bool):
        return [
            {
                "keyPath": "features.multi_agent_v2",
                "value": {
                    "enabled": scalar_origin,
                    "hide_spawn_agent_metadata": managed["metadata"],
                    "tool_namespace": managed["namespace"],
                    "multi_agent_mode_hint_text": managed["mode"],
                    "usage_hint_text": managed["usage"],
                },
                "mergeStrategy": "replace",
            }
        ]
    return [
        {
            "keyPath": FIELD_PATHS[key],
            "value": managed[key],
            "mergeStrategy": "replace",
        }
        for key in ("metadata", "namespace", "mode", "usage")
    ]


def previous_matches(config: dict[str, Any], state: dict[str, Any]) -> bool:
    current = values(config)
    scalar_origin = state.get("scalar_origin")
    if isinstance(scalar_origin, bool):
        return current["feature"] is scalar_origin
    previous = state["previous"]
    return all(
        current[key]
        == (previous[key].get("value") if previous[key].get("present") else MISSING)
        for key in ("metadata", "namespace", "mode", "usage")
    )


def state_with_phase(
    state: dict[str, Any], phase: str, recovery_target: str
) -> dict[str, Any]:
    updated = dict(state)
    updated["phase"] = phase
    updated["recovery_target"] = recovery_target
    return updated


def require_write_status(result: dict[str, Any], operation: str) -> None:
    if result.get("status") not in {"ok", "okOverridden"}:
        raise RoutingError(
            f"{operation} returned an unexpected config status: {result.get('status')!r}"
        )


def restore_previous_config(
    app: CodexAppServer, cwd: Path, state: dict[str, Any]
) -> bool:
    config, version, _ = read_config(app, cwd)
    if not previous_matches(config, state):
        if not managed_state_matches(config, state):
            raise RoutingError(
                "routing restore found concurrent user-layer changes; refusing overwrite"
            )
        result = batch_write(app, disable_edits(state), version)
        require_write_status(result, "routing restore")
    verify_config, _, effective_config = read_config(app, cwd)
    if not previous_matches(verify_config, state):
        raise RoutingError("routing restore user-layer readback mismatch")
    return not managed_state_matches(effective_config, state)


def restore_managed_config(
    app: CodexAppServer, cwd: Path, state: dict[str, Any]
) -> None:
    config, version, effective_config = read_config(app, cwd)
    if not managed_state_matches(config, state):
        if not previous_matches(config, state):
            raise RoutingError(
                "managed-state restore found concurrent user-layer changes; refusing overwrite"
            )
        result = batch_write(app, enable_edits(state), version)
        require_write_status(result, "routing managed-state restore")
        config, _, effective_config = read_config(app, cwd)
    if not managed_state_matches(config, state):
        raise RoutingError("managed routing user-layer readback mismatch")
    if not managed_state_matches(effective_config, state):
        raise RoutingError("managed routing effective readback mismatch")


def apply_setup_transaction(
    app: CodexAppServer,
    cwd: Path,
    journal_path: Path,
    new_state: dict[str, Any],
    edits: list[dict[str, Any]],
    version: str | None,
) -> None:
    if not isinstance(version, str) or not version.strip():
        raise RoutingError(
            "config/read returned no user-layer version; refusing mutation without CAS"
        )
    write_state(journal_path, new_state)
    write_accepted = False
    try:
        result = batch_write(app, edits, version)
        require_write_status(result, "native routing setup")
        write_accepted = True
        verify_config, _, effective_config = read_config(app, cwd)
        if not managed_state_matches(verify_config, new_state):
            raise RoutingError("user-layer readback does not match the accepted write")
        if not managed_state_matches(effective_config, new_state):
            raise RoutingError("effective workspace readback does not match the accepted write")
        write_state(
            journal_path, state_with_phase(new_state, "active", "previous")
        )
    except BaseException as exc:
        if not write_accepted:
            try:
                write_state(
                    journal_path,
                    state_with_phase(new_state, "recovery-needed", "previous"),
                )
            except BaseException as journal_exc:
                raise RoutingError(
                    "setup write was not confirmed and recovery journal update "
                    f"also failed: {exc}; {journal_exc}"
                ) from exc
            raise RoutingError(
                "setup write was not confirmed; no rollback was attempted and "
                f"the recovery journal was retained: {exc}"
            ) from exc
        try:
            restore_previous_config(app, cwd, new_state)
            remove_state(journal_path)
        except BaseException as rollback_exc:
            try:
                write_state(
                    journal_path,
                    state_with_phase(new_state, "recovery-needed", "previous"),
                )
            except BaseException as journal_exc:
                raise RoutingError(
                    "setup failed; rollback and recovery journal update also failed: "
                    f"{exc}; {rollback_exc}; {journal_exc}"
                ) from exc
            raise RoutingError(
                f"setup failed and rollback failed; recovery journal retained: {exc}; {rollback_exc}"
            ) from exc
        raise RoutingError(
            f"setup verification failed; prior values restored: {exc}"
        ) from exc


def read_config(app: CodexAppServer, cwd: Path) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    result = app.request("config/read", {"includeLayers": True, "cwd": str(cwd)})
    config, version = user_layer(result)
    effective = result.get("config")
    return config, version, effective if isinstance(effective, dict) else {}


def report_status(
    *,
    binary: Path,
    clients: list[dict[str, Any]],
    app: CodexAppServer,
    cwd: Path,
    require_effective: bool,
    as_json: bool,
) -> int:
    target = next(
        (item for item in clients if item.get("path") == str(binary)),
        None,
    )
    if target is None:
        raise RoutingError("active Codex client is missing from compatibility readback")
    compatible = target.get("compatible") is True
    detail = str(target.get("detail", "missing compatibility detail"))
    all_compatible = all(item.get("compatible") is True for item in clients)
    config, _, effective_config = read_config(app, cwd)
    current = values(config)
    effective = values(effective_config)
    state = read_state(state_path(app))
    active_journal = state is not None and state.get("phase") == "active"
    installed = active_journal and managed_state_matches(config, state)
    effective_match = active_journal and managed_state_matches(effective_config, state)
    recovery_required = state is not None and (
        state.get("phase") != "active" or not installed
    )
    payload = {
        "codex_binary": str(binary),
        "codex_version": target["version"],
        "config": str(app.config_path),
        "client_compatible": compatible,
        "client_detail": detail,
        "all_clients_compatible": all_compatible,
        "checked_clients": clients,
        "policy_installed": installed,
        "policy_effective": effective_match,
        "journal_phase": state.get("phase") if state is not None else None,
        "recovery_required": recovery_required,
        "tool_namespace": TOOL_NAMESPACE if effective.get("namespace") == TOOL_NAMESPACE else None,
        "spawn_metadata_visible": effective.get("metadata") is False,
        "route_acceptance_verified": False,
        "runtime_identity_verified": False,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for client in clients:
            label = "compatible" if client["compatible"] else client["detail"]
            print(f"Client: {client['version']} at {client['path']} — {label}")
        state_label = (
            "recovery required"
            if recovery_required
            else "installed and effective"
            if effective_match
            else "installed but not effective"
            if installed
            else "inactive"
        )
        print(f"Native role routing: {state_label}")
        print(f"Config: {app.config_path}")
        print("Route validation: not performed; config readback does not prove child acceptance or runtime identity")
    healthy = all_compatible and installed and effective_match
    return 1 if require_effective and not healthy else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--disable", action="store_true")
    actions.add_argument("--recover", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--require-effective", action="store_true")
    parser.add_argument("--replace-existing-policy", action="store_true")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--compat-bin",
        action="append",
        default=[],
        help="Additional Codex binary sharing this config; repeat as needed.",
    )
    parser.add_argument(
        "--allow-incompatible-client",
        action="store_true",
        help="Proceed after explicit approval even if another client rejects the policy.",
    )
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.require_effective and not args.status:
        raise RoutingError("--require-effective requires --status")
    if args.status and args.apply:
        raise RoutingError("--status cannot be combined with --apply")
    binary = resolve_executable(args.codex_bin)
    binaries = discover_compatibility_binaries(binary, args.compat_bin)
    clients = compatibility_report(binaries)
    control_binary = select_control_binary(
        binary,
        clients,
        recovery_operation=bool(args.disable or args.recover),
    )
    cwd = args.cwd.expanduser().resolve()
    if cwd.is_symlink() or not cwd.is_dir():
        raise RoutingError(f"cwd must be a regular directory: {cwd}")
    codex_home = prepare_codex_home(
        args.codex_home,
        allow_create=bool(args.apply and not args.status),
    )
    with routing_operation_lock(
        codex_home, exclusive=bool(args.apply and not args.status)
    ), CodexAppServer(
        control_binary,
        cwd=cwd,
        codex_home=codex_home,
        timeout_seconds=20,
    ) as app:
        if app.codex_home != codex_home:
            raise RoutingError("App Server initialized a different CODEX_HOME")
        if args.status:
            return report_status(
                binary=binary,
                clients=clients,
                app=app,
                cwd=cwd,
                require_effective=args.require_effective,
                as_json=args.json,
            )
        if not (args.disable or args.recover):
            require_compatible_clients(
                clients,
                allow_incompatible=args.allow_incompatible_client,
            )
        if not args.json:
            for client in clients:
                label = "compatible" if client["compatible"] else client["detail"]
                print(f"Client: {client['version']} at {client['path']} — {label}")
            if control_binary != binary:
                print(
                    f"Recovery control client: {control_binary} "
                    f"(requested client {binary} is incompatible)"
                )
        config, version, _ = read_config(app, cwd)
        saved = read_state(state_path(app))
        if saved is not None:
            require_state_config(saved, app.config_path)
        if args.recover:
            if saved is None:
                print("Native role routing has no recovery journal.")
                return 0
            if saved.get("phase") == "active":
                print("Native role routing journal is active and needs no recovery.")
                return 0
            target = str(saved["recovery_target"])
            if not args.apply:
                print(f"Config: {app.config_path}")
                print(f"Dry run: would recover routing journal to {target} state.")
                return 0
            try:
                if target == "previous":
                    effective_disabled = restore_previous_config(app, cwd, saved)
                    remove_state(state_path(app))
                    print(
                        "Native role routing recovery restored the prior user layer."
                        if effective_disabled
                        else "Prior user values were restored, but another layer still exposes the routing policy."
                    )
                    return 0 if effective_disabled else 1
                restore_managed_config(app, cwd, saved)
                write_state(
                    state_path(app), state_with_phase(saved, "active", "previous")
                )
                print("Native role routing recovery restored the managed active state.")
                return 0
            except BaseException as exc:
                try:
                    write_state(
                        state_path(app),
                        state_with_phase(saved, "recovery-needed", target),
                    )
                except BaseException as journal_exc:
                    raise RoutingError(
                        f"routing recovery failed and journal update failed: {exc}; {journal_exc}"
                    ) from exc
                raise RoutingError(f"routing recovery failed; journal retained: {exc}") from exc
        if args.disable:
            if saved is None:
                print("Native role routing is already inactive.")
                return 0
            if saved.get("phase") != "active":
                raise RoutingError("routing journal requires --recover before disable")
            if not managed_state_matches(config, saved):
                raise RoutingError("managed routing fields changed; refusing destructive restore")
            if not args.apply:
                print(f"Config: {app.config_path}")
                print("Dry run: would restore the four previously owned routing fields.")
                return 0
            pending = state_with_phase(saved, "pending-disable", "previous")
            write_state(state_path(app), pending)
            try:
                effective_disabled = restore_previous_config(app, cwd, pending)
            except BaseException as exc:
                try:
                    restore_managed_config(app, cwd, pending)
                    write_state(
                        state_path(app), state_with_phase(saved, "active", "previous")
                    )
                except BaseException as rollback_exc:
                    try:
                        write_state(
                            state_path(app),
                            state_with_phase(pending, "recovery-needed", "managed"),
                        )
                    except BaseException as journal_exc:
                        raise RoutingError(
                            "disable failed; managed rollback and recovery journal update "
                            f"also failed: {exc}; {rollback_exc}; {journal_exc}"
                        ) from exc
                    raise RoutingError(
                        f"disable failed and managed rollback failed; recovery journal retained: {exc}; {rollback_exc}"
                    ) from exc
                raise RoutingError(
                    f"disable failed; managed active state was restored: {exc}"
                ) from exc
            remove_state(state_path(app))
            if effective_disabled:
                print("Native role routing disabled and prior user values read back. Start a new Codex task.")
                return 0
            print("Prior user values were restored, but another config layer still exposes the routing policy.")
            return 1
        new_state, edits, _ = prepare_setup(
            config,
            saved,
            app.config_path,
            args.replace_existing_policy,
        )
        print(f"Config: {app.config_path}")
        print("Tool namespace: agents")
        print("Model policy: current-host exact IDs only; external models disabled by default")
        print("Fork mode: none for every exact routed child")
        if not edits:
            print("Native role routing is already installed in the user layer.")
            return 0
        if not args.apply:
            print("Dry run only. Re-run with --apply after reviewing this preview.")
            return 0
        apply_setup_transaction(
            app,
            cwd,
            state_path(app),
            new_state,
            edits,
            version,
        )
        print("Native role routing installed and read back. Start a new Codex task before testing exact routes.")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RoutingError, ValueError, json.JSONDecodeError) as exc:
        print(f"Native role routing unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2)
