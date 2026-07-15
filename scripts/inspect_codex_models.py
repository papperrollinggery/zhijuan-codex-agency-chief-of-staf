#!/usr/bin/env python3
"""Read Codex App Server model/list and emit a resolver-compatible catalog.

The App Server does not assign Agency capability classes. Callers therefore bind
each exact model ID to efficient, balanced, or judgment explicitly. The script
validates those bindings against the executing host and never carries a static
model-ID table.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from typing import Any

sys.dont_write_bytecode = True


MODEL_CLASSES = frozenset({"efficient", "balanced", "judgment"})
REASONING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
THREAD_ID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,199}\Z")
PROVIDER_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def resolve_executable(raw: str) -> Path:
    candidate = raw if os.sep in raw else shutil.which(raw)
    if not candidate:
        fail(f"Codex executable was not found: {raw}")
    path = Path(candidate).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        fail(f"Codex executable is not an executable regular file: {path}")
    return path


def binary_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        fail(f"Could not inspect Codex version: {exc}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        fail(f"Could not inspect Codex version: {detail}")
    return result.stdout.strip() or result.stderr.strip() or "unknown"


def parse_bindings(values: list[str]) -> dict[str, str]:
    """Return exact model ID -> Agency model class."""

    bindings: dict[str, str] = {}
    bound_classes: set[str] = set()
    for raw in values:
        if "=" not in raw:
            fail("--class-binding must use CLASS=EXACT_MODEL_ID")
        model_class, model_id = raw.split("=", 1)
        if model_class not in MODEL_CLASSES:
            fail(f"unsupported model class: {model_class!r}")
        if not MODEL_RE.fullmatch(model_id):
            fail(f"invalid exact model ID: {model_id!r}")
        if model_id in bindings:
            fail(f"model ID is bound more than once: {model_id}")
        if model_class in bound_classes:
            fail(f"model class is bound more than once: {model_class}")
        bindings[model_id] = model_class
        bound_classes.add(model_class)
    if not bindings:
        fail("at least one --class-binding is required")
    return bindings


def root_provider_from_database(
    database: sqlite3.Connection, thread_id: str
) -> str:
    if not THREAD_ID_RE.fullmatch(thread_id):
        fail(f"invalid root thread ID: {thread_id}")
    row = database.execute(
        "SELECT model_provider FROM threads WHERE id = ?", (thread_id,)
    ).fetchone()
    if row is None or not isinstance(row[0], str) or not PROVIDER_RE.fullmatch(row[0]):
        fail(f"root provider is unavailable in persisted state: {thread_id}")
    return row[0]


def read_root_provider(state_db: Path, thread_id: str) -> str:
    """Read a root provider through one WAL-aware, identity-guarded view."""

    with state_database_connection(state_db) as (database, _identity):
        return root_provider_from_database(database, thread_id)


def canonical_state_database(state_db: Path, codex_home: Path) -> Path:
    """Bind state readback to the App Server's canonical state_5.sqlite entry."""

    home = codex_home.expanduser().resolve(strict=True)
    expanded = state_db.expanduser()
    supplied = expanded.parent.resolve(strict=True) / expanded.name
    canonical = home / "state_5.sqlite"
    if supplied != canonical:
        fail(
            "state database must use the App Server codexHome/state_5.sqlite entry"
        )
    if canonical.is_symlink():
        allowed_target = home / "sqlite" / "state_5.sqlite"
        resolved = canonical.resolve(strict=True)
        if allowed_target.is_symlink() or resolved != allowed_target.resolve(strict=True):
            fail("canonical state database symlink target is invalid")
    else:
        resolved = canonical.resolve(strict=True)
        if resolved != canonical:
            fail("canonical state database entry is invalid")
    if (
        not resolved.is_file()
        or not resolved.is_relative_to(home)
        or resolved.stat().st_nlink != 1
    ):
        fail("canonical state database must resolve to a single regular file inside codexHome")
    return resolved


