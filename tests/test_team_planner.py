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
    MAX_PARALLEL_WRITERS,
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

    def test_single_low_value_work_stays_root_only(self) -> None:
        cases = (
            work_item(
                "W-01",
                work_type="implementation",
                read_scope=["src/feature.py"],
                write_scope=["src/feature.py"],
                context_coupling="low",
                parallelizable=True,
                isolated_worktree_required=True,
            ),
            work_item(
                "W-01",
                work_type="writing",
                read_scope=["README.md"],
                write_scope=["README.md"],
            ),
            work_item(
                "W-01",
                work_type="research",
                read_scope=["src/"],
                parallelizable=True,
            ),
        )
        for item in cases:
            with self.subTest(work_type=item["work_type"]):
                team = resolve_team_plan(task_plan(items=[item]))
                self.assertEqual(team["team_tier"], "solo")
                self.assertEqual(profiles(team), ["execution-root"])
                self.assertEqual(team["root_owned_work_items"], ["W-01"])

    def test_explicit_implementation_delegation_overrides_single_item_gate(self) -> None:
        item = work_item(
            "W-01",
            read_scope=["src/feature.py"],
            write_scope=["src/feature.py"],
        )
        team = resolve_team_plan(
            task_plan(items=[item]),
            signals={"explicit_delegate_implementation": True},
        )
        self.assertIn("developer", profiles(team))
        self.assertNotIn("W-01", team["root_owned_work_items"])

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
                read_scope=["api/"],
                write_scope=["api/handler.py"],
                risk="medium",
                parallelizable=True,
                isolated_worktree_required=True,
                title="Implement cross-module feature",
            ),
            work_item(
                "W-03",
                dependencies=["W-01"],
                read_scope=["domain/"],
                write_scope=["domain/model.py"],
                risk="medium",
                parallelizable=True,
                isolated_worktree_required=True,
                title="Implement migrated domain model",
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertIn("developer", selected)
        self.assertIn("reviewer", selected)

    def test_single_cross_module_integration_gets_one_developer(self) -> None:
        item = work_item(
            "W-01",
            work_type="integration",
            title="Cross-module interface migration",
            read_scope=["api/", "domain/", "persistence/"],
            write_scope=["api/handler.py", "domain/model.py", "persistence/store.py"],
            risk="medium",
            context_coupling="medium",
        )
        team = resolve_team_plan(task_plan(items=[item], title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertEqual(selected.count("developer"), 1)
        self.assertIn("reviewer", selected)

    def test_high_coupling_cross_module_implementation_stays_root_owned(self) -> None:
        item = work_item(
            "W-01",
            work_type="integration",
            title="Cross-module interface migration",
            read_scope=["api/", "domain/"],
            write_scope=["api/handler.py", "domain/model.py"],
            risk="medium",
            context_coupling="high",
        )
        team = resolve_team_plan(task_plan(items=[item], title="Cross-module migration"))
        self.assertNotIn("developer", profiles(team))
        self.assertIn("W-01", team["root_owned_work_items"])

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

    def test_research_instances_require_distinct_outputs(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                work_type="research",
                read_scope=[f"area-{index}/"],
                parallelizable=True,
                outcome="One shared report",
            )
            for index in range(1, 4)
        ]
        team = resolve_team_plan(task_plan(items=items, title="One combined study"))
        research = [p for p in team["positions"] if p["profile"] == "codebase-researcher"]
        self.assertEqual(len(research), 1)

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
        self.assertNotIn("developer", profiles(team))
        self.assertEqual(team["score_breakdown"]["write_conflict"], 0)

    def test_write_conflict_reduces_parallel_gain_instead_of_growing_team(self) -> None:
        def implementation(work_id: str, path: str) -> dict[str, object]:
            return work_item(
                work_id,
                write_scope=[path],
                parallelizable=True,
                isolated_worktree_required=True,
            )

        independent = resolve_team_plan(
            task_plan(items=[implementation("W-01", "src/a.py"), implementation("W-02", "src/b.py")])
        )
        conflicting = resolve_team_plan(
            task_plan(
                items=[
                    implementation("W-01", "src/shared.py"),
                    implementation("W-02", "src/shared.py"),
                ]
            )
        )
        self.assertGreater(
            independent["score_breakdown"]["parallel_gain"],
            conflicting["score_breakdown"]["parallel_gain"],
        )
        self.assertLess(conflicting["score"], independent["score"])

    def test_multiple_safe_implementation_streams_delegate_and_cap_parallel_writers(self) -> None:
        items = [
            work_item(
                f"W-{index:02d}",
                write_scope=[f"src/feature_{index}.py"],
                parallelizable=True,
                isolated_worktree_required=True,
            )
            for index in range(1, 5)
        ]
        team = resolve_team_plan(task_plan(items=items, title="Independent implementation streams"))
        developers = [position for position in team["positions"] if position["profile"] == "developer"]
        self.assertEqual(len(developers), 4)
        wave_two = next(wave for wave in team["waves"] if wave["wave"] == 2)
        self.assertEqual(len(wave_two["parallel_position_ids"]), MAX_PARALLEL_WRITERS)
        self.assertEqual(len(wave_two["sequential_position_ids"]), 2)

    def test_ordinary_multifile_medium_risk_delivery_does_not_force_reviewer(self) -> None:
        item = work_item(
            "W-01",
            read_scope=["src/a.py", "src/b.py"],
            write_scope=["src/a.py", "src/b.py"],
            risk="medium",
        )
        team = resolve_team_plan(task_plan(items=[item], title="Ordinary feature"))
        self.assertEqual(profiles(team), ["execution-root"])

    def test_ordinary_single_stream_architecture_stays_with_root(self) -> None:
        item = work_item(
            "W-01",
            work_type="architecture",
            read_scope=["src/"],
            title="Choose an internal component boundary",
        )
        team = resolve_team_plan(task_plan(items=[item], title="Internal design decision"))
        self.assertEqual(profiles(team), ["execution-root"])

    def test_reviewer_is_added_only_for_quality_gate_signals(self) -> None:
        cases = (
            (
                task_plan(items=[work_item("W-01", work_type="review")]),
                {},
            ),
            (
                task_plan(items=[work_item("W-01")]),
                {"independent_review_required": True},
            ),
            (
                task_plan(items=[work_item("W-01", risk="high")]),
                {},
            ),
            (
                task_plan(items=[work_item("W-01", work_type="release")]),
                {},
            ),
            (
                task_plan(items=[work_item("W-01")], title="Security hardening"),
                {},
            ),
        )
        for plan, signals in cases:
            with self.subTest(title=plan["title"], signals=signals):
                team = resolve_team_plan(plan, signals=signals)
                self.assertIn("reviewer", profiles(team))

    def test_required_architect_and_reviewer_are_not_crowded_out_by_researchers(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                work_type="research",
                read_scope=[f"area-{index}/"],
                parallelizable=True,
            )
            for index in range(1, 5)
        ]
        items.append(
            work_item(
                "W-05",
                work_type="architecture",
                read_scope=["api/", "domain/"],
                title="Cross-module migration architecture",
            )
        )
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertIn("reviewer", selected)
        self.assertEqual(selected.count("codebase-researcher"), 2)
        self.assertLessEqual(len(team["positions"]), MAX_ACTIVE_POSITIONS)

    def test_required_cross_module_developer_is_not_crowded_out_by_researchers(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                work_type="research",
                read_scope=[f"area-{index}/"],
                parallelizable=True,
            )
            for index in range(1, 5)
        ]
        items.append(
            work_item(
                "W-05",
                work_type="integration",
                read_scope=["api/", "domain/", "persistence/"],
                write_scope=["api/handler.py", "domain/model.py", "persistence/store.py"],
                title="Cross-module interface migration",
                context_coupling="medium",
            )
        )
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertIn("developer", selected)
        self.assertIn("reviewer", selected)
        self.assertEqual(selected.count("codebase-researcher"), 1)
        self.assertLessEqual(len(team["positions"]), MAX_ACTIVE_POSITIONS)

    def test_parallel_cross_module_developers_do_not_crowd_out_reviewer(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                title=f"Cross-module implementation stream {index}",
                read_scope=[f"module-{index}/"],
                write_scope=[f"module-{index}/feature.py"],
                parallelizable=True,
                isolated_worktree_required=True,
                context_coupling="low",
            )
            for index in range(1, 5)
        ]
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        selected = profiles(team)
        self.assertIn("technical-architect", selected)
        self.assertIn("reviewer", selected)
        self.assertEqual(selected.count("developer"), 2)
        self.assertLessEqual(len(team["positions"]), MAX_ACTIVE_POSITIONS)

    def test_required_release_supervisor_is_not_crowded_out_by_researchers(self) -> None:
        items = [
            work_item(
                f"W-0{index}",
                work_type="research",
                read_scope=[f"area-{index}/"],
                parallelizable=True,
            )
            for index in range(1, 5)
        ]
        items.append(work_item("W-05", work_type="release", risk="critical"))
        selected = profiles(resolve_team_plan(task_plan(items=items, title="Release program")))
        self.assertIn("reviewer", selected)
        self.assertIn("supervisor", selected)

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
