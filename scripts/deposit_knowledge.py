#!/usr/bin/env python3
"""Validate, deduplicate, and minimally deposit reusable task knowledge."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

from agency_task import (
    atomic_write_json,
    atomic_write_text,
    read_regular_text,
    safe_project_root,
    utc_now,
)


CATEGORIES = frozenset(
    {"architecture", "workflow", "runbook", "debugging", "testing", "decision", "preference"}
)
SENSITIVITIES = frozenset({"public", "internal", "restricted"})
REQUIRED_FIELDS = {
    "knowledge_id",
    "category",
    "statement",
    "applicability",
    "evidence_refs",
    "source_task_id",
    "confidence",
    "sensitivity",
    "recommended_target",
    "status",
}
SECRET_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{12,}|"
    r"\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|bearer)\s*[:=]\s*\S+",
    re.I,
)
TEMPORARY_RE = re.compile(
    r"(?:/tmp/|/var/folders/|\\Temp\\|\.agency/tasks/active/|\.codex/worktrees/|/" r"Users/)|"
    r"\b(?:thread|task)[ _-]?id\s*[:=]\s*[0-9a-f-]{12,}|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.I,
)
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,95}\Z")


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKC", value).casefold()).strip("-")
    return result[:64] or "task-knowledge"


def load_candidates(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(read_regular_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("knowledge candidates must be valid UTF-8 JSON") from exc
    if not isinstance(value, list):
        raise ValueError("knowledge candidates must be a JSON list")
    return validate_knowledge_candidates(value)


def validate_knowledge_candidates(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("knowledge candidates must be a list")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != REQUIRED_FIELDS:
            raise ValueError(f"knowledge candidate {index} fields are invalid")
        candidate = dict(raw)
        knowledge_id = candidate["knowledge_id"]
        if not isinstance(knowledge_id, str) or not SAFE_ID_RE.fullmatch(knowledge_id):
            raise ValueError(f"knowledge candidate {index} has an unsafe id")
        if knowledge_id in seen_ids:
            raise ValueError(f"duplicate knowledge id: {knowledge_id}")
        seen_ids.add(knowledge_id)
        if candidate["category"] not in CATEGORIES:
            raise ValueError(f"knowledge candidate {knowledge_id} category is invalid")
        for key in ("statement", "applicability", "source_task_id", "recommended_target"):
            if not isinstance(candidate[key], str) or not candidate[key].strip():
                raise ValueError(f"knowledge candidate {knowledge_id} {key} is empty")
            candidate[key] = candidate[key].strip()
        if not SAFE_ID_RE.fullmatch(candidate["source_task_id"]):
            raise ValueError(f"knowledge candidate {knowledge_id} source_task_id is unsafe")
        evidence = candidate["evidence_refs"]
        if not isinstance(evidence, list) or not evidence or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise ValueError(f"knowledge candidate {knowledge_id} needs evidence_refs")
        candidate["evidence_refs"] = [item.strip() for item in evidence]
        if candidate["confidence"] not in {"verified", "limited"}:
            raise ValueError(f"knowledge candidate {knowledge_id} confidence is invalid")
        if candidate["sensitivity"] not in SENSITIVITIES:
            raise ValueError(f"knowledge candidate {knowledge_id} sensitivity is invalid")
        if candidate["status"] != "candidate":
            raise ValueError(f"knowledge candidate {knowledge_id} must start as candidate")
        durable_text = "\n".join(
            [
                candidate["statement"],
                candidate["applicability"],
                candidate["recommended_target"],
                *candidate["evidence_refs"],
            ]
        )
        if SECRET_RE.search(durable_text):
            raise ValueError(f"knowledge candidate {knowledge_id} may contain a secret")
        if TEMPORARY_RE.search(durable_text):
            raise ValueError(f"knowledge candidate {knowledge_id} contains temporary task data")
        result.append(candidate)
    return result


def knowledge_documents(project: Path) -> list[Path]:
    result: list[Path] = []
    for relative in ("CONTEXT.md", "README.md"):
        path = project / relative
        if path.is_file() and not path.is_symlink():
            result.append(path)
    docs = project / "docs"
    if docs.is_dir() and not docs.is_symlink():
        result.extend(
            path
            for path in docs.rglob("*.md")
            if path.is_file() and not path.is_symlink()
        )
    return sorted(set(result))


def safe_target(project: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"knowledge target is unsafe: {relative}")
    if candidate.parts[0] not in {"README.md", "CONTEXT.md", "docs"}:
        raise ValueError(f"knowledge target is outside allowed documents: {relative}")
    current = project
    for part in candidate.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"knowledge target traverses a symlink: {relative}")
    resolved = (project / candidate).resolve()
    if not resolved.is_relative_to(project.resolve()):
        raise ValueError(f"knowledge target escapes project: {relative}")
    return resolved


def _relevant_existing(candidate: dict[str, Any], documents: list[Path]) -> Path | None:
    tokens = semantic_tokens(candidate["statement"])
    best: tuple[int, Path] | None = None
    for path in documents:
        headings = " ".join(
            line.lstrip("# ").strip()
            for line in read_regular_text(path).splitlines()
            if line.startswith("#")
        )
        path_tokens = semantic_tokens(f"{path.stem} {headings}")
        score = len(tokens & path_tokens)
        if score >= 2 and (best is None or score > best[0]):
            best = (score, path)
    return best[1] if best else None


def semantic_tokens(value: str) -> set[str]:
    """Return stable Latin words and CJK n-grams for filename/heading matching."""
    normalized = normalized_text(value)
    tokens = set(re.findall(r"[a-z0-9]{3,}", normalized))
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        for width in (2, 3, 4):
            tokens.update(run[index : index + width] for index in range(len(run) - width + 1))
    return tokens


def validate_candidate_provenance(
    candidates: list[dict[str, Any]],
    *,
    source_task_id: str,
    allowed_evidence_refs: set[str],
) -> None:
    """Bind archive candidates to the task and evidence that actually closed it."""
    for candidate in candidates:
        knowledge_id = candidate["knowledge_id"]
        if candidate["source_task_id"] != source_task_id:
            raise ValueError(
                f"knowledge candidate {knowledge_id} is not bound to task {source_task_id}"
            )
        unknown = sorted(set(candidate["evidence_refs"]) - allowed_evidence_refs)
        if unknown:
            raise ValueError(
                f"knowledge candidate {knowledge_id} references evidence outside the closure: "
                + ", ".join(unknown)
            )


def _next_adr(directory: Path, topic: str) -> Path:
    numbers = []
    if directory.is_dir():
        for path in directory.glob("*.md"):
            match = re.match(r"(\d+)", path.name)
            if match:
                numbers.append(int(match.group(1)))
    number = max(numbers, default=0) + 1
    return directory / f"{number:04d}-{topic}.md"


def choose_target(project: Path, candidate: dict[str, Any], documents: list[Path]) -> Path:
    recommended = candidate["recommended_target"]
    if recommended != "auto":
        return safe_target(project, recommended)
    relevant = _relevant_existing(candidate, documents)
    if relevant is not None:
        return relevant
    topic = slug(candidate["knowledge_id"])
    category = candidate["category"]
    if category in {"architecture", "decision"} and (project / "docs" / "adr").is_dir():
        return _next_adr(project / "docs" / "adr", topic)
    mapped = {
        "architecture": "architecture",
        "workflow": "workflows",
        "runbook": "runbooks",
        "testing": "testing",
    }.get(category)
    if mapped and (project / "docs" / mapped).is_dir():
        return project / "docs" / mapped / f"{topic}.md"
    if category == "preference" and (project / "CONTEXT.md").is_file():
        return project / "CONTEXT.md"
    return project / "docs" / "knowledge" / f"{topic}.md"


def candidate_fragment(candidate: dict[str, Any]) -> str:
    evidence = "；".join(candidate["evidence_refs"])
    title = re.sub(r"[._-]+", " ", candidate["knowledge_id"]).strip().title()
    return "\n".join(
        [
            f"## {title}",
            "",
            candidate["statement"],
            "",
            f"适用范围：{candidate['applicability']}",
            "",
            f"Source Task: `{candidate['source_task_id']}`",
            f"Evidence: {evidence}",
            f"Knowledge ID: `{candidate['knowledge_id']}`",
            "",
        ]
    )


def plan_deposits(project: Path, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = safe_project_root(project)
    documents = knowledge_documents(root)
    document_text = {
        path: read_regular_text(path) for path in documents
    }
    all_text = "\n".join(document_text.values())
    normalized_all = normalized_text(all_text)
    actions: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["confidence"] != "verified":
            actions.append(
                {
                    "knowledge_id": candidate["knowledge_id"],
                    "action": "skipped_limited",
                    "target": None,
                }
            )
            continue
        statement = normalized_text(candidate["statement"])
        id_marker = f"Knowledge ID: `{candidate['knowledge_id']}`"
        if statement in normalized_all:
            actions.append(
                {
                    "knowledge_id": candidate["knowledge_id"],
                    "action": "duplicate",
                    "target": None,
                }
            )
            continue
        if id_marker in all_text:
            raise ValueError(
                f"knowledge id conflicts with an existing different statement: {candidate['knowledge_id']}"
            )
        target = choose_target(root, candidate, documents)
        relative = str(target.relative_to(root))
        if candidate["sensitivity"] != "public" and relative == "README.md":
            raise ValueError("internal or restricted knowledge cannot be deposited in README.md")
        actions.append(
            {
                "knowledge_id": candidate["knowledge_id"],
                "action": "append" if target.exists() else "create",
                "target": relative,
                "fragment": candidate_fragment(candidate),
            }
        )
        normalized_all += " " + statement
        all_text += "\n" + id_marker
    return actions


def apply_deposits(
    project: Path,
    actions: list[dict[str, Any]],
    *,
    finalize: Callable[[], None] | None = None,
) -> None:
    root = safe_project_root(project)
    updates: dict[Path, str] = {}
    originals: dict[Path, tuple[bool, str]] = {}
    missing_directories: set[Path] = set()
    for action in actions:
        if action["action"] not in {"append", "create"}:
            continue
        target = safe_target(root, action["target"])
        existing = updates.get(target)
        if existing is None:
            existed = target.exists()
            existing = read_regular_text(target) if existed else ""
            originals[target] = (existed, existing)
            parent = target.parent
            while parent != root and not parent.exists():
                missing_directories.add(parent)
                parent = parent.parent
        fragment = action["fragment"]
        if existing:
            updates[target] = existing.rstrip() + "\n\n" + fragment
        else:
            title = target.stem.replace("-", " ").title()
            updates[target] = f"# {title}\n\n{fragment}"
    attempted: list[Path] = []
    try:
        for target, content in updates.items():
            attempted.append(target)
            atomic_write_text(target, content.rstrip() + "\n")
        if finalize is not None:
            finalize()
    except (OSError, RuntimeError, ValueError) as exc:
        rollback_errors: list[str] = []
        for target in reversed(attempted):
            existed, original = originals[target]
            try:
                if existed:
                    atomic_write_text(target, original)
                elif target.exists() and not target.is_symlink():
                    target.unlink()
            except (OSError, ValueError) as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        for directory in sorted(missing_directories, key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        detail = f"knowledge deposit write failed: {exc}"
        if rollback_errors:
            detail += "; rollback incomplete: " + "; ".join(rollback_errors)
        raise RuntimeError(detail) from exc


def _safe_report_path(project: Path, supplied: Path) -> Path:
    root = safe_project_root(project)
    candidate = supplied.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("knowledge report must stay inside the project") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("knowledge report path traverses a symlink")
    if candidate.exists() and not candidate.is_file():
        raise ValueError("knowledge report path must be a regular file")
    return candidate


def _write_report_with_rollback(
    project: Path, report_path: Path, report: dict[str, Any]
) -> None:
    root = safe_project_root(project)
    path = _safe_report_path(root, report_path)
    existed = path.exists()
    original = read_regular_text(path) if existed else ""
    missing_directories: list[Path] = []
    parent = path.parent
    while parent != root and not parent.exists():
        missing_directories.append(parent)
        parent = parent.parent
    try:
        atomic_write_json(path, report)
    except (OSError, ValueError) as exc:
        rollback_errors: list[str] = []
        try:
            if existed:
                atomic_write_text(path, original)
            elif path.exists() and not path.is_symlink() and path.is_file():
                path.unlink()
        except (OSError, ValueError) as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        for directory in missing_directories:
            try:
                directory.rmdir()
            except OSError:
                pass
        if rollback_errors:
            raise RuntimeError(
                "knowledge report write failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise


def deposit_knowledge(
    project: Path,
    candidates_path: Path,
    *,
    apply: bool,
    report_path: Path | None = None,
    expected_source_task_id: str | None = None,
    allowed_evidence_refs: set[str] | None = None,
) -> dict[str, Any]:
    root = safe_project_root(project)
    candidates = load_candidates(candidates_path)
    if expected_source_task_id is not None:
        validate_candidate_provenance(
            candidates,
            source_task_id=expected_source_task_id,
            allowed_evidence_refs=allowed_evidence_refs or set(),
        )
    actions = plan_deposits(root, candidates)
    report = {
        "schema_version": "1.0",
        "status": "applied" if apply else "planned",
        "project": str(root),
        "source_candidates": str(candidates_path.resolve()),
        "actions": [
            {key: value for key, value in action.items() if key != "fragment"}
            for action in actions
        ],
        "deposited_count": sum(
            action["action"] in {"append", "create"} for action in actions
        )
        if apply
        else 0,
        "limited_candidates_skipped": sum(
            action["action"] == "skipped_limited" for action in actions
        ),
        "generated_at": utc_now(),
    }
    if apply:
        apply_deposits(
            root,
            actions,
            finalize=(
                lambda: _write_report_with_rollback(root, report_path, report)
                if report_path is not None
                else None
            ),
        )
    elif report_path is not None:
        _write_report_with_rollback(root, report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Deposit verified Agency knowledge candidates.")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = deposit_knowledge(
        args.project,
        args.candidates,
        apply=args.apply,
        report_path=args.report,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Knowledge deposit failed: {exc}")