@contextmanager
def state_database_connection(
    database_path: Path,
    *,
    expected_identity: tuple[int, int] | None = None,
):
    """Open one WAL-aware read transaction guarded by a stable database identity.

    SQLite cannot discover ``-wal`` beside a ``/dev/fd`` URI, so an immutable
    descriptor URI can silently return stale state. Keep a no-follow descriptor
    open as the identity guard, read through the real canonical path, and verify
    the database plus any live WAL/SHM sidecars before and after the transaction.
    This detects replacement races without sacrificing current WAL contents.
    """

    path = database_path.expanduser().resolve(strict=True)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    database: sqlite3.Connection | None = None

    def path_identity(candidate: Path, *, required: bool) -> tuple[int, int] | None:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if required:
                fail(f"state database path disappeared: {candidate}")
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail(f"state database path must remain a non-symlink regular file: {candidate}")
        return info.st_dev, info.st_ino

    def sidecar_identities() -> dict[str, tuple[int, int] | None]:
        return {
            suffix: path_identity(Path(str(path) + suffix), required=False)
            for suffix in ("-wal", "-shm")
        }

    def require_same_sidecars(
        before: dict[str, tuple[int, int] | None],
        after: dict[str, tuple[int, int] | None],
    ) -> None:
        for suffix, identity in before.items():
            if after.get(suffix) != identity:
                fail(f"state database {suffix[1:]} identity changed during readback")

    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"state database must be a single regular file: {path}")
        identity = (info.st_dev, info.st_ino)
        if expected_identity is not None and identity != expected_identity:
            fail("state database changed between canonical validation and open")
        if path_identity(path, required=True) != identity:
            fail("state database path changed after identity guard opened")
        sidecars_before = sidecar_identities()
        database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        database.execute("PRAGMA query_only = ON")
        database.execute("BEGIN")
        database.execute("PRAGMA schema_version").fetchone()
        database_path_rows = database.execute("PRAGMA database_list").fetchall()
        main_paths = [row[2] for row in database_path_rows if row[1] == "main"]
        if len(main_paths) != 1 or Path(str(main_paths[0])).resolve() != path:
            fail("SQLite main database does not match the guarded state path")
        if path_identity(path, required=True) != identity:
            fail("state database changed while the read transaction opened")
        sidecars_bound = sidecar_identities()
        for suffix, before_identity in sidecars_before.items():
            if before_identity is not None and sidecars_bound[suffix] != before_identity:
                fail(f"state database {suffix[1:]} changed while the read transaction opened")
        readback_identity = {
            "device": info.st_dev,
            "inode": info.st_ino,
            "identity_guarded": True,
            "wal_aware": True,
            "readonly_transaction": True,
        }
        yield database, readback_identity
        if path_identity(path, required=True) != identity:
            fail("state database identity changed during readback")
        require_same_sidecars(sidecars_bound, sidecar_identities())
    finally:
        if database is not None:
            try:
                database.rollback()
            except sqlite3.Error:
                pass
            database.close()
        os.close(descriptor)


