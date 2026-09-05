from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
import resolve_team_plan as team_plan_module  # noqa: E402
from resolve_team_plan import (  # noqa: E402
    ACCOUNTABLE_PROFILE_BY_WORK_TYPE,
    MAX_ACTIVE_POSITIONS,
    MAX_PARALLEL_POSITIONS,
    MAX_PARALLEL_WRITERS,
    PROFILE_TITLES,
    resolve_team_plan,
    write_team_plan,
)


def profiles(team: dict[str, object]) -> list[str]:
    return [position["profile"] for position in team["positions"]]  # type: ignore[index]


class TeamPlannerTests(unittest.TestCase):
    def test_release_execution_is_not_owned_by_readonly_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, task_dir = create_fixture_task(
                project, items=[work_item("W-01", work_type="release", write_scope=["dist/"])],
            )
            plan = json.loads((task_dir / "task-plan.json").read_text())
            team = resolve_team_plan(plan)
            self.assertIn("supervisor", profiles(team))
            self.assertIn("reviewer", profiles(team))
            self.assertIn("W-01", team["root_owned_work_items"])
            observer_waves = [
                wave
                for wave in team["waves"]
                if any(
                    position["profile"] in {"reviewer", "supervisor"}
                    and position["position_id"] in wave["pending_root_dependency_position_ids"]
                    for position in team["positions"]
                )
            ]
            self.assertEqual(len(observer_waves), 2)
            self.assertTrue(
                all("W-01" in wave["root_owned_dependency_work_ids"] for wave in observer_waves)
            )
            write_team_plan(task_dir, team)
            written = json.loads((task_dir / "task-plan.json").read_text())
            self.assertIsNone(written["work_items"][0]["profile"])

    def test_runtime_profile_sets_stay_consistent_across_planner_and_policies(self) -> None:
        routing = json.loads(
            (ROOT / "assets/agent-routing.json").read_text(encoding="utf-8")
        )
        role_policy = json.loads(
            (ROOT / "assets/role-model-policy.json").read_text(encoding="utf-8")
        )
        planner_profiles = set(PROFILE_TITLES) - {"execution-root"}
        self.assertEqual(planner_profiles, set(routing["profiles"]))
        self.assertEqual(planner_profiles, set(role_policy["profiles"]))
        self.assertTrue(
            set(ACCOUNTABLE_PROFILE_BY_WORK_TYPE.values()) <= planner_profiles
        )

    def test_team_plan_writer_rejects_an_unmanaged_task_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            task_dir = Path(raw) / "task-unmanaged-001"
            task_dir.mkdir()
            plan = task_plan(task_id="task-unmanaged-001")
            (task_dir / "task-plan.json").write_text(
                json.dumps(plan, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "managed active task directory"):
                write_team_plan(task_dir, resolve_team_plan(plan))

    def test_team_plan_second_and_third_write_failures_restore_exact_files(self) -> None:
        for failing_name in ("TEAM_PLAN.json", "TEAM_PLAN.md"):
            with self.subTest(failing_name=failing_name), tempfile.TemporaryDirectory() as raw:
                project = Path(raw)
                task_id, task_dir = create_fixture_task(
                    project, f"task-team-rollback-{failing_name.lower().replace('.', '-')}-001"
                )
                plan = json.loads((task_dir / "task-plan.json").read_text(encoding="utf-8"))
                team = resolve_team_plan(plan)
                paths = (
                    task_dir / "task-plan.json",
                    task_dir / "TEAM_PLAN.json",
                    task_dir / "TEAM_PLAN.md",
                )
                before = {path.name: path.read_bytes() for path in paths}
                failed = False
                real_json = team_plan_module.atomic_write_json
                real_text = team_plan_module.atomic_write_text

                def maybe_fail_json(path: Path, value: object) -> None:
                    nonlocal failed
                    if Path(path).name == failing_name and not failed:
                        failed = True
                        raise OSError("team json write failed")
                    real_json(path, value)

                def maybe_fail_text(path: Path, value: str) -> None:
                    nonlocal failed
                    if Path(path).name == failing_name and not failed:
                        failed = True
                        raise OSError("team markdown write failed")
                    real_text(path, value)

                with mock.patch.object(
                    team_plan_module,
                    "atomic_write_json",
                    side_effect=maybe_fail_json,
                ), mock.patch.object(
                    team_plan_module,
                    "atomic_write_text",
                    side_effect=maybe_fail_text,
                ):
                    with self.assertRaisesRegex(OSError, "team .* write failed"):
                        write_team_plan(task_dir, team)
                self.assertTrue(failed)
                self.assertEqual(
                    {path.name: path.read_bytes() for path in paths}, before
                )

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

    def test_dependent_research_is_not_dispatched_as_parallel_positions(self) -> None:
        items = [
            work_item(
                "W-01",
                work_type="research",
                read_scope=["api/"],
                parallelizable=True,
                context_coupling="low",
            ),
            work_item(
                "W-02",
                work_type="research",
                read_scope=["domain/"],
                dependencies=["W-01"],
                parallelizable=True,
                context_coupling="low",
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Dependent research"))
        research = [p for p in team["positions"] if p["profile"] == "codebase-researcher"]
        self.assertEqual(len(research), 1)
        self.assertEqual(research[0]["work_items"], ["W-01", "W-02"])

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

    def test_shared_completed_prerequisite_allows_parallel_implementation_streams(self) -> None:
        items = [
            work_item("W-01", work_type="architecture", read_scope=["api/"]),
            work_item(
                "W-02",
                read_scope=["client/"],
                write_scope=["client/feature.py"],
                dependencies=["W-01"],
                parallelizable=True,
                isolated_worktree_required=True,
                context_coupling="low",
            ),
            work_item(
                "W-03",
                read_scope=["server/"],
                write_scope=["server/feature.py"],
                dependencies=["W-01"],
                parallelizable=True,
                isolated_worktree_required=True,
                context_coupling="low",
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        developers = [p for p in team["positions"] if p["profile"] == "developer"]
        self.assertEqual(len(developers), 2)
        wave_two = next(wave for wave in team["waves"] if wave["wave"] == 2)
        self.assertEqual(
            set(wave_two["parallel_position_ids"]),
            {developer["position_id"] for developer in developers},
        )

    def test_dependent_implementation_is_not_dispatched_in_parallel(self) -> None:
        items = [
            work_item(
                "W-01",
                read_scope=["src/a.py"],
                write_scope=["src/a.py"],
                parallelizable=True,
                isolated_worktree_required=True,
                context_coupling="low",
            ),
            work_item(
                "W-02",
                read_scope=["src/b.py"],
                write_scope=["src/b.py"],
                dependencies=["W-01"],
                parallelizable=True,
                isolated_worktree_required=True,
                context_coupling="low",
            ),
        ]
        team = resolve_team_plan(
            task_plan(items=items, title="Dependent implementation"),
            signals={"explicit_delegate_implementation": True},
        )
        developers = [p for p in team["positions"] if p["profile"] == "developer"]
        self.assertEqual(len(developers), 1)
        self.assertEqual(developers[0]["work_items"], ["W-01", "W-02"])
        wave_two = next(wave for wave in team["waves"] if wave["wave"] == 2)
        self.assertEqual(wave_two["parallel_position_ids"], [developers[0]["position_id"]])

    def test_position_wave_waits_for_another_selected_position_dependency(self) -> None:
        items = [
            work_item(
                "W-01",
                work_type="research",
                read_scope=["api/"],
                parallelizable=True,
                context_coupling="low",
            ),
            work_item(
                "W-02",
                work_type="research",
                read_scope=["domain/"],
                parallelizable=True,
                context_coupling="low",
            ),
            work_item(
                "W-03",
                work_type="architecture",
                read_scope=["api/", "domain/"],
                dependencies=["W-01"],
                title="Cross-module architecture",
            ),
        ]
        team = resolve_team_plan(task_plan(items=items, title="Cross-module migration"))
        researcher = next(
            p
            for p in team["positions"]
            if p["profile"] == "codebase-researcher" and p["work_items"] == ["W-01"]
        )
        architect = next(p for p in team["positions"] if p["profile"] == "technical-architect")
        architect_wave = next(
            wave for wave in team["waves"] if architect["position_id"] in wave["parallel_position_ids"]
        )
        self.assertGreater(architect_wave["wave"], 1)
        self.assertEqual(architect["wave"], architect_wave["wave"])
        self.assertIn(researcher["position_id"], architect_wave["blocked_by_position_ids"])

    def test_interleaved_same_profile_dependencies_split_into_executable_waves(self) -> None:
        items = [
            work_item(
                "W-01",
                work_type="writing",
                read_scope=["docs/"],
                write_scope=["docs/intro.md"],
            ),
            work_item(
                "W-02",
                work_type="implementation",
                read_scope=["src/"],
                write_scope=["src/feature.py"],
                dependencies=["W-01"],
            ),
            work_item(
                "W-03",
                work_type="writing",
                read_scope=["docs/"],
                write_scope=["docs/reference.md"],
                dependencies=["W-02"],
            ),
        ]
        team = resolve_team_plan(
            task_plan(items=items, title="Documented implementation"),
            signals={"explicit_delegate_implementation": True},
        )
        writers = [p for p in team["positions"] if p["profile"] == "writer"]
        developer = next(p for p in team["positions"] if p["profile"] == "developer")
        self.assertEqual([p["work_items"] for p in writers], [["W-01"], ["W-03"]])
        self.assertEqual(developer["work_items"], ["W-02"])
        self.assertEqual([p["wave"] for p in writers], [2, 4])
        self.assertEqual(developer["wave"], 3)

    def test_root_owned_prerequisite_is_not_listed_as_ready_parallel_work(self) -> None:
        items = [
            work_item("W-01", work_type="research", read_scope=["src/"]),
            work_item(
                "W-02",
                read_scope=["src/"],
                write_scope=["src/feature.py"],
                dependencies=["W-01"],
            ),
        ]
        team = resolve_team_plan(
            task_plan(items=items, title="Root prerequisite"),
            signals={"explicit_delegate_implementation": True},
        )
        developer = next(p for p in team["positions"] if p["profile"] == "developer")
        wave = next(wave for wave in team["waves"] if wave["wave"] == developer["wave"])
        self.assertIn(developer["position_id"], wave["pending_root_dependency_position_ids"])
        self.assertNotIn(developer["position_id"], wave["parallel_position_ids"])

    def test_review_work_is_accountable_to_the_reviewer(self) -> None:
        item = work_item("W-01", work_type="review", read_scope=["src/"])
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, task_dir = create_fixture_task(project, items=[item])
            team = resolve_team_plan(json.loads((task_dir / "task-plan.json").read_text(encoding="utf-8")))
            write_team_plan(task_dir, team)
            assigned = json.loads((task_dir / "task-plan.json").read_text(encoding="utf-8"))["work_items"][0]
            self.assertEqual(assigned["profile"], "reviewer")
            self.assertEqual(assigned["review_profile"], "reviewer")
            self.assertNotIn("W-01", team["root_owned_work_items"])

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

    def test_reviewer_waits_for_root_owned_high_risk_implementation(self) -> None:
        item = work_item("W-01", risk="high", context_coupling="high")
        team = resolve_team_plan(task_plan(items=[item], title="High risk root change"))
        reviewer = next(p for p in team["positions"] if p["profile"] == "reviewer")
        wave = next(wave for wave in team["waves"] if wave["wave"] == reviewer["wave"])
        self.assertIn(reviewer["position_id"], wave["pending_root_dependency_position_ids"])
        self.assertNotIn(reviewer["position_id"], wave["parallel_position_ids"])

    def test_satisfied_root_owned_work_does_not_keep_reviewer_pending(self) -> None:
        for status in ("completed", "waived"):
            with self.subTest(status=status):
                item = work_item("W-01", risk="high", context_coupling="high")
                item["status"] = status
                if status == "waived":
                    item["waiver_reason"] = "Accepted fixture waiver"
                team = resolve_team_plan(
                    task_plan(items=[item], title="Reviewed satisfied root change")
                )
                reviewer = next(p for p in team["positions"] if p["profile"] == "reviewer")
                wave = next(wave for wave in team["waves"] if wave["wave"] == reviewer["wave"])
                self.assertNotIn(reviewer["position_id"], wave["pending_root_dependency_position_ids"])
                self.assertIn(reviewer["position_id"], wave["parallel_position_ids"])

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
