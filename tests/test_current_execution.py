from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, read_json

import agency_task


class CurrentExecutionTests(unittest.TestCase):
    def test_current_conversation_start_needs_no_native_session(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project)
            command = [
                sys.executable, str(ROOT / "scripts/agency_task.py"), "start",
                "--project", str(project), "--task-id", task_id, "--json",
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "executing")
            self.assertFalse((task_dir / "execution-session.json").exists())
            self.assertEqual(read_json(task_dir / "TEAM_PLAN.json")["positions"], [])
            self.assertEqual((task_dir / "progress.jsonl").read_text(), "")
            before = {p.name: p.read_bytes() for p in task_dir.iterdir() if p.is_file()}
            repeated = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(before, {p.name: p.read_bytes() for p in task_dir.iterdir() if p.is_file()})

    def test_start_refuses_to_take_over_prepared_native_session(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project)
            agency_task.atomic_write_json(task_dir / "execution-session.json", {"session_status": "native_launch_ready"})
            with self.assertRaisesRegex(ValueError, "execution session"):
                agency_task.start_current_execution(project, task_id)
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "plan_ready")

    def test_start_is_rollback_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project)
            files = [task_dir / "task-plan.json", task_dir / "TASK_EXECUTION_CHECKLIST.md", project / ".agency/task-index.json"]
            before = {p: p.read_bytes() for p in files}
            original = agency_task._transition_task_unlocked

            def fail_second(*args, **kwargs):
                if args[2] == "executing":
                    raise OSError("simulated second-stage failure")
                return original(*args, **kwargs)

            with mock.patch.object(agency_task, "_transition_task_unlocked", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "second-stage failure"):
                    agency_task.start_current_execution(project, task_id)
            self.assertEqual(before, {p: p.read_bytes() for p in files})


if __name__ == "__main__":
    unittest.main()
