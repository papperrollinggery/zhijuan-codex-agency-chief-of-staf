from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, live_catalog, read_json, work_item

sys.path.insert(0, str(ROOT / "scripts"))
from prepare_execution_launch import execution_packet, prepare_execution_launch  # noqa: E402
from prepare_team_runtime import prepare_team_runtime  # noqa: E402
from protocol_contract import parse_execution_session_packet  # noqa: E402


class ExecutionSessionTests(unittest.TestCase):
    def test_execution_packet_is_distinct_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            packet = execution_packet(project, "task-session-001")
            parsed = parse_execution_session_packet(packet.rstrip("\n"))
            self.assertEqual(parsed["执行模型请求"], "GPT-5.6 Sol")
            self.assertEqual(parsed["推理强度请求"], "ultra")
            self.assertNotIn("AGENCY_WORKER: true", packet)
            with self.assertRaises(ValueError):
                parse_execution_session_packet("\n" + packet.rstrip("\n"))

    def test_unavailable_native_surface_generates_manual_launch_without_claiming_thread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-manual-001")
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": False},
            )
            self.assertEqual(result["status"], "manual_launch_ready")
            self.assertEqual(result["lifecycle_status"], "execution_ready")
            self.assertFalse(result["new_conversation_created"])
            self.assertIsNone(read_json(task_dir / "execution-session.json")["native_task_id"])
            self.assertIn(
                "Execution session prepared",
                (task_dir / "progress.jsonl").read_text(encoding="utf-8"),
            )
            self.assertIn("execution_ready", (task_dir / "PROGRESS.md").read_text(encoding="utf-8"))

    def test_native_write_launch_requires_verified_isolated_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            worktree = base / "worktree"
            project.mkdir()
            worktree.mkdir()
            task_id, _ = create_fixture_task(project, "task-native-001")
            readback = {
                "native_task_id": "019f7a4e-f1be-7771-9f67-38fcde417f48",
                "provider": "openai",
                "actual_model_id": "gpt-5.6-sol",
                "actual_reasoning_effort": "ultra",
                "cwd": str(worktree),
                "worktree_path": str(worktree),
                "isolated_worktree": True,
                "status": "running",
            }
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_readback=readback,
            )
            self.assertEqual(result["status"], "executing")
            self.assertEqual(result["lifecycle_status"], "executing")
            self.assertTrue(result["new_conversation_created"])
            self.assertTrue(result["native_readback_verification"]["worktree_readback_verified"])

    def test_native_model_mismatch_fails_without_executing_transition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = create_fixture_task(project, "task-mismatch-001")
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_readback={
                    "native_task_id": "019f7a4e-f1be-7771-9f67-38fcde417f48",
                    "provider": "openai",
                    "actual_model_id": "different-model",
                    "actual_reasoning_effort": "ultra",
                    "cwd": str(project),
                    "worktree_path": str(project),
                    "isolated_worktree": True,
                    "status": "running",
                },
            )
            self.assertEqual(result["status"], "readback_mismatch")
            self.assertEqual(result["lifecycle_status"], "plan_ready")
            self.assertFalse(result["new_conversation_created"])

    def test_selected_only_profiles_do_not_touch_agents_md(self) -> None:
        items = [
            work_item("W-01", work_type="architecture", read_scope=["api/", "domain/"]),
            work_item(
                "W-02",
                dependencies=["W-01"],
                write_scope=["api/handler.py", "domain/model.py"],
                risk="medium",
            ),
        ]
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "AGENTS.md").write_text("USER SENTINEL\n", encoding="utf-8")
            task_id, task_dir = create_fixture_task(
                project,
                "task-profiles-001",
                items=items,
                title="Cross-module migration",
            )
            launch = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={},
            )
            result = prepare_team_runtime(
                project,
                task_dir / "TEAM_PLAN.json",
                apply=True,
            )
            installed = {path.stem for path in (project / ".codex/agents").glob("*.toml")}
            self.assertEqual(installed, set(launch["selected_profiles"]))
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), "USER SENTINEL\n")
            self.assertFalse(result["agents_md_touched"])


if __name__ == "__main__":
    unittest.main()
