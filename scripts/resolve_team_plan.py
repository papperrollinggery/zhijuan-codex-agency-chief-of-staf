#!/usr/bin/env python3
"""Build a deterministic position-instance team from task work items."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from agency_task import SCHEMA_VERSION, atomic_write_json, atomic_write_text, load_json, validate_task_plan


PROFILE_TITLES = {
    "execution-root": "项目总负责人",
    "codebase-researcher": "研究负责人",
    "technical-architect": "技术架构负责人",
    "developer": "实施负责人",
    "writer": "文档与交付负责人",
    "test-debugger": "测试诊断负责人",
    "reviewer": "独立质量负责人",
    "supervisor": "收口审计负责人",
}
PROFILE_WAVES = {
    "execution-root": 0,
    "codebase-researcher": 1,
    "technical-architect": 1,
    "developer": 2,
    "writer": 2,
    "test-debugger": 3,
    "reviewer": 4,
    "supervisor": 5,
}
ACCOUNTABLE_PROFILE_BY_WORK_TYPE = {
    "research": "codebase-researcher",
    "architecture": "technical-architect",
    "implementation": "developer",
    "integration": "developer",
    "writing": "writer",
    "testing": "test-debugger",
}
MAX_ACTIVE_POSITIONS = 5
MAX_PARALLEL_POSITIONS = 3
MAX_PARALLEL_WRITERS = 2
DEFAULT_COLD_REVIEWERS = 1
MAX_REVIEW_FIX_ROUNDS = 2
RISK_POINTS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
LEVEL_POINTS = {"low": 0, "medium": 1, "high": 2}
FAILURE_RE = re.compile(r"\b(?:fail(?:ed|ing|ure)?|error|flaky|regression)\b|失败|报错|不稳定|根因", re.I)
ARCHITECTURE_RE = re.compile(r"migration|migrate|cross[- ]module|interface|architecture|迁移|跨模块|接口|架构", re.I)
MIGRATION_RE = re.compile(r"migration|migrate|cross[- ]module|迁移|跨模块", re.I)
SECURITY_RE = re.compile(
    r"security|auth(?:entication|orization)?|credential|permission|secret|vulnerab|"
    r"安全|鉴权|认证|权限|凭据|密钥|漏洞",
    re.I,
)
GOAL_RE = re.compile(r"\bgoal\b|长期|持续项目", re.I)


def _scope_prefix(raw: str) -> tuple[str, ...]:
    parts: list[str] = []
    for part in PurePosixPath(raw).parts:
        if any(character in part for character in "*?["):
            break
        if part not in {".", ""}:
            parts.append(part)
    return tuple(parts)


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    for left_raw in left:
        for right_raw in right:
            left_prefix = _scope_prefix(left_raw)
            right_prefix = _scope_prefix(right_raw)
            if not left_prefix or not right_prefix:
                return True
            length = min(len(left_prefix), len(right_prefix))
            if left_prefix[:length] == right_prefix[:length]:
                return True
    return False


def dependency_depth(items: list[dict[str, Any]]) -> int:
    graph = {item["work_id"]: item["dependencies"] for item in items}
    memo: dict[str, int] = {}

    def depth(work_id: str) -> int:
        if work_id not in memo:
            memo[work_id] = 1 + max((depth(value) for value in graph[work_id]), default=0)
        return memo[work_id]

    return max((depth(work_id) for work_id in graph), default=0)


def write_conflict_pairs(items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    writers = [item for item in items if item["write_scope"]]
    conflicts: list[tuple[str, str]] = []
    for index, left in enumerate(writers):
        for right in writers[index + 1 :]:
            if scopes_overlap(left["write_scope"], right["write_scope"]):
                conflicts.append((left["work_id"], right["work_id"]))
    return conflicts


def is_cross_module(items: list[dict[str, Any]], plan: dict[str, Any]) -> bool:
    scope_roots = {
        _scope_prefix(path)[:1]
        for item in items
        for path in item["read_scope"] + item["write_scope"]
        if _scope_prefix(path)
    }
    narrative = " ".join(
        [plan["title"], plan["objective"]]
        + [item["title"] + " " + item["outcome"] for item in items]
    )
    structural_work = any(
        item["work_type"] in {"architecture", "integration"} for item in items
    )
    return bool(MIGRATION_RE.search(narrative)) or (
        len(scope_roots) >= 2
        and (structural_work or bool(ARCHITECTURE_RE.search(narrative)))
    )


def requires_independent_review(
    items: list[dict[str, Any]], plan: dict[str, Any], signals: dict[str, Any]
) -> bool:
    narrative = " ".join(
        [plan["title"], plan["objective"]]
        + [item["title"] + " " + item["outcome"] for item in items]
    )
    scope_roots = {
        _scope_prefix(path)[:1]
        for item in items
        for path in item["read_scope"] + item["write_scope"]
        if _scope_prefix(path)
    }
    structural_cross_module = len(scope_roots) >= 2 and any(
        item["work_type"] in {"architecture", "integration"} for item in items
    )
    return (
        signals.get("independent_review_required") is True
        or any(item["work_type"] == "review" for item in items)
        or any(item["risk"] in {"high", "critical"} for item in items)
        or any(item["work_type"] == "release" for item in items)
        or structural_cross_module
        or bool(MIGRATION_RE.search(narrative))
        or bool(SECURITY_RE.search(narrative))
    )


def requires_test_debugger(items: list[dict[str, Any]], signals: dict[str, Any]) -> bool:
    if signals.get("real_test_failure") is True or signals.get("competing_root_causes") is True:
        return True
    failure_text = " ".join(
        item["title"] + " " + item["outcome"] + " " + " ".join(item["blockers"])
        for item in items
        if item["work_type"] == "testing"
    )
    return bool(failure_text and FAILURE_RE.search(failure_text))


def score_dimensions(plan: dict[str, Any], signals: dict[str, Any]) -> dict[str, int]:
    items = plan["work_items"]
    conflicts = write_conflict_pairs(items)
    types = {item["work_type"] for item in items}
    parallel_items = [
        item
        for item in items
        if item["parallelizable"] and item["context_coupling"] == "low"
    ]
    specialist_types = types & {"research", "architecture", "writing", "testing", "release"}
    parallel_gain = min(2, max(0, len(parallel_items) - 1))
    parallel_gain = max(0, parallel_gain - min(2, len(conflicts)))
    return {
        "workstream_count": min(3, max(0, len(types) - 1)),
        "dependency_depth": min(2, max(0, dependency_depth(items) - 1)),
        "uncertainty": max((LEVEL_POINTS[item["uncertainty"]] for item in items), default=0),
        "risk": max((RISK_POINTS[item["risk"]] for item in items), default=0),
        # A conflict is a scheduling cost, never a reason to grow the team.
        "write_conflict": 0,
        "specialist_need": min(3, len(specialist_types)),
        "parallel_gain": parallel_gain,
        "independent_review_need": (
            2 if requires_independent_review(items, plan, signals) else 0
        ),
        "duration_scope": 0 if len(items) <= 1 else 1 if len(items) <= 3 else 2,
    }


def tier_for_score(score: int) -> str:
    if score <= 3:
        return "solo"
    if score <= 6:
        return "lean_team"
    if score <= 10:
        return "project_team"
    return "program_team"


def _position(
    profile: str,
    items: list[dict[str, Any]],
    instance: int,
    *,
    position_suffix: str | None = None,
) -> dict[str, Any]:
    suffix = position_suffix or str(instance)
    position_id = "execution-root" if profile == "execution-root" else f"{profile}-{suffix.lower()}"
    writable_items = [item for item in items if item["write_scope"]]
    return {
        "position_id": position_id,
        "title": PROFILE_TITLES[profile],
        "profile": profile,
        "work_items": [item["work_id"] for item in items],
        "instance": instance,
        "read_scope": sorted({path for item in items for path in item["read_scope"]}),
        "write_scope": sorted({path for item in items for path in item["write_scope"]}),
        "wave": PROFILE_WAVES[profile],
        "isolated_worktree_required": bool(
            profile in {"developer", "writer"}
            and writable_items
            and all(item["isolated_worktree_required"] for item in writable_items)
        ),
    }


def _dedicated_research_positions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = [item for item in items if item["work_type"] == "research"]
    if len(research) <= 1:
        return []
    independently_parallel = all(
        item["parallelizable"] and item["context_coupling"] == "low" and item["read_scope"]
        for item in research
    )
    distinct_scopes = all(
        not scopes_overlap(left["read_scope"], right["read_scope"])
        for index, left in enumerate(research)
        for right in research[index + 1 :]
    )
    distinct_outputs = len({item["outcome"] for item in research}) == len(research)
    if independently_parallel and distinct_scopes and distinct_outputs:
        return [
            _position(
                "codebase-researcher",
                [item],
                index,
                position_suffix=item["work_id"],
            )
            for index, item in enumerate(research, 1)
        ]
    return [_position("codebase-researcher", research, 1)]


def _parallel_implementation_streams(
    implementation: list[dict[str, Any]],
) -> bool:
    return (
        len(implementation) > 1
        and all(
            item["context_coupling"] == "low"
            and item["parallelizable"]
            and item["write_scope"]
            and item["isolated_worktree_required"]
            for item in implementation
        )
        and not write_conflict_pairs(implementation)
        and len({item["outcome"] for item in implementation}) == len(implementation)
    )


def _developer_positions(
    items: list[dict[str, Any]], signals: dict[str, Any]
) -> list[dict[str, Any]]:
    implementation = [
        item for item in items if item["work_type"] in {"implementation", "integration"}
    ]
    if not implementation:
        return []
    parallel_streams = _parallel_implementation_streams(implementation)
    if not parallel_streams and signals.get("explicit_delegate_implementation") is not True:
        return []
    if parallel_streams:
        return [
            _position("developer", [item], index, position_suffix=item["work_id"])
            for index, item in enumerate(implementation, 1)
        ]
    return [_position("developer", implementation, 1)]


def _candidate_positions(
    plan: dict[str, Any], signals: dict[str, Any]
) -> list[dict[str, Any]]:
    items = plan["work_items"]
    candidates = _dedicated_research_positions(items)
    if is_cross_module(items, plan):
        architecture_items = [
            item
            for item in items
            if item["work_type"] == "architecture" or ARCHITECTURE_RE.search(item["title"] + " " + item["outcome"])
        ] or items
        candidates.append(_position("technical-architect", architecture_items, 1))

    candidates.extend(_developer_positions(items, signals))
    writing = [item for item in items if item["work_type"] == "writing"]
    if len(writing) > 1:
        candidates.append(_position("writer", writing, 1))
    testing = [item for item in items if item["work_type"] == "testing"]
    if testing and requires_test_debugger(items, signals):
        candidates.append(_position("test-debugger", testing, 1))
    review = [item for item in items if item["work_type"] == "review"]
    if requires_independent_review(items, plan, signals):
        candidates.append(_position("reviewer", review or items, 1))
    narrative = plan["title"] + " " + plan["objective"]
    if (
        any(item["work_type"] == "release" or item["risk"] == "critical" for item in items)
        or GOAL_RE.search(narrative)
        or signals.get("complex_archive") is True
    ):
        candidates.append(_position("supervisor", items, 1))
    return candidates


def _waves(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for wave in range(6):
        members = [item for item in positions if item["wave"] == wave]
        if not members:
            continue
        parallel: list[str] = []
        sequential: list[str] = []
        parallel_writers = 0
        for member in members:
            writable = member["profile"] in {"developer", "writer"} and bool(
                member["write_scope"]
            )
            conflicts_with_parallel = any(
                scopes_overlap(member["write_scope"], other["write_scope"])
                for other in members
                if other["position_id"] in parallel and member["write_scope"] and other["write_scope"]
            )
            write_requires_isolation = writable and not member["isolated_worktree_required"]
            if (
                len(parallel) >= MAX_PARALLEL_POSITIONS
                or writable and parallel_writers >= MAX_PARALLEL_WRITERS
                or conflicts_with_parallel
                or write_requires_isolation
            ):
                sequential.append(member["position_id"])
            else:
                parallel.append(member["position_id"])
                if writable:
                    parallel_writers += 1
        result.append(
            {
                "wave": wave,
                "label": {
                    0: "Execution Root 读取计划和项目状态",
                    1: "独立研究与架构判断",
                    2: "实现与文档工作",
                    3: "测试诊断，仅在需要时",
                    4: "独立 Review",
                    5: "Supervisor 收口，仅在需要时",
                }[wave],
                "parallel_position_ids": parallel,
                "sequential_position_ids": sequential,
            }
        )
    return result


def resolve_team_plan(
    raw_plan: dict[str, Any], *, signals: dict[str, Any] | None = None
) -> dict[str, Any]:
    plan = validate_task_plan(raw_plan)
    signals = signals or {}
    if not isinstance(signals, dict):
        raise ValueError("team planner signals must be an object")
    items = plan["work_items"]
    conflicts = write_conflict_pairs(items)
    breakdown = score_dimensions(plan, signals)
    score = sum(breakdown.values())
    tier = tier_for_score(score)
    root = _position("execution-root", items, 1)
    candidates = _candidate_positions(plan, signals)

    profile_priority = {
        "technical-architect": 100,
        "reviewer": 95,
        "codebase-researcher": 75,
        "developer": 70,
        "writer": 60,
        "test-debugger": 55,
        "supervisor": 90,
    }
    if signals.get("explicit_delegate_implementation") is True:
        profile_priority["developer"] = 90
    candidates = sorted(
        candidates,
        key=lambda item: (-profile_priority[item["profile"]], item["instance"], item["position_id"]),
    )
    chosen = candidates[: MAX_ACTIVE_POSITIONS - 1]
    selected = [root] + sorted(
        chosen,
        key=lambda item: (PROFILE_WAVES[item["profile"]], item["position_id"]),
    )
    root_owned = sorted(
        item["work_id"]
        for item in items
        if not any(
            position["profile"] == ACCOUNTABLE_PROFILE_BY_WORK_TYPE.get(item["work_type"])
            and item["work_id"] in position["work_items"]
            for position in selected
        )
    )
    if len(selected) == 1:
        tier = "solo"
    elif tier == "solo":
        tier = "lean_team"

    counts = Counter(position["profile"] for position in selected)
    for profile, count in counts.items():
        instances = sorted(
            position["instance"] for position in selected if position["profile"] == profile
        )
        if instances != list(range(1, count + 1)):
            raise AssertionError(f"non-contiguous position instances: {profile}")
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": plan["task_id"],
        "status": "ready",
        "team_tier": tier,
        "score": score,
        "score_breakdown": breakdown,
        "positions": selected,
        "waves": _waves(selected),
        "write_conflicts": [list(pair) for pair in conflicts],
        "root_owned_work_items": root_owned,
        "limits": {
            "max_active_positions": MAX_ACTIVE_POSITIONS,
            "max_parallel_positions": MAX_PARALLEL_POSITIONS,
            "max_parallel_writers": MAX_PARALLEL_WRITERS,
            "default_cold_reviewers": DEFAULT_COLD_REVIEWERS,
            "max_review_fix_rounds": MAX_REVIEW_FIX_ROUNDS,
        },
    }


def render_team_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# 团队执行计划",
        "",
        f"- 团队等级：{plan['team_tier']}",
        f"- 活跃职位：{len(plan['positions'])} / {MAX_ACTIVE_POSITIONS}",
        "",
        "## 职位安排",
        "",
    ]
    for position in plan["positions"]:
        work = "、".join(position["work_items"])
        lines.append(
            f"- {position['title']}（实例 {position['instance']}）：{work}"
        )
    lines.extend(["", "## 调度波次", ""])
    for wave in plan["waves"]:
        lines.append(f"- Wave {wave['wave']}：{wave['label']}")
    lines.extend(
        [
            "",
            "团队规模是上限，不是目标；写范围冲突不并行，Profile 相同也必须保持不同工作项、范围和输出。",
            "",
        ]
    )
    return "\n".join(lines)


def write_team_plan(task_dir: Path, team_plan: dict[str, Any]) -> None:
    resolved = task_dir.resolve()
    if not resolved.is_dir() or resolved.is_symlink():
        raise ValueError("task directory must be a non-symlink directory")
    task_plan_path = resolved / "task-plan.json"
    task_plan = validate_task_plan(load_json(task_plan_path), expected_task_id=team_plan["task_id"])
    positions_by_work: dict[str, list[dict[str, Any]]] = {}
    for position in team_plan["positions"]:
        for work_id in position["work_items"]:
            positions_by_work.setdefault(work_id, []).append(position)
    for item in task_plan["work_items"]:
        positions = positions_by_work.get(item["work_id"], [])
        accountable = next(
            (
                position
                for position in positions
                if position["profile"]
                == ACCOUNTABLE_PROFILE_BY_WORK_TYPE.get(item["work_type"])
            ),
            next((position for position in positions if position["profile"] == "execution-root"), None),
        )
        reviewer = next((position for position in positions if position["profile"] == "reviewer"), None)
        if accountable:
            item["accountable_position"] = accountable["title"]
            item["profile"] = None if accountable["profile"] == "execution-root" else accountable["profile"]
        item["review_profile"] = reviewer["profile"] if reviewer else None
    atomic_write_json(task_plan_path, task_plan)
    atomic_write_json(resolved / "TEAM_PLAN.json", team_plan)
    atomic_write_text(resolved / "TEAM_PLAN.md", render_team_plan(team_plan))


def _self_test_plan(work_items: list[dict[str, Any]], title: str = "Team planner test") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-team-self-test",
        "title": title,
        "objective": title,
        "source_discussion": {
            "summary": "Accepted planner fixture",
            "accepted_decisions": [],
            "constraints": [],
            "assumptions": [],
            "open_questions": [],
        },
        "acceptance_criteria": ["Team is bounded"],
        "out_of_scope": [],
        "execution_model_request": {
            "display_request": "GPT-5.6 Sol",
            "reasoning_request": "ultra",
            "resolved_model_id": None,
            "resolution_status": "pending",
        },
        "work_items": work_items,
        "status": "plan_ready",
    }


def _work(work_id: str, work_type: str, scope: str, **overrides: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "work_id": work_id,
        "title": f"{work_type} {work_id}",
        "outcome": f"Complete {work_id}",
        "work_type": work_type,
        "dependencies": [],
        "read_scope": [scope],
        "write_scope": [] if work_type == "research" else [scope],
        "verification": [f"verify {work_id}"],
        "risk": "low",
        "uncertainty": "low",
        "context_coupling": "low",
        "parallelizable": work_type == "research",
        "isolated_worktree_required": False,
        "accountable_position": "",
        "profile": None,
        "review_profile": None,
        "status": "pending",
        "evidence_refs": [],
        "blockers": [],
    }
    item.update(overrides)
    return item


def run_self_test() -> dict[str, Any]:
    solo = resolve_team_plan(
        _self_test_plan(
            [_work("W-01", "implementation", "utils.py", context_coupling="high")]
        )
    )
    if solo["team_tier"] != "solo" or len(solo["positions"]) != 1:
        raise AssertionError("single-file high-coupling task was over-dispatched")
    research = resolve_team_plan(
        _self_test_plan(
            [
                _work("W-01", "research", "mobile/"),
                _work("W-02", "research", "server/"),
                _work("W-03", "research", "infra/"),
            ]
        )
    )
    researchers = [
        position for position in research["positions"] if position["profile"] == "codebase-researcher"
    ]
    if len(researchers) != 3 or len({item["position_id"] for item in researchers}) != 3:
        raise AssertionError("independent researcher instances were collapsed")
    feature_items = [
        _work("W-01", "architecture", "api/", title="Cross-module interface"),
        _work(
            "W-02",
            "implementation",
            "client/",
            dependencies=["W-01"],
            risk="medium",
            parallelizable=True,
            isolated_worktree_required=True,
        ),
        _work(
            "W-03",
            "implementation",
            "server/",
            dependencies=["W-01"],
            risk="medium",
            parallelizable=True,
            isolated_worktree_required=True,
        ),
    ]
    feature = resolve_team_plan(_self_test_plan(feature_items, "Cross-module migration"))
    profiles = {position["profile"] for position in feature["positions"]}
    if not {"technical-architect", "developer", "reviewer"}.issubset(profiles):
        raise AssertionError("cross-module feature lacks architect, developer, or reviewer")
    if any(len(wave["parallel_position_ids"]) > MAX_PARALLEL_POSITIONS for wave in feature["waves"]):
        raise AssertionError("parallel position limit exceeded")
    return {
        "status": "self-test-passed",
        "solo_positions": len(solo["positions"]),
        "researcher_instances": len(researchers),
        "cross_module_profiles": sorted(profiles),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve a deterministic Agency team plan.")
    parser.add_argument("--task-plan", type=Path)
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--write-task-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = run_self_test()
    else:
        if args.task_plan is None:
            raise ValueError("--task-plan is required unless --self-test is used")
        signals = load_json(args.signals) if args.signals else None
        result = resolve_team_plan(load_json(args.task_plan), signals=signals)
        if args.write_task_dir:
            write_team_plan(args.write_task_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json or args.self_test else render_team_plan(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"Team plan resolution failed: {exc}")