@contextmanager
def canonical_state_connection(state_db: Path, codex_home: Path):
    resolved = canonical_state_database(state_db, codex_home)
    expected = resolved.stat()
    expected_identity = (expected.st_dev, expected.st_ino)
    with state_database_connection(
        resolved, expected_identity=expected_identity
    ) as (database, identity):
        revalidated = canonical_state_database(state_db, codex_home)
        current = revalidated.stat()
        if (
            revalidated != resolved
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            fail("canonical state database changed during identity binding")
        yield database, identity
        revalidated = canonical_state_database(state_db, codex_home)
        current = revalidated.stat()
        if (
            revalidated != resolved
            or (current.st_dev, current.st_ino) != expected_identity
        ):
            fail("canonical state database changed during readback")


class CodexAppServer:
    """Small read-only JSON-RPC client for the App Server stdio transport."""

    def __init__(
        self,
        executable: Path,
        *,
        cwd: Path,
        codex_home: Path | None,
        timeout_seconds: int,
        process_environment: dict[str, str] | None = None,
        config_overrides: tuple[str, ...] = (),
    ) -> None:
        environment = (
            dict(process_environment)
            if process_environment is not None
            else os.environ.copy()
        )
        if codex_home is not None:
            if codex_home.is_symlink() or not codex_home.is_dir():
                fail(f"CODEX_HOME must be an existing regular directory: {codex_home}")
            environment["CODEX_HOME"] = str(codex_home.resolve())
        command = [str(executable)]
        for override in config_overrides:
            if not isinstance(override, str) or not override:
                fail("App Server config overrides must be non-empty strings")
            command.extend(("-c", override))
        command.extend(("app-server", "--stdio"))
        self.timeout_seconds = timeout_seconds
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=cwd,
            env=environment,
        )
        if self.process.stdin is None or self.process.stdout is None:
            self.close()
            fail("Codex App Server did not expose stdio")
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self.pending: dict[int, dict[str, Any]] = {}
        self.next_id = 0
        threading.Thread(target=self._read_loop, daemon=True).start()
        try:
            initialized = self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "agency_model_catalog_inspector",
                        "title": "Agency Model Catalog Inspector",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            raw_home = initialized.get("codexHome")
            if not isinstance(raw_home, str) or not raw_home:
                fail("Codex App Server initialize response has no codexHome")
            self.codex_home = Path(raw_home).expanduser().resolve()
            self.config_path = self.codex_home / "config.toml"
            self.notify("initialized")
        except BaseException:
            self.close()
            raise

    def _read_loop(self) -> None:
        try:
            for line in self.stdout:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    self.messages.put(value)
            self.messages.put(EOFError("Codex App Server closed stdout"))
        except BaseException as exc:  # pragma: no cover - process boundary
            self.messages.put(exc)

    def _send(self, value: dict[str, Any]) -> None:
        self.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
        self.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            if request_id in self.pending:
                message = self.pending.pop(request_id)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail(f"App Server request timed out: {method}")
                try:
                    item = self.messages.get(timeout=remaining)
                except queue.Empty:
                    fail(f"App Server request timed out: {method}")
                if isinstance(item, BaseException):
                    fail(f"App Server stopped during {method}: {item}")
                message = item
                message_id = message.get("id")
                if not isinstance(message_id, int):
                    continue
                if message_id != request_id:
                    self.pending[message_id] = message
                    continue
            if "error" in message:
                error = message.get("error")
                detail = error.get("message") if isinstance(error, dict) else error
                fail(f"App Server {method} failed: {detail}")
            result = message.get("result")
            if not isinstance(result, dict):
                fail(f"App Server {method} returned an invalid result")
            return result

    def notify(self, method: str) -> None:
        self._send({"method": method})

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def __enter__(self) -> "CodexAppServer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def collect_model_items(app: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params: dict[str, Any] = {"includeHidden": True, "limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = app.request("model/list", params)
        page = result.get("data")
        if not isinstance(page, list):
            fail("App Server model/list result has no data array")
        for index, item in enumerate(page):
            if not isinstance(item, dict):
                fail(f"model/list entry is not an object: {index}")
            items.append(item)
        next_cursor = result.get("nextCursor")
        if next_cursor is None or next_cursor == "":
            return items
        if not isinstance(next_cursor, str):
            fail("model/list nextCursor must be a string or null")
        if next_cursor in seen_cursors:
            fail("model/list repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def supported_efforts(item: dict[str, Any], model_id: str) -> list[str]:
    raw = item.get("supportedReasoningEfforts")
    if not isinstance(raw, list):
        fail(f"model has no supportedReasoningEfforts array: {model_id}")
    efforts: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("reasoningEffort"), str):
            fail(f"model has a malformed reasoning effort: {model_id}")
        effort = entry["reasoningEffort"]
        if effort not in REASONING_LEVELS:
            fail(f"model has a resolver-incompatible reasoning effort: {model_id}")
        if effort and effort not in efforts:
            efforts.append(effort)
    default = item.get("defaultReasoningEffort")
    if default is not None and not isinstance(default, str):
        fail(f"model has an invalid defaultReasoningEffort: {model_id}")
    if isinstance(default, str) and default not in REASONING_LEVELS:
        fail(f"model has a resolver-incompatible default effort: {model_id}")
    if isinstance(default, str) and default and default not in efforts:
        efforts.append(default)
    if not efforts:
        fail(f"model has no usable reasoning effort: {model_id}")
    return efforts


