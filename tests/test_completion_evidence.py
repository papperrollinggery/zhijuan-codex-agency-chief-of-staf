from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_task_completion import completion_args, executing_fixture, managed_snapshot
from lifecycle_test_support import read_json

from agency_task import transition_task
from complete_task import complete_task
from update_task_progress import update_progress
from validate_task_archive import validate_archive_readiness


class CompletionEvidenceTests(unittest.TestCase):
    def test_retry_can_reuse_same_progress_command_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            common = {"task_id": task_id, "work_id": "W-01", "actor": "execution-root"}
            update_progress(
                project, **common, event_type="verification_failed",
                summary="Failure found", blockers=["retry needed"],
            )
            started = update_progress(project, **common, event_type="work_started", summary="Implementation started")
            self.assertEqual(started["status"], "recorded")
            self.assertEqual(read_json(task_dir / "task-plan.json")["work_items"][0]["status"], "in_progress")
            (project / "artifact.txt").write_text("repaired\n", encoding="utf-8")
            done = update_progress(
                project, **common, event_type="work_completed", summary="Implementation completed",
                artifacts=["artifact.txt"], verification=["unit test exit 0"],
            )
            self.assertEqual(done["status"], "recorded")
            self.assertEqual(complete_task(project, task_id=task_id, apply=True, **completion_args())["status_after"], "completed")

    def test_failed_final_verification_can_repair_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            transition_task(project, task_id, "verifying")
            common = {"task_id": task_id, "work_id": "W-01", "actor": "execution-root"}
            update_progress(
                project, **common, event_type="verification_failed",
                summary="Integration exposed a defect", blockers=["wrong edge case"],
            )
            with self.assertRaisesRegex(ValueError, "required work remains open"):
                complete_task(project, task_id=task_id, apply=True, **completion_args())
            update_progress(project, **common, event_type="work_started", summary="Repair edge case")
            (project / "artifact.txt").write_text("repaired\n", encoding="utf-8")
            update_progress(
                project, **common, event_type="work_completed", summary="Repair verified",
                artifacts=["artifact.txt"], verification=["integration exit 0 after repair"],
            )
            with self.assertRaisesRegex(ValueError, "recorded verification"):
                complete_task(project, task_id=task_id, apply=True, **completion_args())
            args = completion_args()
            args["acceptance_evidence"] = {"The fixture has current evidence": ["integration exit 0 after repair"]}
            args["validation_results"][0]["evidence_refs"] = ["integration exit 0 after repair"]
            result = complete_task(project, task_id=task_id, apply=True, **args)
            self.assertEqual(result["status_after"], "completed")

    def test_unrecorded_validation_cannot_complete_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            before = managed_snapshot(project, task_dir)
            args = completion_args()
            args["validation_results"][0]["evidence_refs"] = ["invented PASS"]
            with self.assertRaisesRegex(ValueError, "recorded verification"):
                complete_task(project, task_id=task_id, apply=True, **args)
            self.assertEqual(managed_snapshot(project, task_dir), before)

    def test_unrecorded_acceptance_cannot_complete_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project)
            args = completion_args()
            args["acceptance_evidence"] = {"The fixture has current evidence": ["invented PASS"]}
            with self.assertRaisesRegex(ValueError, "recorded work evidence"):
                complete_task(project, task_id=task_id, apply=False, **args)

    def test_completed_flags_without_progress_are_not_execution_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            (task_dir / "progress.jsonl").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "work completion evidence"):
                complete_task(project, task_id=task_id, apply=True, **completion_args())

    def test_unrelated_existing_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project)
            (project / "unrelated.txt").write_text("PASS\n", encoding="utf-8")
            args = {**completion_args(), "artifacts": ["unrelated.txt"]}
            with self.assertRaisesRegex(ValueError, "artifact verification"):
                complete_task(project, task_id=task_id, apply=True, **args)

    def test_artifact_changed_since_work_verification_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            (project / "artifact.txt").write_text("changed after verification\n", encoding="utf-8")
            before = managed_snapshot(project, task_dir)
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                complete_task(project, task_id=task_id, apply=True, **completion_args())
            self.assertEqual(managed_snapshot(project, task_dir), before)

    def test_archive_cannot_reuse_completion_after_artifact_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = executing_fixture(project)
            complete_task(project, task_id=task_id, apply=True, **completion_args())
            closure = read_json(task_dir / "closure.json")
            self.assertIn("artifact_snapshots", closure)
            (project / "artifact.txt").write_text("changed after completion\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                validate_archive_readiness(project, task_dir, closure)

    def test_directory_is_not_a_completed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = executing_fixture(project)
            (project / "empty-output").mkdir()
            with self.assertRaisesRegex(ValueError, "regular file"):
                complete_task(
                    project, task_id=task_id, apply=True,
                    **{**completion_args(), "artifacts": ["empty-output"]},
                )


if __name__ == "__main__":
    unittest.main()
