from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
from resolve_team_plan import (  # noqa: E402
    MAX_ACTIVE_POSITIONS,
    MAX_PARALLEL_POSITIONS,
    resolve_team_plan,
)


def profiles(team: dict[str, object]) -> list[str]:
    return [position["profile"] for position in team["positions"]]  # type: ignore[index]


class TeamPlannerTests(unittest.TestCase):
    def test_single_file_high_coupling_bug_stays_solo(self) -> None:
        item = work_item(
            "W-01",
            write_scope=["utils.py"],
            read_scope=["utils.py"],
            context_coupling="high",
            title="Fix one typo",
        )
        team = resolve_team_plan(task_plan(items=[item], title="Single file bug"))
        self.assertEqual(team["team_tier"], "solo")
        self.assertEqual(profiles(team), ["execution-root"])

    def test_cross_module_feature_gets_architect_developer_and_reviewer(self) -> None:
        items = [
            work_item(
                "W-01",
                work_type="architecture",
                read_scope=["api/", "domain/"],
                title="Cross-module interface migration",
            ),
            work_item(
                "W-02",
                dependencies=["W-01"],
                read_scope=["api/", "domain/"],
                write_scope=["api/handler.py", "domain/model.py"],
                risk="medium",
                title="Implement cross-module feature",
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertIn("developer", selected)
        self.assertIn("reviewer", selected)

    def test_three_independent_research_streams_keep_three_profile_instances(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                work_type="research",
                read_scope=[f"area-{index}/"],
                parallelizable=True,
                context_coupling="low",
            )
            for index in range(1, 4)
        ]
        team = resolve_team_plan(task_plan(items=items, title="Three independent studies"))
        research = [p for p in team["positions"] if p["profile"] == "codebase-researcher"]
        self.assertEqual(len(research), 3)
        self.assertEqual([p["instance"] for p in research], [1, 2, 3])
        self.assertEqual(len({tuple(p["read_scope"]) for p in research}), 3)

    def test_overlapping_writes_are_reported_and_not_parallel(self) -> None:
        items = [
            work_item(
                "W-01",
                write_scope=["src/shared.py"],
                parallelizable=True,
                isolated_worktree_required=True,
            ),
            work_item(
                "W-02",
                write_scope=["src/shared.py"],
                parallelizable=True,
                isolated_worktree_required=True,
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Conflicting writers"))
        self.assertEqual(team["write_conflicts"], [["W-01", "W-02"]])
        wave_two = next(wave for wave in team["waves"] if wave["wave"] == 2)
        self.assertLessEqual(len(wave_two["parallel_position_ids"]), 1)

    def test_test_debugger_is_signal_gated(self) -> None:
        item = work_item("W-01", work_type="testing", read_scope=["tests/"])
        ordinary = resolve_team_plan(task_plan(items=[item]))
        failed = resolve_team_plan(task_plan(items=[item]), signals={"real_test_failure": True})
        self.assertNotIn("test-debugger", profiles(ordinary))
        self.assertIn("test-debugger", profiles(failed))

    def test_position_and_parallel_limits_are_hard_caps(self) -> None:
        items = [
            work_item(
                f"W-{index:02d}",
                work_type="research",
                read_scope=[f"stream-{index}/"],
                parallelizable=True,
            )
            for index in range(1, 9)
        ]
        team = resolve_team_plan(task_plan(items=items, title="Many research streams"))
        self.assertLessEqual(len(team["positions"]), MAX_ACTIVE_POSITIONS)
        for wave in team["waves"]:
            self.assertLessEqual(len(wave["parallel_position_ids"]), MAX_PARALLEL_POSITIONS)


if __name__ == "__main__":
    unittest.main()