def provider_evidence_for_bindings(
    items: list[dict[str, Any]],
    bindings: dict[str, str],
    *,
    root_provider: str,
    fallback: str,
) -> str:
    indexed = {
        item.get("model"): item
        for item in items
        if isinstance(item.get("model"), str)
    }
    bound = [indexed.get(model_id) for model_id in bindings]
    if bound and all(item is not None for item in bound):
        advertised = [
            item.get("modelProvider", item.get("provider"))  # type: ignore[union-attr]
            for item in bound
        ]
        if all(value is not None for value in advertised):
            if any(value != root_provider for value in advertised):
                fail("bound model provider does not match the root provider")
            return "catalog-advertised"
    return fallback


def build_resolver_catalog(
    items: list[dict[str, Any]],
    bindings: dict[str, str],
    *,
    root_provider: str,
    source_id: str,
    provenance_source: str,
    requested_thread_id: str | None,
    canonical_state_store_bound: bool,
    model_provider_evidence: str,
) -> dict[str, object]:
    if not PROVIDER_RE.fullmatch(root_provider):
        fail(f"invalid root provider ID: {root_provider!r}")
    if not source_id:
        fail("catalog source_id is required")
    if provenance_source not in {
        "active-host-catalog",
        "user-confirmed-exact-id",
        "provider-asserted-catalog",
    }:
        fail("catalog provenance source is invalid")
    if requested_thread_id is not None and not THREAD_ID_RE.fullmatch(
        requested_thread_id
    ):
        fail("catalog requested thread id is invalid")
    if type(canonical_state_store_bound) is not bool:
        fail("catalog canonical state binding must be boolean")
    if model_provider_evidence not in {
        "catalog-advertised",
        "root-state-inferred",
        "user-confirmed",
    }:
        fail("catalog model provider evidence is invalid")
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        model_id = item.get("model")
        if not isinstance(model_id, str) or not MODEL_RE.fullmatch(model_id):
            fail("model/list contains an invalid model ID")
        if model_id in indexed:
            fail(f"model/list contains a duplicate model ID: {model_id}")
        indexed[model_id] = item

    models: list[dict[str, object]] = []
    for model_id, model_class in bindings.items():
        if model_class not in MODEL_CLASSES:
            fail(f"unsupported model class: {model_class!r}")
        item = indexed.get(model_id)
        if item is None:
            fail(f"bound model is absent from current App Server catalog: {model_id}")
        if item.get("hidden") is True:
            fail(f"bound model is hidden from normal host selection: {model_id}")
        if model_id.lower().startswith("claude-"):
            fail("external Claude models are disabled in the core Codex catalog")
        advertised_provider = item.get("modelProvider", item.get("provider"))
        if advertised_provider is not None and advertised_provider != root_provider:
            fail(
                f"bound model provider does not match the root provider: {model_id}: "
                f"{advertised_provider!r}"
            )
        availability = item.get("available", item.get("isAvailable", True))
        if type(availability) is not bool:
            fail(f"model availability is not boolean: {model_id}")
        models.append(
            {
                "id": model_id,
                "provider": root_provider,
                "model_class": model_class,
                "supported_reasoning": supported_efforts(item, model_id),
                "available": availability,
                "provider_evidence": (
                    "catalog-advertised"
                    if advertised_provider is not None
                    else model_provider_evidence
                ),
            }
        )
    return {
        "schema_version": 2,
        "provenance": {
            "source": provenance_source,
            "source_id": source_id,
            "observed_for_requested_thread": requested_thread_id is not None,
            "requested_thread_id": requested_thread_id,
            "root_provider": root_provider,
            "canonical_state_store_bound": canonical_state_store_bound,
            "model_provider_evidence": model_provider_evidence,
        },
        "models": models,
    }


