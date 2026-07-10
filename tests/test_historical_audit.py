from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HistoricalAuditTests(unittest.TestCase):
    def test_fixture_runs_without_agents_routing_advice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "audit.json"
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "audit_historical_threads.py"),
                    "--repo-root",
                    str(ROOT),
                    "--fixture",
                    str(ROOT / "evals" / "history_threads.sample.json"),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "valid")
            categories = payload["summary"]["issue_categories"]
            self.assertIn("cross_project_context_requires_readback", categories)
            serialized = json.dumps(payload, ensure_ascii=False).lower()
            self.assertNotIn("agents routing", serialized)
            self.assertNotIn("agents_snippet", serialized)
            self.assertNotIn("cos_main_overexecution", serialized)
            self.assertNotIn("main_thread_self_execution_complaint", serialized)
            not_due = next(
                item
                for item in payload["threads"]
                if item["thread_id"] == "fixture-automation-not-due-valid"
            )
            self.assertNotIn(
                "automation_lifecycle_missing_evidence", not_due["categories"]
            )
            due = next(
                item
                for item in payload["threads"]
                if item["thread_id"] == "fixture-automation-lifecycle-missing-evidence"
            )
            self.assertIn("automation_lifecycle_missing_evidence", due["categories"])
            for thread_id in (
                "fixture-automation-due-now-with-next-due",
                "fixture-automation-overdue-with-next-due",
                "fixture-automation-not-due-then-due-now",
                "fixture-automation-invalid-not-due-prefix",
            ):
                due_with_next = next(
                    item for item in payload["threads"] if item["thread_id"] == thread_id
                )
                self.assertIn(
                    "automation_lifecycle_missing_evidence",
                    due_with_next["categories"],
                )
            latest_not_due = next(
                item
                for item in payload["threads"]
                if item["thread_id"] == "fixture-automation-due-now-then-not-due"
            )
            self.assertNotIn(
                "automation_lifecycle_missing_evidence", latest_not_due["categories"]
            )
            current_receipt = next(
                item
                for item in payload["threads"]
                if item["thread_id"] == "fixture-current-work-receipt-good"
            )
            self.assertTrue(current_receipt["markers"]["has_current_work_receipt"])
            self.assertNotIn("dispatch_missing_or_unproven", current_receipt["categories"])


if __name__ == "__main__":
    unittest.main()
