from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, read_json

sys.path.insert(0, str(ROOT / "scripts"))
from agency_task import atomic_write_json, transition_task  # noqa: E402
from complete_task import complete_task  # noqa: E402
import complete_task as complete_task_module  # noqa: E402
from update_task_progress import update_progress  # noqa: E402


def executing_fixture(project: Path, *, reviewer: bool = False) -> tuple[str, Path]:
    task_id, task_dir = create_fixture_task(project)
    transition_task(project, task_id, "execution_ready")
    transition_task(project, task_id, "executing")
    update_progress(
        project,
        task_id=task_id,
        event_type="work_started",
        work_id="W-01",
        actor="execution-root",
        summary="Implementation started",
    )
    (project / "artifact.txt").write_text("verified\n", encoding="utf-8")
    update_progress(
        project,
        task_id=task_id,
        event_type="work_completed",
        work_id="W-01",
        actor="execution-root",
        summary="Implementation completed",
        artifacts=["artifact.txt"],
        verification=["unit test exit 0"],
    )
    if reviewer:
        atomic_write_json(
            task_dir / "TEAM_PLAN.json",
            {"positions": [{"profile": "execution-root"}, {"profile": "reviewer"}]},
        )
    return task_id, task_dir


def completion_args() -> dict[str, object]:
    return {
        "acceptance_evidence": {"The fixture has current evidence": ["unit test exit 0"]},
        "validation_results": [
            {
                "status": "passed",
                "summary": "unit tests passed",
                "evidence_refs": ["unit test exit 0"],
            }
        ],
        "artifacts": ["artifact.txt"],
    }


def managed_snapshot(project: Path, task_dir: Path) -> dict[str, str | None]:
    project = project.resolve()
    paths = (
        task_dir / "task-plan.json",
        task_dir / "TASK_EXECUTION_CHECKLIST.md",
        project / ".agency/task-index.json",
        task_dir / "progress.jsonl",
        task_dir / "PROGRESS.md",
        task_dir / "closure.json",
    )
    return {
        str(path.relative_to(project)): (
            path.read_text(encoding="utf-8") if path.exists() else None
        )
        for path in paths
    }


class TaskCompletionTests(unittest.TestCase):
    def test_check_only_does_not_mutate_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            result = complete_task(project, task_id=task_id, apply=False, **completion_args())
            self.assertEqual(result["status"], "would-complete")
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "executing")
            self.assertFalse((task_dir / "closure.json").exists())

    def test_apply_completes_and_writes_reusable_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            result = complete_task(project, task_id=task_id, apply=True, **completion_args())
            self.assertEqual(result["status_after"], "completed")
            plan = read_json(task_dir / "task-plan.json")
            self.assertEqual(plan["status"], "completed")
            self.assertEqual(
                plan["acceptance_evidence"]["The fixture has current evidence"],
                ["unit test exit 0"],
            )
            self.assertTrue((task_dir / "closure.json").is_file())
            self.assertTrue((task_dir / "PROGRESS.md").is_file())
            repeated = complete_task(
                project, task_id=task_id, apply=True, **completion_args()
            )
            self.assertEqual(repeated["status_after"], "completed")
            self.assertIsNone(repeated["progress_event"])

    def test_missing_acceptance_mapping_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project)
            args = completion_args()
            args["acceptance_evidence"] = {}
            with self.assertRaisesRegex(ValueError, "does not match criteria"):
                complete_task(project, task_id=task_id, apply=True, **args)

    def test_selected_reviewer_requires_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project, reviewer=True)
            with self.assertRaisesRegex(ValueError, "Reviewer"):
                complete_task(project, task_id=task_id, apply=False, **completion_args())
            result = complete_task(
                project,
                task_id=task_id,
                review_evidence=["review PASS at current diff"],
                apply=True,
                **completion_args(),
            )
            self.assertEqual(result["review_status"], "handled")

    def test_high_risk_task_requires_review_even_without_team_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["work_items"][0]["risk"] = "high"
            atomic_write_json(task_dir / "task-plan.json", plan)
            with self.assertRaisesRegex(ValueError, "Reviewer"):
                complete_task(project, task_id=task_id, apply=False, **completion_args())

    def test_completed_task_rejects_closure_evidence_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project)
            complete_task(project, task_id=task_id, apply=True, **completion_args())
            changed = completion_args()
            changed["validation_results"] = [
                {
                    "status": "passed",
                    "summary": "different evidence",
                    "evidence_refs": ["different test exit 0"],
                }
            ]
            with self.assertRaisesRegex(ValueError, "closure does not match"):
                complete_task(project, task_id=task_id, apply=True, **changed)

    def test_native_task_requires_cleanup_readback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            atomic_write_json(task_dir / "execution-session.json", {"native_task_id": "task-real"})
            with self.assertRaisesRegex(ValueError, "closed or cleanup_blocked"):
                complete_task(project, task_id=task_id, apply=False, **completion_args())
            result = complete_task(
                project,
                task_id=task_id,
                cleanup_status="closed",
                cleanup_evidence=["native task readback closed"],
                apply=False,
                **completion_args(),
            )
            self.assertEqual(result["cleanup_status"], "closed")

    def test_native_closed_status_requires_readback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            atomic_write_json(task_dir / "execution-session.json", {"native_task_id": "task-real"})
            with self.assertRaisesRegex(ValueError, "readback evidence"):
                complete_task(
                    project,
                    task_id=task_id,
                    cleanup_status="closed",
                    apply=False,
                    **completion_args(),
                )

    def test_closure_write_failure_restores_every_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            before = managed_snapshot(project, task_dir)
            real_write = complete_task_module.atomic_write_json

            def fail_closure(path: Path, value: object) -> None:
                if Path(path).name == "closure.json":
                    raise OSError("closure write failed")
                real_write(path, value)

            with mock.patch.object(
                complete_task_module, "atomic_write_json", side_effect=fail_closure
            ):
                with self.assertRaisesRegex(OSError, "closure write failed"):
                    complete_task(
                        project, task_id=task_id, apply=True, **completion_args()
                    )
            self.assertEqual(managed_snapshot(project, task_dir), before)

    def test_transition_failure_restores_acceptance_evidence_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            before = managed_snapshot(project, task_dir)
            with mock.patch.object(
                complete_task_module,
                "transition_task",
                side_effect=OSError("transition failed"),
            ):
                with self.assertRaisesRegex(OSError, "transition failed"):
                    complete_task(
                        project, task_id=task_id, apply=True, **completion_args()
                    )
            self.assertEqual(managed_snapshot(project, task_dir), before)

    def test_terminal_progress_failure_removes_prepared_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            before = managed_snapshot(project, task_dir)
            with mock.patch.object(
                complete_task_module,
                "record_terminal_progress",
                side_effect=OSError("terminal progress failed"),
            ):
                with self.assertRaisesRegex(OSError, "terminal progress failed"):
                    complete_task(
                        project, task_id=task_id, apply=True, **completion_args()
                    )
            self.assertEqual(managed_snapshot(project, task_dir), before)


if __name__ == "__main__":
    unittest.main()
