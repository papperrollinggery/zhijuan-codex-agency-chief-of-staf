from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, read_json

sys.path.insert(0, str(ROOT / "scripts"))
import agency_task as agency_task_module  # noqa: E402
import update_task_progress as progress_module  # noqa: E402
from agency_task import atomic_write_json, transition_task  # noqa: E402
from update_task_progress import (  # noqa: E402
    load_events,
    record_terminal_progress,
    update_progress,
)


class ProgressUpdateTests(unittest.TestCase):
    def executing_task(self, project: Path) -> tuple[str, Path]:
        task_id, task_dir = create_fixture_task(project, "task-progress-001")
        transition_task(project, task_id, "execution_ready")
        transition_task(project, task_id, "executing")
        return task_id, task_dir

    def test_progress_is_event_driven_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            kwargs = {
                "task_id": task_id,
                "event_type": "work_started",
                "work_id": "W-01",
                "actor": "execution-root",
                "summary": "Implementation started",
                "idempotency_key": "start-w01",
            }
            first = update_progress(project, **kwargs)
            second = update_progress(project, **kwargs)
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "duplicate")
            events = load_events(task_dir / "progress.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "work_started")

    def test_historical_event_without_event_type_or_snapshots_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, task_dir = self.executing_task(project)
            legacy = {
                "event_id": "evt-legacy",
                "task_id": "task-progress-001",
                "work_id": "W-01",
                "timestamp": "2026-01-01T00:00:00Z",
                "actor": "execution-root",
                "status_before": "pending",
                "status_after": "in_progress",
                "summary": "Legacy work started",
                "artifacts": [],
                "verification": [],
                "blockers": [],
            }
            (task_dir / "progress.jsonl").write_text(
                json.dumps(legacy) + "\n", encoding="utf-8"
            )
            self.assertEqual(load_events(task_dir / "progress.jsonl"), [legacy])

    def test_cli_argv_preserves_untrusted_summary_without_shell_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            marker = project / "must-not-exist"
            payload = f"x'; touch {marker}; : ' && echo compromised"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/update_task_progress.py"),
                    "--project",
                    str(project),
                    "--task-id",
                    task_id,
                    "--event-type",
                    "work_started",
                    "--work-id",
                    "W-01",
                    "--summary",
                    payload,
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(
                load_events(task_dir / "progress.jsonl")[0]["summary"], payload
            )

    def test_subagent_cannot_update_global_task_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = self.executing_task(project)
            with self.assertRaisesRegex(ValueError, "Execution Root"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="work_started",
                    work_id="W-01",
                    actor="developer",
                    summary="Subagent attempted a global update",
                )

    def test_review_returned_resume_evidence_lives_in_canonical_log(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            update_progress(
                project,
                task_id=task_id,
                event_type="review_returned",
                work_id=None,
                actor="execution-root",
                summary="Independent review returned PASS",
                verification=["reviewer task current-diff PASS"],
            )
            plan_text = (task_dir / "task-plan.json").read_text(encoding="utf-8")
            events = load_events(task_dir / "progress.jsonl")
            self.assertNotIn("reviewer task current-diff PASS", plan_text)
            self.assertEqual(events[-1]["status_before"], "executing")
            self.assertEqual(events[-1]["status_after"], "executing")
            self.assertEqual(
                events[-1]["verification"], ["reviewer task current-diff PASS"]
            )

    def test_progress_markdown_is_current_state_first_without_percentage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation started",
            )
            text = (task_dir / "PROGRESS.md").read_text(encoding="utf-8")
            for heading in ("当前阶段", "已完成", "正在进行", "被阻塞", "下一步", "验证状态"):
                self.assertIn(heading, text)
            self.assertNotIn("%", text)

    def test_work_completed_requires_verification_and_records_artifact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            artifact = project / "artifact.txt"
            artifact.write_text("verified\n", encoding="utf-8")
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation started",
            )
            with self.assertRaisesRegex(ValueError, "requires verification"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="work_completed",
                    work_id="W-01",
                    actor="execution-root",
                    summary="Implementation completed",
                )
            with self.assertRaisesRegex(ValueError, "cannot include blockers"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="work_completed",
                    work_id="W-01",
                    actor="execution-root",
                    summary="Implementation completed",
                    verification=["unit test exit 0"],
                    blockers=["stale blocker"],
                )
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
            event = load_events(task_dir / "progress.jsonl")[-1]
            self.assertEqual(event["event_type"], "work_completed")
            self.assertEqual(
                event["artifact_snapshots"]["artifact.txt"]["bytes"], len("verified\n")
            )
            self.assertRegex(event["artifact_snapshots"]["artifact.txt"]["sha256"], r"^[0-9a-f]{64}$")

    def test_verification_failure_blocks_work_and_discards_prior_evidence_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            (project / "verification.txt").write_text("test output\n", encoding="utf-8")
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation started",
            )
            update_progress(
                project,
                task_id=task_id,
                event_type="verification_completed",
                work_id="W-01",
                actor="execution-root",
                summary="Focused test passed before later failure",
                artifacts=["verification.txt"],
                verification=["focused test exit 0"],
            )
            verification_event = load_events(task_dir / "progress.jsonl")[-1]
            self.assertEqual(
                verification_event["artifact_snapshots"]["verification.txt"]["bytes"],
                len("test output\n"),
            )
            update_progress(
                project,
                task_id=task_id,
                event_type="verification_failed",
                work_id="W-01",
                actor="execution-root",
                summary="Integration test failed",
                blockers=["integration test exit 1"],
            )
            item = read_json(task_dir / "task-plan.json")["work_items"][0]
            self.assertEqual(item["status"], "blocked")
            self.assertEqual(item["evidence_refs"], [])
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation retry started",
            )
            retried = read_json(task_dir / "task-plan.json")["work_items"][0]
            self.assertEqual(retried["status"], "in_progress")
            self.assertEqual(retried["blockers"], [])

    def test_work_mutation_requires_executing_state_but_duplicate_retry_survives(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = create_fixture_task(project, "task-progress-nonexecuting-001")
            with self.assertRaisesRegex(ValueError, "executing"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="work_started",
                    work_id="W-01",
                    actor="execution-root",
                    summary="Must not start at plan ready",
                )

            transition_task(project, task_id, "execution_ready")
            transition_task(project, task_id, "executing")
            kwargs = {
                "task_id": task_id,
                "event_type": "work_started",
                "work_id": "W-01",
                "actor": "execution-root",
                "summary": "Started once",
                "idempotency_key": "start-once",
            }
            update_progress(project, **kwargs)
            transition_task(project, task_id, "verifying")
            duplicate = update_progress(project, **kwargs)
            self.assertEqual(duplicate["status"], "duplicate")
            with self.assertRaisesRegex(ValueError, "executing"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="artifact_generated",
                    work_id="W-01",
                    actor="execution-root",
                    summary="Must not mutate while verifying",
                )

    def test_task_completion_event_cannot_bypass_guarded_completion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            (project / "artifact.txt").write_text("verified\n", encoding="utf-8")
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation started",
            )
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
            transition_task(project, task_id, "verifying")
            with self.assertRaisesRegex(ValueError, "terminal task events are guarded"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="task_completed",
                    work_id=None,
                    actor="execution-root",
                    summary="Task completed",
                )
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "verifying")

    def test_progress_log_symlink_is_rejected_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            project.mkdir()
            task_id, task_dir = self.executing_task(project)
            outside = base / "outside.jsonl"
            outside.write_text("SENTINEL\n", encoding="utf-8")
            progress_path = task_dir / "progress.jsonl"
            progress_path.unlink()
            progress_path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="work_started",
                    work_id="W-01",
                    actor="execution-root",
                    summary="Implementation started",
                )
            self.assertEqual(outside.read_text(encoding="utf-8"), "SENTINEL\n")

    def test_event_append_failure_rolls_back_work_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            with mock.patch.object(
                progress_module, "append_event", side_effect=OSError("log full")
            ):
                with self.assertRaisesRegex(OSError, "log full"):
                    update_progress(
                        project,
                        task_id=task_id,
                        event_type="work_started",
                        work_id="W-01",
                        actor="execution-root",
                        summary="Implementation started",
                    )
            self.assertEqual(
                read_json(task_dir / "task-plan.json")["work_items"][0]["status"],
                "pending",
            )
            self.assertEqual((task_dir / "progress.jsonl").read_text(encoding="utf-8"), "")

    def test_terminal_index_failure_rolls_back_completion_event(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = self.executing_task(project)
            (project / "artifact.txt").write_text("verified\n", encoding="utf-8")
            update_progress(
                project,
                task_id=task_id,
                event_type="work_started",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation started",
            )
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
            plan = read_json(task_dir / "task-plan.json")
            plan["acceptance_evidence"] = {
                criterion: ["test exit 0"] for criterion in plan["acceptance_criteria"]
            }
            atomic_write_json(task_dir / "task-plan.json", plan)
            transition_task(project, task_id, "verifying")
            events_before = load_events(task_dir / "progress.jsonl")

            with mock.patch.object(
                agency_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    record_terminal_progress(
                        project,
                        task_id=task_id,
                        event_type="task_completed",
                        actor="execution-root",
                        summary="Task completed",
                        verification=["test exit 0"],
                    )

            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "verifying")
            self.assertEqual(load_events(task_dir / "progress.jsonl"), events_before)
            index = read_json(project / ".agency/task-index.json")
            self.assertEqual(index["tasks"][task_id]["status"], "verifying")


if __name__ == "__main__":
    unittest.main()
