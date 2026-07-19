from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import create_fixture_task, read_json, work_item


class ExecutionChecklistTests(unittest.TestCase):
    def test_plan_creation_writes_all_user_and_machine_artifacts_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, task_dir = create_fixture_task(project)
            expected = {
                "task-plan.json",
                "TASK_EXECUTION_CHECKLIST.md",
                "TEAM_PLAN.json",
                "TEAM_PLAN.md",
                "EXECUTION_LAUNCH_PROMPT.md",
                "PROGRESS.md",
                "progress.jsonl",
                "EVIDENCE.md",
            }
            self.assertEqual({path.name for path in task_dir.iterdir()}, expected)
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "plan_ready")
            self.assertEqual(read_json(task_dir / "TEAM_PLAN.json")["status"], "pending")
            self.assertEqual((task_dir / "progress.jsonl").read_text(encoding="utf-8"), "")

    def test_checklist_is_readable_and_preserves_dependency_order(self) -> None:
        items = [
            work_item("W-01", work_type="research", read_scope=["src/"]),
            work_item("W-02", dependencies=["W-01"], write_scope=["src/change.py"]),
        ]
        with tempfile.TemporaryDirectory() as raw:
            _, task_dir = create_fixture_task(Path(raw), items=items)
            checklist = (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")
            self.assertIn("## 完成标准", checklist)
            self.assertIn("### [ ] W-01", checklist)
            self.assertIn("### [ ] W-02", checklist)
            self.assertIn("依赖：W-01", checklist)
            self.assertIn("不会自动开始执行", checklist)
            self.assertNotIn("```yaml", checklist)

    def test_checklist_does_not_invent_time_or_percentage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, task_dir = create_fixture_task(Path(raw))
            text = (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8")
            self.assertNotIn("%", text)
            self.assertNotRegex(text, r"\b\d+\s*(?:hour|day|小时|天)\b")


if __name__ == "__main__":
    unittest.main()
