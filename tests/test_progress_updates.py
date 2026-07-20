from __future__ import annotations

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
            self.assertEqual(len(load_events(task_dir / "progress.jsonl")), 1)

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

    def test_task_completion_event_cannot_bypass_guarded_completion(self) -> None:
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
            update_progress(
                project,
                task_id=task_id,
                event_type="work_completed",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation completed",
                artifacts=["artifact.txt"],
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
            (task_dir / "progress.jsonl").symlink_to(outside)
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
            self.assertFalse((task_dir / "progress.jsonl").exists())

    def test_terminal_index_failure_rolls_back_completion_event(self) -> None:
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
            update_progress(
                project,
                task_id=task_id,
                event_type="work_completed",
                work_id="W-01",
                actor="execution-root",
                summary="Implementation completed",
                artifacts=["artifact.txt"],
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
