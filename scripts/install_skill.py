#!/usr/bin/env python3
"""Install the canonical/legacy pair under a cooperating-installer advisory lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported platforms
    fcntl = None  # type: ignore[assignment]


CANONICAL_SKILL_NAME = "agency-chief-of-staff"
LEGACY_SKILL_NAME = "zhijuan-codex-agency-chief-of-staf"
SKILL_NAME = CANONICAL_SKILL_NAME
INSTALL_NAMES = (CANONICAL_SKILL_NAME, LEGACY_SKILL_NAME)
RUNTIME_FILES = (
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
RUNTIME_EXECUTABLE_FILES = frozenset({"scripts/audit_historical_threads.py"})
SEALED_TREE_POLICY = "sealed-tree-v1"
SEALED_ROOT_MODE = 0o700
SEALED_DIRECTORY_MODE = 0o755
SEALED_FILE_MODE = 0o644
SEALED_EXECUTABLE_MODE = 0o755

LEGACY_DESCRIPTION = (
    f"Compatibility bundle for explicit ${LEGACY_SKILL_NAME} invocation only. "
    f"If a pre-read announcement is required, output exactly "
    f"`我将使用 ${LEGACY_SKILL_NAME}，遵照你的范围。`; then use a read-only "
    "tool to read only this bundle's SKILL.md in full before any other action or "
    "progress, and immediately output COS_BOOT_RECEIPT. "
    f"Do not select implicitly; prefer ${CANONICAL_SKILL_NAME} for new requests."
)
CANONICAL_PRELOAD_ANNOUNCEMENT = (
    f"我将使用 ${CANONICAL_SKILL_NAME}，遵照你的范围。"
)
LEGACY_PRELOAD_ANNOUNCEMENT = f"我将使用 ${LEGACY_SKILL_NAME}，遵照你的范围。"
CANONICAL_ACTIVATION_SENTENCE = "本 Skill 在主会话被显式或隐式激活时"
LEGACY_ACTIVATION_SENTENCE = "本兼容 Skill 在主会话被用户通过旧 slug 显式激活时"
LEGACY_OPENAI_YAML = f'''interface:
  display_name: "Zhijuan Codex 幕僚长（旧入口兼容）"
  short_description: "旧显式调用兼容入口；新任务请使用 agency-chief-of-staff"
  default_prompt: "使用 ${LEGACY_SKILL_NAME} 把这个复杂任务从目标澄清推进到可验证交付。"

policy:
  allow_implicit_invocation: false
'''


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def runtime_source_path(root: Path, rel: str) -> Path:
    path = root / rel
    if path.is_symlink():
        raise ValueError(f"runtime source must not be a symlink: {rel}")
    if not path.is_file():
        raise ValueError(f"runtime bundle missing file: {rel}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"runtime source escapes package root: {rel}")
    return path


def render_runtime_bytes(source: Path, rel: str, skill_name: str) -> bytes:
    if skill_name not in INSTALL_NAMES:
        raise ValueError(f"unsupported installed Skill name: {skill_name}")
    source_path = runtime_source_path(source, rel)
    content = source_path.read_bytes()
    if skill_name == CANONICAL_SKILL_NAME:
        return content
    if rel == "agents/openai.yaml":
        return LEGACY_OPENAI_YAML.encode()
    if rel != "SKILL.md":
        return content

    text = content.decode()
    canonical_name = f"name: {CANONICAL_SKILL_NAME}"
    if canonical_name not in text:
        raise ValueError("canonical SKILL.md name is missing before alias rendering")
    text = text.replace(canonical_name, f"name: {LEGACY_SKILL_NAME}", 1)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("description:"):
            lines[index] = f"description: {json.dumps(LEGACY_DESCRIPTION, ensure_ascii=False)}\n"
            break
    else:
        raise ValueError("canonical SKILL.md description is missing before alias rendering")
    text = "".join(lines).replace("入口：canonical", "入口：legacy")
    if text.count(CANONICAL_PRELOAD_ANNOUNCEMENT) != 1:
        raise ValueError(
            "canonical SKILL.md preload announcement is missing or ambiguous before alias rendering"
        )
    text = text.replace(
        CANONICAL_PRELOAD_ANNOUNCEMENT, LEGACY_PRELOAD_ANNOUNCEMENT, 1
    )
    if text.count(CANONICAL_ACTIVATION_SENTENCE) != 1:
        raise ValueError(
            "canonical SKILL.md activation sentence is missing or ambiguous before alias rendering"
        )
    text = text.replace(
        CANONICAL_ACTIVATION_SENTENCE, LEGACY_ACTIVATION_SENTENCE, 1
    )
    frontmatter_end = text.find("\n---\n", 4)
    if frontmatter_end < 0:
        raise ValueError("canonical SKILL.md frontmatter is not closed")
    insert_at = frontmatter_end + len("\n---\n")
    compatibility_note = (
        "\n> 兼容入口：本 bundle 只用于用户显式调用旧 slug；工作流与 canonical "
        "同源生成。prompt 同时包含 canonical 时停止兼容入口，由 canonical 单独接管。"
        "合法 worker packet 仍先 bypass，不得输出启动回执。\n"
    )
    return (text[:insert_at] + compatibility_note + text[insert_at:]).encode()


def rendered_runtime_manifest(source: Path, skill_name: str) -> dict[str, str]:
    return {
        rel: digest_bytes(render_runtime_bytes(source, rel, skill_name))
        for rel in RUNTIME_FILES
    }


def runtime_manifest(root: Path) -> dict[str, str]:
    return {rel: digest(runtime_source_path(root, rel)) for rel in RUNTIME_FILES}


def package_source_revision_sha256(
    expected_manifests: dict[str, dict[str, str]],
) -> str:
    """Hash the complete canonical/legacy expected-manifest pair."""
    if set(expected_manifests) != set(INSTALL_NAMES):
        raise ValueError("package source revision requires the complete install pair")
    canonical_json = json.dumps(
        expected_manifests,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return digest_bytes(canonical_json)


TreeRecord = dict[str, int | str]
TreeSnapshot = dict[str, TreeRecord]


def runtime_directory_paths(files: Mapping[str, str]) -> set[str]:
    directories: set[str] = set()
    for relative_text in files:
        relative = Path(relative_text)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("installed manifest contains an unsafe runtime path")
        for parent in relative.parents:
            if parent == Path("."):
                break
            directories.add(parent.as_posix())
    return directories


def runtime_file_mode(relative_text: str) -> int:
    return (
        SEALED_EXECUTABLE_MODE
        if relative_text in RUNTIME_EXECUTABLE_FILES
        else SEALED_FILE_MODE
    )


def _node_kind(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character-device"
    if stat.S_ISBLK(mode):
        return "block-device"
    return "special"


def _metadata_record(metadata: os.stat_result) -> TreeRecord:
    return {
        "kind": _node_kind(metadata.st_mode),
        "mode": stat.S_IMODE(metadata.st_mode),
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
        "nlink": metadata.st_nlink,
        "size": metadata.st_size,
        "dev": metadata.st_dev,
        "ino": metadata.st_ino,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
    }


def _read_regular_digest_nofollow(path: Path, expected: os.stat_result) -> str:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("safe no-follow installed-tree reads are unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("installed bundle changed during sealed-tree scan") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("installed bundle file changed type during sealed-tree scan")
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
            expected.st_dev,
            expected.st_ino,
            expected.st_mode,
            expected.st_uid,
            expected.st_gid,
            expected.st_nlink,
            expected.st_size,
            expected.st_mtime_ns,
            expected.st_ctime_ns,
        ):
            raise RuntimeError("installed bundle file rebound during sealed-tree scan")
        hasher = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            hasher.update(chunk)
        after = os.fstat(descriptor)
        if _metadata_record(after) != _metadata_record(before):
            raise RuntimeError("installed bundle file changed during sealed-tree scan")
        return hasher.hexdigest()
    finally:
        os.close(descriptor)


def _installed_tree_snapshot_once(root: Path) -> TreeSnapshot:
    try:
        root_metadata = os.lstat(root)
    except FileNotFoundError:
        return {}
    snapshot: TreeSnapshot = {".": _metadata_record(root_metadata)}
    if not stat.S_ISDIR(root_metadata.st_mode):
        if stat.S_ISLNK(root_metadata.st_mode):
            snapshot["."]["target_sha256"] = digest_bytes(
                os.readlink(root).encode("utf-8", errors="surrogateescape")
            )
        elif stat.S_ISREG(root_metadata.st_mode):
            snapshot["."]["sha256"] = _read_regular_digest_nofollow(
                root, root_metadata
            )
        return snapshot

    def scan(directory: Path, relative_directory: Path) -> None:
        before = os.lstat(directory)
        if not stat.S_ISDIR(before.st_mode):
            raise RuntimeError("installed bundle directory changed during sealed-tree scan")
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise RuntimeError("installed bundle could not be enumerated safely") from exc
        for entry in entries:
            relative = relative_directory / entry.name
            relative_text = relative.as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError("installed bundle changed during sealed-tree scan") from exc
            record = _metadata_record(metadata)
            snapshot[relative_text] = record
            path = directory / entry.name
            if stat.S_ISDIR(metadata.st_mode):
                scan(path, relative)
            elif stat.S_ISREG(metadata.st_mode):
                record["sha256"] = _read_regular_digest_nofollow(path, metadata)
            elif stat.S_ISLNK(metadata.st_mode):
                try:
                    target = os.readlink(path)
                except OSError as exc:
                    raise RuntimeError("installed bundle symlink changed during scan") from exc
                record["target_sha256"] = digest_bytes(
                    target.encode("utf-8", errors="surrogateescape")
                )
        after = os.lstat(directory)
        if _metadata_record(after) != _metadata_record(before):
            raise RuntimeError("installed bundle directory changed during sealed-tree scan")

    scan(root, Path())
    return snapshot


def installed_tree_snapshot(root: Path) -> TreeSnapshot:
    """Return a stable lstat/nofollow snapshot of every installed tree node."""
    first = _installed_tree_snapshot_once(root)
    second = _installed_tree_snapshot_once(root)
    if first != second:
        raise RuntimeError("installed bundle changed between sealed-tree scans")
    return first


def sealed_manifest_from_snapshot(
    snapshot: TreeSnapshot, expected_manifest: Mapping[str, str]
) -> dict[str, str]:
    """Validate sealed-tree-v1 and return the content-only public manifest."""
    if not snapshot:
        return {}
    expected_files = set(expected_manifest)
    expected_directories = runtime_directory_paths(expected_manifest)
    expected_paths = {".", *expected_directories, *expected_files}
    if set(snapshot) != expected_paths:
        raise ValueError("installed bundle path set is not sealed to the runtime allowlist")
    if not hasattr(os, "geteuid"):
        raise RuntimeError("installed-tree owner verification is unavailable")
    owner = os.geteuid()
    manifest: dict[str, str] = {}
    for relative_text, record in snapshot.items():
        expected_kind = (
            "directory"
            if relative_text == "." or relative_text in expected_directories
            else "file"
        )
        if record.get("kind") != expected_kind:
            raise ValueError(f"installed bundle contains a non-{expected_kind} node")
        if record.get("uid") != owner:
            raise ValueError("installed bundle contains a node owned by another user")
        expected_mode = (
            SEALED_ROOT_MODE
            if relative_text == "."
            else SEALED_DIRECTORY_MODE
            if expected_kind == "directory"
            else runtime_file_mode(relative_text)
        )
        if record.get("mode") != expected_mode:
            raise ValueError("installed bundle contains a node with non-canonical permissions")
        if expected_kind == "file":
            if record.get("nlink") != 1:
                raise ValueError("installed bundle contains a hard-linked runtime file")
            sha256 = record.get("sha256")
            if not isinstance(sha256, str):
                raise ValueError("installed bundle runtime file was not hashed")
            manifest[relative_text] = sha256
    return manifest


def installed_manifest(
    root: Path, expected_manifest: Mapping[str, str]
) -> dict[str, str]:
    """Return content hashes only after exact sealed-tree-v1 validation."""
    return sealed_manifest_from_snapshot(
        installed_tree_snapshot(root), expected_manifest
    )


def guidance_files(root: Path) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name in {"AGENTS.md", "AGENTS.override.md"}
    )


def paths_overlap(left: Path, right: Path) -> bool:
    """Return whether two resolved paths are equal or one contains the other."""
    left_resolved = left.resolve(strict=False)
    right_resolved = right.resolve(strict=False)
    return (
        left_resolved == right_resolved
        or left_resolved in right_resolved.parents
        or right_resolved in left_resolved.parents
    )


def validate_install_paths(
    source: Path, target_root: Path, targets: dict[str, Path]
) -> None:
    """Reject any source/target overlap before the installer can mutate disk."""
    if paths_overlap(source, target_root):
        raise ValueError(
            "refusing overlapping package source and target root: "
            f"{source} <-> {target_root}"
        )
    for skill_name, target in targets.items():
        if paths_overlap(source, target):
            raise ValueError(
                "refusing overlapping package source and install target: "
                f"{skill_name}: {source} <-> {target}"
            )


def verify_preflight_snapshot(
    targets: dict[str, Path], observed: dict[str, TreeSnapshot]
) -> None:
    """Fail if any target changed after the locked transaction inspection."""
    for name, target in targets.items():
        if target.is_symlink():
            raise RuntimeError(f"install target changed to a symlink after preflight: {target}")
        try:
            current = installed_tree_snapshot(target)
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"install target became unsafe after preflight: {name}") from exc
        if current != observed[name]:
            raise RuntimeError(
                f"install target changed after preflight: {name}; retry the install"
            )


def copy_runtime(source: Path, target: Path, skill_name: str = SKILL_NAME) -> None:
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(SEALED_ROOT_MODE)
    for rel in RUNTIME_FILES:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(render_runtime_bytes(source, rel, skill_name))
        destination.chmod(runtime_file_mode(rel))
    for relative_text in sorted(
        runtime_directory_paths(rendered_runtime_manifest(source, skill_name))
    ):
        (target / relative_text).chmod(SEALED_DIRECTORY_MODE)


def remove_transaction_path(path: Path) -> None:
    """Remove a transaction path and surface every cleanup failure."""
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def remove_committed_backup(path: Path) -> None:
    """Remove a committed backup without hiding cleanup failure."""
    remove_transaction_path(path)


def existing_transaction_artifacts(target_root: Path) -> list[dict[str, str]]:
    """Block every path using a reserved transaction-artifact prefix."""
    found: list[dict[str, str]] = []
    if not target_root.is_dir() or target_root.is_symlink():
        return found
    for path in target_root.iterdir():
        for skill_name in INSTALL_NAMES:
            artifact_kind: str | None = None
            suffix = ""
            for candidate_kind in ("backup", "staging", "failed"):
                prefix = f".{skill_name}.{candidate_kind}-"
                if path.name.startswith(prefix):
                    artifact_kind = candidate_kind
                    suffix = path.name.removeprefix(prefix)
                    break
            if artifact_kind is None:
                continue
            if not (path.exists() or path.is_symlink()):
                continue
            found.append(
                {
                    "kind": f"preexisting_{artifact_kind}_residual",
                    "artifact_kind": artifact_kind,
                    "skill_name": skill_name,
                    "path": str(path),
                    "error": (
                        f"{artifact_kind} transaction-reserved path still exists"
                        + ("" if suffix else " with an empty suffix")
                    ),
                }
            )
    return sorted(found, key=lambda item: item["path"])


def cleanup_guidance_for(residuals: list[dict[str, str]]) -> list[str]:
    return [
        "Inspect and remove this installer transaction residual only after "
        f"confirming the active bundle is intact: {item['path']}"
        for item in residuals
    ]


def artifact_records_report(artifacts: list[dict[str, str]]) -> dict[str, object]:
    return {
        "cleanup_complete": not artifacts,
        "cleanup_warnings": artifacts,
        "residual_paths": [item["path"] for item in artifacts],
        "cleanup_guidance": cleanup_guidance_for(artifacts),
    }


def transaction_artifact_report(target_root: Path) -> dict[str, object]:
    return artifact_records_report(existing_transaction_artifacts(target_root))


@contextmanager
def install_lock(target_root: Path) -> Iterator[None]:
    if fcntl is None:
        raise RuntimeError("OS advisory locking is unavailable on this platform")
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("safe no-follow lock opening is unavailable on this platform")
    target_root.mkdir(parents=True, exist_ok=True)
    lock_path = target_root / f".{CANONICAL_SKILL_NAME}.install.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(f"install lock could not be opened safely: {lock_path}") from exc
    try:
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise RuntimeError(f"install lock is not a regular file: {lock_path}")
        if lock_stat.st_nlink != 1:
            raise RuntimeError(f"install lock must not be hard-linked: {lock_path}")
        if hasattr(os, "geteuid") and lock_stat.st_uid != os.geteuid():
            raise RuntimeError(f"install lock is owned by another user: {lock_path}")
        if stat.S_IMODE(lock_stat.st_mode) & 0o077:
            raise RuntimeError(f"install lock permissions are too broad: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise RuntimeError(f"another install may be active: {lock_path}") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        # Closing the descriptor releases flock even after process failure.
        os.close(descriptor)


def replace_many_from_staging(
    source: Path,
    targets: dict[str, Path],
    *,
    expected_manifests: dict[str, dict[str, str]] | None = None,
    transaction_targets: dict[str, Path] | None = None,
    observed_manifests: dict[str, TreeSnapshot] | None = None,
) -> dict[str, object]:
    full_targets = transaction_targets or targets
    frozen_expected = expected_manifests or {
        name: rendered_runtime_manifest(source, name) for name in full_targets
    }
    if not set(targets).issubset(full_targets):
        raise ValueError("updated targets must be part of the full transaction pair")
    if set(full_targets) != set(frozen_expected):
        raise ValueError("frozen manifests must cover the full transaction pair")
    if observed_manifests is not None and set(full_targets) != set(observed_manifests):
        raise ValueError("observed manifests must cover the full transaction pair")

    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    promoted: set[str] = set()
    committed = False
    ordered = list(targets.items())
    try:
        for skill_name, target in ordered:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
            )
            staged[skill_name] = staging
            copy_runtime(source, staging, skill_name)
            if (
                installed_manifest(staging, frozen_expected[skill_name])
                != frozen_expected[skill_name]
            ):
                raise RuntimeError(f"staged manifest mismatch for {skill_name}")

        # Staging can take long enough for an otherwise-current peer to drift.
        # Recheck the complete pair immediately before the first destructive rename.
        if observed_manifests is not None:
            verify_preflight_snapshot(full_targets, observed_manifests)

        for skill_name, target in ordered:
            if target.exists():
                backup_candidate = (
                    target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
                )
                target.rename(backup_candidate)
                backups[skill_name] = backup_candidate

        for skill_name, target in ordered:
            staged[skill_name].rename(target)
            promoted.add(skill_name)
            if (
                installed_manifest(target, frozen_expected[skill_name])
                != frozen_expected[skill_name]
            ):
                raise RuntimeError(f"installed manifest mismatch for {skill_name}")

        # The transaction is not committed until both updated and unchanged peers
        # match the same frozen source manifests. The file lock serializes this
        # installer; a non-cooperating same-user writer is outside that guarantee.
        for skill_name, target in full_targets.items():
            if (
                installed_manifest(target, frozen_expected[skill_name])
                != frozen_expected[skill_name]
            ):
                raise RuntimeError(f"final pair manifest mismatch for {skill_name}")
        committed = True
    except Exception as original:
        rollback_errors: list[str] = []
        for skill_name, target in reversed(ordered):
            if skill_name in promoted and target.exists():
                failed_target = (
                    target.parent / f".{target.name}.failed-{uuid.uuid4().hex}"
                )
                try:
                    target.rename(failed_target)
                    remove_transaction_path(failed_target)
                except OSError as exc:
                    rollback_errors.append(
                        f"isolate or clean failed target for {skill_name}: {exc}"
                    )
            backup = backups.get(skill_name)
            if backup is not None and backup.exists() and not target.exists():
                try:
                    backup.rename(target)
                except OSError as exc:
                    rollback_errors.append(f"restore {skill_name}: {exc}")
        if rollback_errors:
            raise RuntimeError(
                f"install failed: {original}; rollback also failed: "
                + "; ".join(rollback_errors)
            ) from original
        raise
    finally:
        staging_cleanup_errors: list[str] = []
        for staging in staged.values():
            if staging.exists() or staging.is_symlink():
                try:
                    remove_transaction_path(staging)
                except OSError as exc:
                    staging_cleanup_errors.append(f"{staging}: {exc}")
        if staging_cleanup_errors:
            raise RuntimeError(
                "installer staging cleanup failed: " + "; ".join(staging_cleanup_errors)
            )

    cleanup_warnings: list[dict[str, str]] = []
    residual_paths: list[str] = []

    # Both installs are already committed and verified. Cleanup failures must not
    # roll back valid installs, but they must remain visible to callers.
    if committed:
        for skill_name, backup in backups.items():
            if not (backup.exists() or backup.is_symlink()):
                continue
            warning_recorded = False
            try:
                remove_committed_backup(backup)
            except OSError as exc:
                cleanup_warnings.append(
                    {
                        "kind": "backup_cleanup_failed",
                        "skill_name": skill_name,
                        "path": str(backup),
                        "error": str(exc),
                    }
                )
                warning_recorded = True
            if backup.exists() or backup.is_symlink():
                residual_paths.append(str(backup))
                if not warning_recorded:
                    cleanup_warnings.append(
                        {
                            "kind": "backup_cleanup_incomplete",
                            "skill_name": skill_name,
                            "path": str(backup),
                            "error": "backup still exists after cleanup returned",
                        }
                    )

    return {
        "cleanup_complete": not cleanup_warnings and not residual_paths,
        "cleanup_warnings": cleanup_warnings,
        "residual_paths": residual_paths,
    }


def replace_from_staging(
    source: Path, target: Path, skill_name: str = SKILL_NAME
) -> dict[str, object]:
    return replace_many_from_staging(source, {skill_name: target})


def inspect_install_state(
    targets: dict[str, Path], expected: dict[str, dict[str, str]]
) -> tuple[dict[str, str], dict[str, TreeSnapshot], dict[str, list[str]]]:
    states: dict[str, str] = {}
    observed_manifests: dict[str, TreeSnapshot] = {}
    guidance_detected: dict[str, list[str]] = {}
    for name, target in targets.items():
        if target.is_symlink():
            raise ValueError(f"refusing symlink install target: {target}")
        current_snapshot = installed_tree_snapshot(target)
        observed_manifests[name] = current_snapshot
        guidance_detected[name] = guidance_files(target)
        if not target.exists():
            states[name] = "missing"
        else:
            try:
                current = sealed_manifest_from_snapshot(
                    current_snapshot, expected[name]
                )
            except (ValueError, RuntimeError):
                states[name] = "different"
            else:
                states[name] = (
                    "current" if current == expected[name] else "different"
                )
    return states, observed_manifests, guidance_detected


def emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['status']}: {payload['target_root']}")
        warnings = payload.get("cleanup_warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if isinstance(warning, dict):
                    print(
                        "cleanup warning: "
                        f"{warning.get('skill_name', 'unknown')} "
                        f"{warning.get('path', 'unknown')} "
                        f"{warning.get('error', 'unknown error')}"
                    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install canonical and legacy-compatible Skill bundles. This command "
            "never writes AGENTS.md routing guidance."
        )
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="Directory containing user skills. Defaults to ~/.agents/skills.",
    )
    parser.add_argument("--force", action="store_true", help="Replace differing installs.")
    parser.add_argument("--dry-run", action="store_true", help="Check without copying.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    target_root = args.target_root.expanduser().resolve()
    targets = {name: target_root / name for name in INSTALL_NAMES}
    expected: dict[str, dict[str, str]] | None = None
    states: dict[str, str]
    observed_manifests: dict[str, TreeSnapshot]
    guidance_detected: dict[str, list[str]]
    updates: dict[str, Path]
    preexisting_artifacts: list[dict[str, str]] = []
    transaction_result: dict[str, object] = {
        "cleanup_complete": True,
        "cleanup_warnings": [],
        "residual_paths": [],
    }

    try:
        # This must stay ahead of lock creation, staging, and every target write.
        validate_install_paths(source, target_root, targets)
        if args.dry_run:
            # A dry run must remain non-mutating, so it cannot acquire the file lock.
            expected = {
                name: rendered_runtime_manifest(source, name) for name in INSTALL_NAMES
            }
            states, observed_manifests, guidance_detected = inspect_install_state(
                targets, expected
            )
            preexisting_artifacts = existing_transaction_artifacts(target_root)
            updates = {
                name: target
                for name, target in targets.items()
                if states[name] != "current"
            }
        else:
            with install_lock(target_root):
                # Freeze one full-pair source expectation and derive both states and
                # updates from the filesystem only after the transaction lock exists.
                expected = {
                    name: rendered_runtime_manifest(source, name)
                    for name in INSTALL_NAMES
                }
                states, observed_manifests, guidance_detected = inspect_install_state(
                    targets, expected
                )
                preexisting_artifacts = existing_transaction_artifacts(target_root)
                updates = {
                    name: target
                    for name, target in targets.items()
                    if states[name] != "current"
                }
                if any(state == "different" for state in states.values()) and not args.force:
                    payload = {
                        "source": str(source),
                        "target_root": str(target_root),
                        "status": "conflict",
                        "message": (
                            "an install differs; re-run with --force to replace the pair"
                        ),
                        "package_source_revision_sha256": (
                            package_source_revision_sha256(expected)
                        ),
                        "tree_integrity_policy": SEALED_TREE_POLICY,
                        "tree_integrity_verified": False,
                        "states": states,
                        "guidance_files_detected": guidance_detected,
                        "agents_md_written": False,
                        "agents_md_dependency": False,
                        **artifact_records_report(preexisting_artifacts),
                    }
                    emit(payload, args.json)
                    raise SystemExit(1)
                if updates:
                    transaction_result = replace_many_from_staging(
                        source,
                        updates,
                        expected_manifests=expected,
                        transaction_targets=targets,
                        observed_manifests=observed_manifests,
                    )
                else:
                    verify_preflight_snapshot(targets, observed_manifests)
                    for name, target in targets.items():
                        if (
                            installed_manifest(target, expected[name])
                            != expected[name]
                        ):
                            raise RuntimeError(
                                f"final pair manifest mismatch for {name}"
                            )
    except (OSError, ValueError, RuntimeError) as exc:
        try:
            artifact_report = transaction_artifact_report(target_root)
        except OSError as scan_exc:
            artifact_report = {
                "cleanup_complete": False,
                "cleanup_warnings": [
                    {
                        "kind": "transaction_artifact_scan_failed",
                        "path": str(target_root),
                        "error": str(scan_exc),
                    }
                ],
                "residual_paths": [],
                "cleanup_guidance": [
                    f"Inspect installer transaction artifacts manually: {target_root}"
                ],
            }
        payload = {
            "source": str(source),
            "target_root": str(target_root),
            "status": "conflict",
            "message": f"install could not be completed safely: {exc}",
            "agents_md_written": False,
            "agents_md_dependency": False,
            "tree_integrity_policy": SEALED_TREE_POLICY,
            "tree_integrity_verified": False,
            **(
                {
                    "package_source_revision_sha256": (
                        package_source_revision_sha256(expected)
                    )
                }
                if expected is not None
                else {}
            ),
            **artifact_report,
        }
        emit(payload, args.json)
        raise SystemExit(1)

    if any(state == "different" for state in states.values()) and not args.force:
        payload = {
            "source": str(source),
            "target_root": str(target_root),
            "status": "conflict",
            "message": "an install differs; re-run with --force to replace the pair",
            "package_source_revision_sha256": package_source_revision_sha256(
                expected
            ),
            "tree_integrity_policy": SEALED_TREE_POLICY,
            "tree_integrity_verified": False,
            "states": states,
            "guidance_files_detected": guidance_detected,
            "agents_md_written": False,
            "agents_md_dependency": False,
            **artifact_records_report(preexisting_artifacts),
        }
        emit(payload, args.json)
        raise SystemExit(1)

    if expected is None:
        raise RuntimeError("expected package manifests were not generated")

    if not updates:
        status = "already-installed"
    elif args.dry_run:
        status = (
            "would-replace"
            if any(state == "different" for state in states.values())
            else "would-install"
        )
    else:
        status = (
            "replaced"
            if any(state == "different" for state in states.values())
            else "installed"
        )

    transaction_warnings = transaction_result["cleanup_warnings"]
    assert isinstance(transaction_warnings, list)
    cleanup_warnings = [*preexisting_artifacts, *transaction_warnings]
    transaction_residuals = transaction_result["residual_paths"]
    assert isinstance(transaction_residuals, list)
    residual_paths = sorted(
        {
            *(item["path"] for item in preexisting_artifacts),
            *(str(path) for path in transaction_residuals),
        }
    )
    cleanup_pending_names = {
        str(item["skill_name"])
        for item in cleanup_warnings
        if isinstance(item, dict) and "skill_name" in item
    }
    guidance_affected = {
        name: paths
        for name, paths in guidance_detected.items()
        if paths and not args.dry_run and name in updates
    }
    removed_guidance = {
        name: paths
        for name, paths in guidance_affected.items()
        if name not in cleanup_pending_names
    }
    pending_guidance = {
        name: paths
        for name, paths in guidance_affected.items()
        if name in cleanup_pending_names
    }
    residual_skill_by_path = {
        str(item["path"]): str(item["skill_name"])
        for item in cleanup_warnings
        if isinstance(item, dict) and "path" in item and "skill_name" in item
    }
    for path_text in residual_paths:
        skill_name = residual_skill_by_path.get(path_text)
        if skill_name is None:
            continue
        detected = guidance_files(Path(path_text))
        if detected:
            pending_guidance[skill_name] = sorted(
                set(pending_guidance.get(skill_name, [])) | set(detected)
            )
    cleanup_complete = transaction_result["cleanup_complete"]
    if residual_paths:
        cleanup_complete = False
    residual_records = [
        item
        for item in cleanup_warnings
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"] in residual_paths
    ]
    payload = {
        "source": str(source),
        "target_root": str(target_root),
        "status": status,
        "canonical_name": CANONICAL_SKILL_NAME,
        "legacy_name": LEGACY_SKILL_NAME,
        "package_source_revision_sha256": package_source_revision_sha256(expected),
        "tree_integrity_policy": SEALED_TREE_POLICY,
        "tree_integrity_verified": (
            not args.dry_run or not updates
        ),
        "runtime_files_per_bundle": len(RUNTIME_FILES),
        "transaction_lock_scope": (
            None if args.dry_run else "cooperating-installers-only"
        ),
        "transaction_lock_kind": None if args.dry_run else "os-advisory-flock",
        "states_before": states,
        "targets": {name: str(target) for name, target in targets.items()},
        "manifests": expected,
        "agents_md_written": False,
        "agents_md_dependency": False,
        "legacy_guidance_files_removed": removed_guidance,
        "legacy_guidance_files_cleanup_pending": pending_guidance,
        "guidance_removal_complete": (
            None
            if args.dry_run and not residual_paths
            else not pending_guidance and not residual_paths
        ),
        "agents_md_touched": bool(guidance_affected),
        "cleanup_complete": cleanup_complete,
        "cleanup_warnings": cleanup_warnings,
        "residual_paths": residual_paths,
        "cleanup_guidance": cleanup_guidance_for(residual_records),
    }
    emit(payload, args.json)


if __name__ == "__main__":
    main()
