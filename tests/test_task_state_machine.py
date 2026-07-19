from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
from agency_task import (  # noqa: E402
    LEGAL_TRANSITIONS,
    create_task,
    list_active_tasks,
    transition_task,
    validate_task_plan,
    validate_transition,
)


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


if __name__ == "__main__":
    unittest.main()
