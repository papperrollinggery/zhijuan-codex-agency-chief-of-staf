from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, read_json

sys.path.insert(0, str(ROOT / "scripts"))
from agency_task import transition_task  # noqa: E402
from update_task_progress import load_events, update_progress  # noqa: E402


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

    def test_task_completion_requires_verification_and_acceptance_evidence(self) -> None:
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
            with self.assertRaisesRegex(ValueError, "evidence"):
                update_progress(
                    project,
                    task_id=task_id,
                    event_type="task_completed",
                    work_id=None,
                    actor="execution-root",
                    summary="Task completed",
                )
            plan = read_json(task_dir / "task-plan.json")
            plan["acceptance_evidence"] = {
                plan["acceptance_criteria"][0]: ["test exit 0"]
            }
            from agency_task import atomic_write_json

            atomic_write_json(task_dir / "task-plan.json", plan)
            result = update_progress(
                project,
                task_id=task_id,
                event_type="task_completed",
                work_id=None,
                actor="execution-root",
                summary="Task completed",
                verification=["test exit 0"],
            )
            self.assertEqual(result["status_after"], "completed")
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