def catalog_source_id(
    *,
    executable: Path,
    version: str,
    items: list[dict[str, Any]],
    root_provider: str,
    state_binding: dict[str, object] | None,
) -> str:
    digest_input = json.dumps(
        {
            "binary": str(executable),
            "version": version,
            "models": items,
            "root_provider": root_provider,
            "state_binding": state_binding,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "codex-app-server:model/list:" + hashlib.sha256(digest_input).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--root-provider")
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--thread-id")
    parser.add_argument(
        "--confirm-root-provider",
        "--confirm-current-task-provider",
        dest="confirm_root_provider",
        action="store_true",
        help=(
            "Manually confirm --root-provider without claiming a state or "
            "current-task readback. The older option spelling is retained as an alias."
        ),
    )
    parser.add_argument(
        "--class-binding",
        action="append",
        default=[],
        help="Repeatable CLASS=EXACT_MODEL_ID binding.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 120:
        fail("--timeout-seconds must be between 1 and 120")
    cwd = args.cwd.expanduser().resolve()
    if cwd.is_symlink() or not cwd.is_dir():
        fail(f"cwd must be a regular directory: {cwd}")
    executable = resolve_executable(args.codex_bin)
    version = binary_version(executable)
    bindings = parse_bindings(args.class_binding)
    if bool(args.state_db) != bool(args.thread_id):
        fail("--state-db and --thread-id must be supplied together")
    with CodexAppServer(
        executable,
        cwd=cwd,
        codex_home=args.codex_home.expanduser() if args.codex_home else None,
        timeout_seconds=args.timeout_seconds,
    ) as app:
        items = collect_model_items(app)
        if args.state_db:
            if args.root_provider or args.confirm_root_provider:
                fail("state readback cannot be combined with manual provider confirmation")
            with canonical_state_connection(
                args.state_db, app.codex_home
            ) as (database, state_identity):
                root_provider = root_provider_from_database(
                    database, args.thread_id
                )
            requested_thread_id = args.thread_id
            canonical_state_store_bound = True
            provenance_source = "active-host-catalog"
            model_provider_evidence = "root-state-inferred"
            state_binding: dict[str, object] | None = {
                "thread_id": args.thread_id,
                **state_identity,
            }
        else:
            if not args.root_provider:
                fail("use --state-db/--thread-id or supply --root-provider")
            root_provider = args.root_provider
            requested_thread_id = None
            canonical_state_store_bound = False
            provenance_source = (
                "user-confirmed-exact-id"
                if args.confirm_root_provider
                else "provider-asserted-catalog"
            )
            model_provider_evidence = "user-confirmed"
            state_binding = None
    if provenance_source == "active-host-catalog":
        model_provider_evidence = provider_evidence_for_bindings(
            items,
            bindings,
            root_provider=root_provider,
            fallback="root-state-inferred",
        )
    source_id = catalog_source_id(
        executable=executable,
        version=version,
        items=items,
        root_provider=root_provider,
        state_binding=state_binding,
    )
    catalog = build_resolver_catalog(
        items,
        bindings,
        root_provider=root_provider,
        source_id=source_id,
        provenance_source=provenance_source,
        requested_thread_id=requested_thread_id,
        canonical_state_store_bound=canonical_state_store_bound,
        model_provider_evidence=model_provider_evidence,
    )
    print(json.dumps(catalog, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"Codex model catalog unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
