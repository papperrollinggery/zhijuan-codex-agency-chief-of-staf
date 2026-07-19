from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, completed_task, knowledge_candidate, read_json

sys.path.insert(0, str(ROOT / "scripts"))
from archive_task import archive_task  # noqa: E402
from validate_task_archive import validate_archive_directory, validate_archive_readiness  # noqa: E402


class TaskArchiveTests(unittest.TestCase):
    def test_incomplete_task_cannot_archive_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["status"] = "verifying"
            (task_dir / "task-plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_archive_readiness(project, task_dir, closure)

    def test_completed_archive_creates_manifest_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                candidates=[knowledge_candidate()],
                apply=True,
            )
            destination = Path(result["destination"])
            self.assertEqual(validate_archive_directory(destination)["status"], "valid")
            manifest = read_json(destination / "archive-manifest.json")
            self.assertEqual(manifest["final_status"], "archived")
            index = read_json(project / ".agency/task-index.json")
            self.assertNotIn("task-archive-001", index["active_task_ids"])
            self.assertIn("task-archive-001", index["archived_task_ids"])

    def test_reviewer_position_requires_handled_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project, reviewer=True)
            closure["review"] = {"status": "not_required", "evidence_refs": []}
            with self.assertRaisesRegex(ValueError, "Reviewer"):
                validate_archive_readiness(project, task_dir, closure)


if __name__ == "__main__":
    unittest.main()
