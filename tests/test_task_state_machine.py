from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
from agency_task import (  # noqa: E402
    LEGAL_TRANSITIONS,
    create_task,
    list_active_tasks,
    load_json,
    transition_task,
    validate_task_plan,
    validate_transition,
)
import agency_task as agency_task_module  # noqa: E402


class TaskStateMachineTests(unittest.TestCase):
    def test_every_declared_transition_is_accepted(self) -> None:
        for before, afters in LEGAL_TRANSITIONS.items():
            for after in afters:
                validate_transition(before, after)

    def test_forbidden_shortcuts_are_rejected(self) -> None:
        for before, after in (
            ("discussion", "archived"),
            ("plan_ready", "completed"),
            ("executing", "completed"),
        ):
            with self.assertRaisesRegex(ValueError, "illegal task transition"):
                validate_transition(before, after)

    def test_generated_task_ids_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            first = task_plan()
            second = task_plan()
            first.pop("task_id")
            second.pop("task_id")
            one = create_task(project, first)["task_id"]
            two = create_task(project, second)["task_id"]
            self.assertNotEqual(one, two)

    def test_dependency_cycle_is_rejected(self) -> None:
        items = [
            work_item("W-01", dependencies=["W-02"]),
            work_item("W-02", dependencies=["W-01"]),
        ]
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            validate_task_plan(task_plan(items=items))

    def test_superseded_task_is_removed_from_active_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            old_id, _ = create_fixture_task(project, "task-old-001")
            new_id, _ = create_fixture_task(project, "task-new-001")
            result = transition_task(
                project,
                old_id,
                "superseded",
                reason="Replaced by a corrected scope",
                superseded_by=new_id,
            )
            self.assertFalse(result["active"])
            self.assertNotIn(old_id, {item["task_id"] for item in list_active_tasks(project)})

    def test_public_transition_cannot_bypass_completion_or_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-guarded-001")
            transition_task(project, task_id, "execution_ready")
            transition_task(project, task_id, "executing")
            transition_task(project, task_id, "verifying")
            with self.assertRaisesRegex(ValueError, "complete_task.py"):
                transition_task(project, task_id, "completed")
            plan = validate_task_plan(load_json(task_dir / "task-plan.json"))
            self.assertEqual(plan["status"], "verifying")

    def test_agency_root_symlink_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (project / ".agency").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                create_task(project, task_plan(task_id="task-symlink-001"))
            self.assertEqual(list(outside.iterdir()), [])

    def test_create_rolls_back_directory_when_index_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            with mock.patch.object(
                agency_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    create_task(project, task_plan(task_id="task-create-failure-001"))
            self.assertFalse(
                (project / ".agency/tasks/active/task-create-failure-001").exists()
            )
            self.assertFalse((project / ".agency/task-index.json").exists())

    def test_transition_rolls_back_plan_and_checklist_when_index_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-transition-failure-001")
            checklist_before = (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(
                encoding="utf-8"
            )
            with mock.patch.object(
                agency_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    transition_task(project, task_id, "execution_ready")
            self.assertEqual(load_json(task_dir / "task-plan.json")["status"], "plan_ready")
            self.assertEqual(
                (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8"),
                checklist_before,
            )
            index = load_json(project / ".agency/task-index.json")
            self.assertEqual(index["tasks"][task_id]["status"], "plan_ready")


if __name__ == "__main__":
    unittest.main()
