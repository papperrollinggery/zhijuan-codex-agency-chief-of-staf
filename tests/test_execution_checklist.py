from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import create_fixture_task, read_json, task_plan, work_item

from agency_task import create_task, validate_task_plan


class ExecutionChecklistTests(unittest.TestCase):
    def test_plan_creation_lazily_writes_only_plan_and_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, task_dir = create_fixture_task(project)
            expected = {"task-plan.json", "TASK_EXECUTION_CHECKLIST.md"}
            self.assertEqual({path.name for path in task_dir.iterdir()}, expected)
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "plan_ready")
            index = read_json(project / ".agency" / "task-index.json")
            self.assertEqual(index["active_task_ids"], ["task-test-001"])

    def test_compact_plan_is_normalized_before_persistence(self) -> None:
        compact = {
            "title": "Compact task",
            "objective": "Persist a safe normalized task",
            "source_discussion": {"summary": "Scope is clear."},
            "acceptance_criteria": ["The normalized task is readable"],
            "work_items": [
                {
                    "work_id": "W-01",
                    "title": "Implement the change",
                    "outcome": "The change is verified",
                    "work_type": "implementation",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            result = create_task(project, compact)
            persisted = read_json(Path(result["task_dir"]) / "task-plan.json")

        self.assertEqual(persisted["schema_version"], "1.0")
        self.assertEqual(persisted["status"], "plan_ready")
        self.assertTrue(persisted["task_id"].startswith("task-"))
        self.assertEqual(persisted["out_of_scope"], [])
        self.assertEqual(
            persisted["source_discussion"],
            {
                "summary": "Scope is clear.",
                "accepted_decisions": [],
                "constraints": [],
                "assumptions": [],
                "open_questions": [],
            },
        )
        self.assertNotIn("execution_model_request", persisted)
        self.assertEqual(
            persisted["work_items"][0],
            {
                "work_id": "W-01",
                "title": "Implement the change",
                "outcome": "The change is verified",
                "work_type": "implementation",
                "dependencies": [],
                "read_scope": [],
                "write_scope": [],
                "verification": [],
                "risk": "medium",
                "uncertainty": "medium",
                "context_coupling": "high",
                "parallelizable": False,
                "isolated_worktree_required": False,
                "accountable_position": "",
                "profile": None,
                "review_profile": None,
                "status": "pending",
                "evidence_refs": [],
                "blockers": [],
                "required": True,
            },
        )

    def test_legacy_complete_plan_and_closure_fields_remain_valid(self) -> None:
        legacy = task_plan()
        legacy["work_items"][0]["status"] = "waived"
        legacy["work_items"][0]["waiver_reason"] = "Superseded by verified equivalent work"
        legacy["acceptance_evidence"] = {
            legacy["acceptance_criteria"][0]: ["test exit 0"]
        }
        normalized = validate_task_plan(legacy)
        self.assertEqual(normalized["execution_model_request"], legacy["execution_model_request"])
        self.assertEqual(normalized["acceptance_evidence"], legacy["acceptance_evidence"])
        self.assertEqual(
            normalized["work_items"][0]["waiver_reason"],
            "Superseded by verified equivalent work",
        )

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
