#!/usr/bin/env python3
"""Render validated surfaces into deterministic fallbacks and optional fragments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.dont_write_bytecode = True

from validate_visualization_data import (
    image_extension,
    normalize_payload,
    read_verified_image_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "task-stage": ROOT / "assets" / "visualizations" / "task-surface.html",
    "decision": ROOT / "assets" / "visualizations" / "decision-surface.html",
}
IMAGE_EXTENSIONS = ("png", "jpg", "gif", "webp")
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TOKEN_PATTERN = re.compile(r"__([A-Z][A-Z0-9_]*)__")
MAX_FRAGMENT_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


def fail(message: str) -> None:
    raise ValueError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def same_inode(identity: tuple[int, ...], value: os.stat_result) -> bool:
    return identity[:3] == (value.st_dev, value.st_ino, value.st_mode)


def directory_identity(value: os.stat_result) -> tuple[int, int]:
    return (value.st_dev, value.st_ino)


def nofollow_flag() -> int:
    value = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(value, int):
        fail("this platform cannot enforce O_NOFOLLOW")
    return value


def read_regular_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        fail(f"{label} must be opened without following symlinks: {path}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(f"{label} must be an unlinked regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            path_after = os.stat(path, follow_symlinks=False)
        except OSError:
            fail(f"{label} path changed during read: {path}")
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or stat_identity(before) != stat_identity(after)
            or stat_identity(after) != stat_identity(path_after)
        ):
            fail(f"{label} changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def markdown_text(value: str) -> str:
    collapsed = " ".join(value.split())
    collapsed = (
        collapsed.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    for character in "\\`*_{}[]()#+-.!|>":
        collapsed = collapsed.replace(character, f"\\{character}")
    return collapsed


def replace_tokens(template: str, replacements: dict[str, str]) -> str:
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in replacements:
            fail(f"visualization template contains unknown token: {token}")
        seen.add(token)
        return replacements[token]

    rendered = TOKEN_PATTERN.sub(replace, template)
    missing = sorted(set(replacements) - seen)
    if missing:
        fail(f"visualization template did not consume tokens: {', '.join(missing)}")
    return rendered


def task_stage_markup(stages: list[dict[str, str]]) -> str:
    state_labels = {
        "completed": "已完成",
        "current": "当前",
        "pending": "待开始",
    }
    items: list[str] = []
    for stage in stages:
        label = escape(stage["label"], quote=True)
        state = stage["state"]
        state_label = state_labels[state]
        current = ' aria-current="step"' if state == "current" else ""
        items.append(
            "\n".join(
                (
                    f'    <li class="agency-stage-item" data-state="{state}"{current}>',
                    '      <span class="agency-stage-marker" aria-hidden="true"></span>',
                    '      <span class="agency-stage-copy">',
                    f"        <strong>{label}</strong>",
                    f'        <span class="text-small">{state_label}</span>',
                    "      </span>",
                    "    </li>",
                )
            )
        )
    return "\n".join(items)


def task_fallback(data: dict[str, Any]) -> str:
    state_labels = {
        "completed": "已完成",
        "current": "当前",
        "pending": "待开始",
    }
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
        markdown_text(data["goal"]),
        "",
    ]
    for index, stage in enumerate(data["stages"], start=1):
        lines.append(
            f"{index}. {markdown_text(stage['label'])} — {state_labels[stage['state']]}"
        )
    lines.extend(("", f"下一步：{markdown_text(data['next_step'])}"))
    if "blocker" in data:
        lines.append(f"阻塞：{markdown_text(data['blocker'])}")
    lines.append("")
    return "\n".join(lines)


def task_blocker_markup(data: dict[str, Any]) -> str:
    blocker = data.get("blocker")
    if not isinstance(blocker, str):
        return ""
    return "\n".join(
        (
            '<div class="viz-row" role="status" aria-label="当前阻塞">',
            '  <span class="viz-badge">阻塞</span>',
            f'  <span class="text-destructive agency-stage-detail">{escape(blocker)}</span>',
            "</div>",
        )
    )


def ordered_decision_choices(data: dict[str, Any]) -> list[dict[str, str]]:
    choices = list(data["choices"])
    recommended = choices[data["recommended_index"]]
    return [recommended, *(choice for choice in choices if choice is not recommended)]


def decision_choice_markup(data: dict[str, Any]) -> tuple[str, str]:
    ordered = ordered_decision_choices(data)
    items: list[str] = []
    for index, choice in enumerate(ordered):
        recommended = index == 0
        label = choice["label"]
        tradeoff = choice["tradeoff"]
        downstream_effect = choice["downstream_effect"]
        detail = f"{label}：{tradeoff}；影响：{downstream_effect}"
        badge = '<span class="viz-badge">推荐</span>' if recommended else ""
        items.append(
            "\n".join(
                (
                    '<button class="btn viz-tile" type="button" data-choice '
                    f'data-choice-id="{escape(choice["id"], quote=True)}" '
                    f'data-label="{escape(label, quote=True)}" '
                    f'data-tradeoff="{escape(tradeoff, quote=True)}" '
                    f'data-downstream-effect="{escape(downstream_effect, quote=True)}" '
                    f'data-detail="{escape(detail, quote=True)}" '
                    f'aria-pressed="{str(recommended).lower()}">',
                    '  <span class="agency-choice-copy">',
                    '    <span class="agency-choice-heading">',
                    f"      <strong>{escape(label)}</strong>{badge}",
                    "    </span>",
                    f"    <span>{escape(tradeoff)}</span>",
                    f'    <span class="text-small">影响：{escape(downstream_effect)}</span>',
                    "  </span>",
                    "</button>",
                )
            )
        )
    initial = (
        f"{ordered[0]['label']}：{ordered[0]['tradeoff']}；"
        f"影响：{ordered[0]['downstream_effect']}"
    )
    return "\n".join(items), initial


def decision_fallback(data: dict[str, Any]) -> str:
    ordered = ordered_decision_choices(data)
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
        markdown_text(data["summary"]),
        "",
        "| 方案 | 权衡 | 后续影响 |",
        "| --- | --- | --- |",
    ]
    for index, choice in enumerate(ordered):
        suffix = "（推荐）" if index == 0 else ""
        lines.append(
            f"| {markdown_text(choice['label'])}{suffix} | "
            f"{markdown_text(choice['tradeoff'])} | "
            f"{markdown_text(choice['downstream_effect'])} |"
        )
    lines.extend(("", "请回复你选择的方案。", ""))
    return "\n".join(lines)


def impact_fallback(data: dict[str, Any]) -> str:
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
        "```mermaid",
        "flowchart LR",
        f'  changed["{escape(data["changed_item"], quote=True)}"]',
    ]
    for index, item in enumerate(data["downstream_items"], start=1):
        disposition = "保留" if item["disposition"] == "preserved" else "需复核"
        label = escape(f"{item['item']} — {item['impact']}", quote=True)
        lines.append(f'  item{index}["{label}"]')
        lines.append(f"  changed -->|{disposition}| item{index}")
    lines.extend(("```", "", f"下次复核：{markdown_text(data['next_review'])}", ""))
    return "\n".join(lines)


def evidence_fallback(data: dict[str, Any]) -> str:
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
        "| 项目 | 状态 | 含义 | 下一步 |",
        "| --- | --- | --- | --- |",
    ]
    for item in data["items"]:
        next_action = markdown_text(item.get("next_action", "—"))
        lines.append(
            f"| {markdown_text(item['item'])} | {markdown_text(item['status'])} | "
            f"{markdown_text(item['meaning'])} | {next_action} |"
        )
    lines.append("")
    return "\n".join(lines)


def numeric_fallback(data: dict[str, Any]) -> str:
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
        markdown_text(data["summary"]),
        "",
        "| 名称 | 数值 | 单位 | 维度 | 缺失说明 |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for observation in data["observations"]:
        value = observation["value"]
        rendered_value = "缺失" if value is None else json.dumps(value, allow_nan=False)
        missing_reason = markdown_text(observation.get("missing_reason", "—"))
        lines.append(
            f"| {markdown_text(observation['name'])} | {rendered_value} | "
            f"{markdown_text(observation['unit'])} | "
            f"{markdown_text(observation['dimension'])} | {missing_reason} |"
        )
    lines.extend(
        (
            "",
            f"缺失值：{markdown_text(data['missing_values'])}",
            f"来源定义：{markdown_text(data['source_definition'])}",
            "",
        )
    )
    return "\n".join(lines)


def image_fallback(
    data: dict[str, Any], *, verified_image_path: Path | None
) -> str:
    lines = [
        f"## {markdown_text(data['title'])}",
        "",
    ]
    if verified_image_path is None:
        lines.extend(("预览：未验证，已省略", ""))
    else:
        image_path = quote(str(verified_image_path), safe="/")
        lines.extend(
            (
                f"![{markdown_text(data['alt_text'])}](<{image_path}>)",
                "",
            )
        )
    lines.extend((f"审阅对象：{markdown_text(data['review_target'])}", ""))
    for index, finding in enumerate(data["region_findings"], start=1):
        lines.append(
            f"{index}. {markdown_text(finding['region'])}："
            f"{markdown_text(finding['finding'])}"
        )
    lines.extend(
        ("", f"修改效果：{markdown_text(data['revision_effect'])}", "")
    )
    return "\n".join(lines)


def render_fallback(
    normalized: dict[str, Any], *, verified_image_path: Path | None = None
) -> str:
    surface = normalized["surface"]
    data = normalized["data"]
    if surface == "task-stage":
        return task_fallback(data)
    if surface == "decision":
        return decision_fallback(data)
    if surface == "impact":
        return impact_fallback(data)
    if surface == "evidence-list":
        return evidence_fallback(data)
    if surface == "numeric-trend":
        return numeric_fallback(data)
    if surface == "image-review":
        return image_fallback(data, verified_image_path=verified_image_path)
    fail(f"surface {surface!r} has no deterministic fallback")


def render_content(
    normalized: dict[str, Any], *, name: str
) -> tuple[str, str, str, str]:
    surface = normalized["surface"]
    template_path = TEMPLATES.get(surface)
    if template_path is None:
        fail(f"surface {surface!r} has no inline renderer; use its registry fallback")
    template_bytes = read_regular_bytes(template_path, "visualization template")
    template = template_bytes.decode("utf-8")
    normalized_hash = sha256_bytes(canonical_bytes(normalized))
    root_id = f"agency-{surface}-{name}-{normalized_hash[:12]}"
    data = normalized["data"]

    if surface == "task-stage":
        stages = data["stages"]
        replacements = {
            "ROOT_ID": root_id,
            "ACCESSIBLE_TITLE": escape(data["title"], quote=True),
            "STAGES": task_stage_markup(stages),
            "NEXT_STEP": escape(data["next_step"]),
            "BLOCKER": task_blocker_markup(data),
        }
        fallback = render_fallback(normalized)
    else:
        choices, initial_detail = decision_choice_markup(data)
        replacements = {
            "ROOT_ID": root_id,
            "ACCESSIBLE_TITLE": escape(data["title"], quote=True),
            "CHOICES": choices,
            "INITIAL_DETAIL": escape(initial_detail),
        }
        fallback = render_fallback(normalized)

    fragment = replace_tokens(template, replacements)
    return fragment, fallback, root_id, sha256_bytes(template_bytes)


def verify_directory_binding(
    path: Path,
    directory_descriptor: int,
    expected_identity: tuple[int, int],
) -> None:
    descriptor_observed = os.fstat(directory_descriptor)
    try:
        path_observed = os.stat(path, follow_symlinks=False)
    except OSError:
        fail(f"output directory path changed during render: {path}")
    if (
        not stat.S_ISDIR(descriptor_observed.st_mode)
        or not stat.S_ISDIR(path_observed.st_mode)
        or directory_identity(descriptor_observed) != expected_identity
        or directory_identity(path_observed) != expected_identity
    ):
        fail(f"output directory path changed during render: {path}")


def open_directory_descriptor(path: Path) -> tuple[int, tuple[int, int]]:
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if not isinstance(directory_flag, int):
        fail("this platform cannot pin an output directory")
    flags = os.O_RDONLY | directory_flag | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        fail(f"output directory must be opened without following symlinks: {path}")
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode):
            fail(f"output directory must be a directory: {path}")
        identity = directory_identity(observed)
        verify_directory_binding(path, descriptor, identity)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, identity


def entry_stat(directory_descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def validate_output_entry(value: os.stat_result, name: str) -> None:
    if not (stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode)):
        fail(f"output entry must be a regular file or symlink: {name}")


def unused_entry_name(directory_descriptor: int, final_name: str, purpose: str) -> str:
    for _attempt in range(32):
        candidate = f".{final_name}.{purpose}-{secrets.token_hex(16)}"
        if entry_stat(directory_descriptor, candidate) is None:
            return candidate
    fail(f"could not allocate a private {purpose} name for {final_name}")


def write_secure_temp(
    directory_descriptor: int, final_name: str, content: bytes
) -> tuple[str, tuple[int, ...]]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | nofollow_flag()
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    temp_name = ""
    try:
        for _attempt in range(32):
            temp_name = f".{final_name}.tmp-{secrets.token_hex(16)}"
            try:
                descriptor = os.open(
                    temp_name,
                    flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                break
            except FileExistsError:
                continue
        if descriptor is None:
            fail(f"could not create a private temporary file for {final_name}")
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(f"temporary output must be an unlinked regular file: {temp_name}")
        stream = os.fdopen(descriptor, "wb", closefd=False)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(descriptor)
        finally:
            stream.close()
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or (before.st_dev, before.st_ino, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_mode)
            or after.st_size != len(content)
        ):
            fail(f"temporary output changed while writing: {temp_name}")
        return temp_name, stat_identity(after)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def unlink_matching_entry(
    directory_descriptor: int, name: str, identity: tuple[int, ...]
) -> bool:
    observed = entry_stat(directory_descriptor, name)
    if observed is None:
        return True
    if not same_inode(identity, observed):
        return False
    os.unlink(name, dir_fd=directory_descriptor)
    return True


def read_regular_at(
    directory_descriptor: int,
    name: str,
    label: str,
) -> tuple[bytes, tuple[int, ...]]:
    flags = os.O_RDONLY | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError:
        fail(f"{label} must be opened without following symlinks: {name}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(f"{label} must be an unlinked regular file: {name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        entry_after = entry_stat(directory_descriptor, name)
        if (
            entry_after is None
            or not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or stat_identity(before) != stat_identity(after)
            or stat_identity(after) != stat_identity(entry_after)
        ):
            fail(f"{label} changed during readback: {name}")
        return b"".join(chunks), stat_identity(after)
    finally:
        os.close(descriptor)


def verify_output_set(
    directory_descriptor: int,
    outputs: list[tuple[str, bytes]],
    expected_identities: dict[str, tuple[int, ...]],
) -> None:
    for name, expected_content in outputs:
        observed_content, observed_identity = read_regular_at(
            directory_descriptor, name, "rendered visualization output"
        )
        if observed_identity != expected_identities.get(name):
            fail(f"rendered visualization output identity changed: {name}")
        if sha256_bytes(observed_content) != sha256_bytes(expected_content):
            fail(f"rendered visualization output hash mismatch: {name}")


def require_absent_entries(
    directory_descriptor: int,
    names: tuple[str, ...],
) -> None:
    conflicts = [name for name in names if entry_stat(directory_descriptor, name) is not None]
    if conflicts:
        fail(
            "fallback-only output name conflicts with an existing fragment; "
            "choose a new name instead of leaving a stale mount target: "
            + ", ".join(conflicts)
        )


def commit_output_set(
    directory_descriptor: int,
    outputs: list[tuple[str, bytes]],
    *,
    overwrite: bool,
    directory_path: Path,
    expected_directory_identity: tuple[int, int],
    absent_names: tuple[str, ...] = (),
) -> dict[str, tuple[int, ...]]:
    verify_directory_binding(
        directory_path, directory_descriptor, expected_directory_identity
    )
    require_absent_entries(directory_descriptor, absent_names)
    snapshots: dict[str, tuple[int, ...] | None] = {}
    for name, _content in outputs:
        observed = entry_stat(directory_descriptor, name)
        if observed is not None:
            validate_output_entry(observed, name)
            if not overwrite:
                fail(f"output already exists: {name}")
            snapshots[name] = stat_identity(observed)
        else:
            snapshots[name] = None

    prepared: dict[str, tuple[str, tuple[int, ...]]] = {}
    backups: dict[str, tuple[str, tuple[int, ...]]] = {}
    installed: dict[str, tuple[int, ...]] = {}
    committed = False
    try:
        for name, content in outputs:
            prepared[name] = write_secure_temp(directory_descriptor, name, content)
        os.fsync(directory_descriptor)
        verify_directory_binding(
            directory_path, directory_descriptor, expected_directory_identity
        )
        require_absent_entries(directory_descriptor, absent_names)

        for name, expected in snapshots.items():
            observed = entry_stat(directory_descriptor, name)
            actual = stat_identity(observed) if observed is not None else None
            if actual != expected:
                fail(f"output entry changed while preparing the set: {name}")
        require_absent_entries(directory_descriptor, absent_names)

        for name, expected in snapshots.items():
            if expected is None:
                continue
            backup_name = unused_entry_name(directory_descriptor, name, "backup")
            os.replace(
                name,
                backup_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            backups[name] = (backup_name, expected)
            backup_observed = entry_stat(directory_descriptor, backup_name)
            if backup_observed is None or not same_inode(expected, backup_observed):
                fail(f"output backup identity changed during rename: {name}")
            backups[name] = (backup_name, stat_identity(backup_observed))

        for name, _content in outputs:
            temp_name, temp_identity = prepared[name]
            os.replace(
                temp_name,
                name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            installed[name] = temp_identity
            installed_observed = entry_stat(directory_descriptor, name)
            if (
                installed_observed is None
                or not same_inode(temp_identity, installed_observed)
                or not stat.S_ISREG(installed_observed.st_mode)
                or installed_observed.st_nlink != 1
            ):
                fail(f"installed output identity changed during rename: {name}")
            prepared.pop(name)
            installed[name] = stat_identity(installed_observed)
        require_absent_entries(directory_descriptor, absent_names)
        verify_output_set(directory_descriptor, outputs, installed)
        verify_directory_binding(
            directory_path, directory_descriptor, expected_directory_identity
        )
        require_absent_entries(directory_descriptor, absent_names)
        os.fsync(directory_descriptor)
        committed = True

        cleanup_failures: list[str] = []
        for name, (backup_name, backup_identity) in list(backups.items()):
            if unlink_matching_entry(
                directory_descriptor, backup_name, backup_identity
            ):
                backups.pop(name)
            else:
                cleanup_failures.append(backup_name)
        os.fsync(directory_descriptor)
        if cleanup_failures:
            fail(
                "new output set committed but backup cleanup identity changed: "
                + ", ".join(cleanup_failures)
            )
        verify_directory_binding(
            directory_path, directory_descriptor, expected_directory_identity
        )
        require_absent_entries(directory_descriptor, absent_names)
        return dict(installed)
    except BaseException as exc:
        rollback_failures: list[str] = []
        if not committed:
            for name, identity in reversed(list(installed.items())):
                try:
                    if not unlink_matching_entry(directory_descriptor, name, identity):
                        rollback_failures.append(name)
                except OSError:
                    rollback_failures.append(name)
            for name, (backup_name, backup_identity) in reversed(list(backups.items())):
                try:
                    destination = entry_stat(directory_descriptor, name)
                    backup = entry_stat(directory_descriptor, backup_name)
                    if (
                        destination is not None
                        or backup is None
                        or not same_inode(backup_identity, backup)
                    ):
                        rollback_failures.append(name)
                        continue
                    os.replace(
                        backup_name,
                        name,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                    )
                    backups.pop(name)
                except OSError:
                    rollback_failures.append(name)
            try:
                os.fsync(directory_descriptor)
            except OSError:
                rollback_failures.append("directory-fsync")
        if rollback_failures:
            raise RuntimeError(
                "visualization output commit failed and rollback was incomplete: "
                + ", ".join(rollback_failures)
            ) from exc
        raise
    finally:
        for _name, (temp_name, temp_identity) in list(prepared.items()):
            try:
                unlink_matching_entry(directory_descriptor, temp_name, temp_identity)
            except OSError:
                pass
        for _name, (backup_name, backup_identity) in list(backups.items()):
            try:
                if committed:
                    unlink_matching_entry(
                        directory_descriptor, backup_name, backup_identity
                    )
            except OSError:
                pass


def render_visualization(
    payload_path: Path,
    output_directory: Path,
    name: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    if len(name) > 80 or NAME_PATTERN.fullmatch(name) is None:
        fail("name must contain only lowercase ASCII letters, digits, and hyphens")
    payload_path = payload_path.expanduser()
    source_bytes = read_regular_bytes(payload_path, "visualization payload")
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict):
        fail("visualization payload must be a JSON object")
    normalized = normalize_payload(payload)

    output_directory = output_directory.expanduser()
    if not output_directory.is_absolute():
        fail("output directory must be absolute")

    surface = normalized["surface"]
    inline_surface = surface in TEMPLATES
    fragment: str | None = None
    root_id: str | None = None
    template_hash: str | None = None
    verified_image_bytes: bytes | None = None
    verified_image_path: Path | None = None
    if inline_surface:
        fragment, fallback, root_id, template_hash = render_content(
            normalized, name=name
        )
    else:
        if surface == "image-review":
            verified_image_bytes = read_verified_image_bytes(
                Path(normalized["data"]["image_path"])
            )
            observed_image_hash = sha256_bytes(verified_image_bytes)
            if observed_image_hash != normalized["data"]["image_sha256"]:
                fail("image_path changed between validation and renderer copy")
            extension = image_extension(verified_image_bytes)
            verified_image_path = output_directory / f"{name}-verified.{extension}"
        fallback = render_fallback(
            normalized, verified_image_path=verified_image_path
        )
    fragment_bytes = fragment.encode("utf-8") if fragment is not None else None
    fallback_bytes = fallback.encode("utf-8")
    if fragment_bytes is not None and len(fragment_bytes) >= MAX_FRAGMENT_BYTES:
        fail("rendered visualization fragment must be smaller than 2 MB")

    fragment_path = output_directory / f"{name}.html"
    fallback_path = output_directory / f"{name}.md"
    manifest_path = output_directory / f"{name}.manifest.json"
    normalized_hash = sha256_bytes(canonical_bytes(normalized))
    directive = (
        f'::codex-inline-vis{{file="{fragment_path.name}"}}'
        if fragment_bytes is not None
        else None
    )
    manifest = {
        "manifest_version": "1.0",
        "surface": normalized["surface"],
        "source": {
            "payload_sha256": sha256_bytes(source_bytes),
            "normalized_sha256": normalized_hash,
            "template_sha256": template_hash,
            "renderer_sha256": sha256_bytes(
                read_regular_bytes(Path(__file__).resolve(), "visualization renderer")
            ),
        },
        "fragment": (
            {
                "file": fragment_path.name,
                "sha256": sha256_bytes(fragment_bytes),
                "bytes": len(fragment_bytes),
                "root_id": root_id,
                "inline_directive": directive,
            }
            if fragment_bytes is not None
            else None
        ),
        "fallback": {
            "file": fallback_path.name,
            "sha256": sha256_bytes(fallback_bytes),
            "bytes": len(fallback_bytes),
        },
        "verified_image": (
            {
                "file": verified_image_path.name,
                "sha256": sha256_bytes(verified_image_bytes),
                "bytes": len(verified_image_bytes),
            }
            if verified_image_path is not None
            and verified_image_bytes is not None
            else None
        ),
        "host_mount": {
            "status": "unverified",
            "reason": "This renderer does not produce or accept host mount/readback evidence.",
        },
    }

    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    directory_descriptor, output_directory_identity = open_directory_descriptor(
        output_directory
    )
    try:
        outputs = [
            (fallback_path.name, fallback_bytes),
            (manifest_path.name, manifest_bytes),
        ]
        if fragment_bytes is not None:
            outputs.insert(0, (fragment_path.name, fragment_bytes))
        if verified_image_path is not None and verified_image_bytes is not None:
            outputs.insert(0, (verified_image_path.name, verified_image_bytes))
        possible_siblings = {
            fragment_path.name,
            *(f"{name}-verified.{extension}" for extension in IMAGE_EXTENSIONS),
        }
        output_names = {output_name for output_name, _content in outputs}
        output_identities = commit_output_set(
            directory_descriptor,
            outputs,
            overwrite=overwrite,
            directory_path=output_directory,
            expected_directory_identity=output_directory_identity,
            absent_names=tuple(sorted(possible_siblings - output_names)),
        )
        verify_output_set(
            directory_descriptor,
            outputs,
            output_identities,
        )
        verify_directory_binding(
            output_directory,
            directory_descriptor,
            output_directory_identity,
        )
    finally:
        os.close(directory_descriptor)
    return {
        "fragment_path": fragment_path if fragment_bytes is not None else None,
        "fallback_path": fallback_path,
        "manifest_path": manifest_path,
        "verified_image_path": verified_image_path,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="JSON visualization payload")
    parser.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="existing absolute thread visualization directory",
    )
    parser.add_argument("--name", required=True, help="lowercase hyphenated output name")
    parser.add_argument("--overwrite", action="store_true", help="replace regular output files")
    args = parser.parse_args()
    result = render_visualization(
        args.data,
        args.output_directory,
        args.name,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "fragment": (
                    str(result["fragment_path"])
                    if result["fragment_path"] is not None
                    else None
                ),
                "fallback": str(result["fallback_path"]),
                "manifest": str(result["manifest_path"]),
                "verified_image": (
                    str(result["verified_image_path"])
                    if result["verified_image_path"] is not None
                    else None
                ),
                "inline_directive": (
                    result["manifest"]["fragment"]["inline_directive"]
                    if result["manifest"]["fragment"] is not None
                    else None
                ),
                "host_mount": "unverified",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Visualization render failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
