from __future__ import annotations

import tempfile
import unittest
import json
import copy
import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, live_catalog, read_json, work_item

sys.path.insert(0, str(ROOT / "scripts"))
import bind_execution_session as bind_execution_session_module  # noqa: E402
from bind_execution_session import (  # noqa: E402
    MECHANICAL_ATTESTATION,
    bind_execution_session,
    validate_bound_execution_session,
)
from agency_task import utc_now  # noqa: E402
from prepare_execution_launch import execution_packet, prepare_execution_launch  # noqa: E402
from prepare_team_runtime import prepare_team_runtime  # noqa: E402
from protocol_contract import parse_execution_session_packet  # noqa: E402

try:
    import jsonschema
except ImportError:  # pragma: no cover - package gate has a structural fallback
    jsonschema = None


NATIVE_TASK_ID = "019f7a4e-f1be-7771-9f67-38fcde417f48"


def trusted_readback(project: Path, task_id: str) -> dict[str, object]:
    return {
        "native_task_id": NATIVE_TASK_ID,
        "provider": "openai",
        "actual_model_id": "gpt-5.6-sol",
        "actual_reasoning_effort": "ultra",
        "cwd": str(project.resolve()),
        "isolated_worktree": False,
        "worktree_path": None,
        "status": "active-unarchived",
        "host_thread_readback": True,
        "prompt_bound": True,
        "catalog_bound": True,
        "state_store_identity": {
            "device": 1,
            "inode": 2,
            "identity_guarded": True,
            "wal_aware": True,
            "readonly_transaction": True,
        },
        "state_source": "appServer",
        "prompt_sha256": hashlib.sha256(
            execution_packet(project.resolve(), task_id).encode("utf-8")
        ).hexdigest(),
        "rollout_sha256": "a" * 64,
        "model_turns_observed": 1,
        "observed_at": utc_now(),
    }


class ExecutionSessionTests(unittest.TestCase):
    def test_execution_packet_is_distinct_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            packet = execution_packet(project, "task-session-001")
            parsed = parse_execution_session_packet(packet.rstrip("\n"))
            self.assertEqual(parsed["执行模型请求"], "GPT-5.6 Sol")
            self.assertEqual(parsed["推理强度请求"], "ultra")
            self.assertEqual(parsed["编排深度"], "0")
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
                catalog_mechanically_verified=True,
            )
            self.assertEqual(result["status"], "manual_launch_ready")
            self.assertEqual(result["lifecycle_status"], "execution_ready")
            self.assertFalse(result["new_conversation_created"])
            self.assertIsNone(read_json(task_dir / "execution-session.json")["native_task_id"])
            self.assertEqual(
                read_json(task_dir / "execution-session.json")["orchestration_depth"], 0
            )
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
                native_capabilities={
                    "task_thread_create": True,
                    "isolated_worktree": True,
                },
                native_readback=readback,
                catalog_mechanically_verified=True,
            )
            self.assertEqual(result["status"], "native_launch_ready")
            self.assertEqual(result["lifecycle_status"], "execution_ready")
            self.assertFalse(result["new_conversation_created"])
            consistency = result["native_readback_consistency"]
            self.assertEqual(consistency["status"], "fields_consistent_unverified")
            self.assertTrue(consistency["worktree_fields_consistent"])
            self.assertNotIn("verified", consistency)
            session = read_json(
                project / ".agency/tasks/active/task-native-001/execution-session.json"
            )
            self.assertIsNone(session["native_task_id"])
            self.assertIsNone(session["native_readback"])
            self.assertIsNone(session["native_readback_attestation"])

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_schema_rejects_caller_attestation_and_semantics_reject_forgery(self) -> None:
        schema = json.loads(
            (ROOT / "assets/execution-session.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-session-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            plan = read_json(task_dir / "task-plan.json")
            plan["execution_model_request"]["resolved_model_id"] = "gpt-5.6-sol"
            plan["execution_model_request"]["resolution_status"] = "resolved"
            plan["status"] = "executing"
            forged = {
                "schema_version": "1.0",
                "task_id": task_id,
                "orchestration_depth": 0,
                "project_root": str(project),
                "task_plan": f".agency/tasks/active/{task_id}/task-plan.json",
                "team_plan": f".agency/tasks/active/{task_id}/TEAM_PLAN.json",
                "progress_file": f".agency/tasks/active/{task_id}/PROGRESS.md",
                "display_model_request": "GPT-5.6 Sol",
                "reasoning_request": "ultra",
                "resolved_model_id": "gpt-5.6-sol",
                "model_resolution_status": "resolved",
                "launch_policy": "prefer_native",
                "session_status": "executing",
                "native_task_id": NATIVE_TASK_ID,
                "native_readback": trusted_readback(project, task_id),
                "native_readback_attestation": "caller-supplied-unverified",
                "created_at": "2026-07-19T00:00:00Z",
                "bound_at": None,
            }
            forged["bound_at"] = forged["native_readback"]["observed_at"]
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.Draft202012Validator(schema).validate(forged)

            forged["native_readback_attestation"] = MECHANICAL_ATTESTATION
            jsonschema.Draft202012Validator(schema).validate(forged)
            validate_bound_execution_session(forged, plan, project)

            mutations = {
                "nested task": ("native_readback", "native_task_id", "029f7a4e-f1be-7771-9f67-38fcde417f48"),
                "model": ("native_readback", "actual_model_id", "different-model"),
                "effort": ("native_readback", "actual_reasoning_effort", "xhigh"),
                "provider": ("native_readback", "provider", "external"),
                "cwd": ("native_readback", "cwd", "/tmp/other-project"),
            }
            for label, (container, field, value) in mutations.items():
                inconsistent = copy.deepcopy(forged)
                inconsistent[container][field] = value
                with self.subTest(label=label):
                    with self.assertRaisesRegex(ValueError, "inconsistent"):
                        validate_bound_execution_session(inconsistent, plan, project)

    def test_binding_uses_internal_mechanical_readback_and_enters_executing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-bind-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            observation = trusted_readback(project, task_id)
            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=observation,
            ) as mechanical:
                result = bind_execution_session(
                    project,
                    task_id=task_id,
                    native_task_id=NATIVE_TASK_ID,
                    apply=True,
                )
            self.assertEqual(mechanical.call_count, 1)
            self.assertEqual(result["status"], "bound")
            self.assertTrue(result["new_conversation_created"])
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "executing")
            session = read_json(task_dir / "execution-session.json")
            self.assertEqual(session["native_task_id"], NATIVE_TASK_ID)
            self.assertEqual(session["native_readback"], observation)
            self.assertEqual(session["native_readback_attestation"], MECHANICAL_ATTESTATION)
            self.assertIn("mechanically read back", (task_dir / "progress.jsonl").read_text())

    def test_binding_transition_failure_restores_session_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-bind-rollback-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            session_before = (task_dir / "execution-session.json").read_text()
            plan_before = (task_dir / "task-plan.json").read_text()
            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=trusted_readback(project, task_id),
            ), mock.patch.object(
                bind_execution_session_module,
                "transition_task",
                side_effect=OSError("transition failed"),
            ):
                with self.assertRaisesRegex(OSError, "transition failed"):
                    bind_execution_session(
                        project,
                        task_id=task_id,
                        native_task_id=NATIVE_TASK_ID,
                        apply=True,
                    )
            self.assertEqual((task_dir / "execution-session.json").read_text(), session_before)
            self.assertEqual((task_dir / "task-plan.json").read_text(), plan_before)

    def test_mechanical_reader_joins_host_state_catalog_packet_and_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-mechanical-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            plan = read_json(task_dir / "task-plan.json")
            plan["execution_model_request"]["resolved_model_id"] = "gpt-5.6-sol"
            plan["execution_model_request"]["resolution_status"] = "resolved"
            packet = execution_packet(project, task_id)
            rollout = project / "rollout.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": NATIVE_TASK_ID,
                                    "model_provider": "openai",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {
                                    "turn_id": "turn-1",
                                    "model": "gpt-5.6-sol",
                                    "effort": "ultra",
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            database = sqlite3.connect(":memory:")
            database.execute(
                """
                CREATE TABLE threads (
                    id TEXT, rollout_path TEXT, source TEXT, model_provider TEXT,
                    model TEXT, reasoning_effort TEXT, cwd TEXT, archived INTEGER,
                    first_user_message TEXT, agent_role TEXT, created_at_ms INTEGER
                )
                """
            )
            database.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    NATIVE_TASK_ID,
                    str(rollout),
                    "appServer",
                    "openai",
                    "gpt-5.6-sol",
                    "ultra",
                    str(project),
                    0,
                    packet,
                    None,
                    1_784_592_001_000,
                ),
            )
            database.commit()

            class FakeApp:
                codex_home = project

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def request(self, method, params):
                    self.assert_request(method, params)
                    return {
                        "thread": {
                            "id": NATIVE_TASK_ID,
                            "parentThreadId": None,
                            "preview": packet,
                        }
                    }

                @staticmethod
                def assert_request(method, params):
                    if method != "thread/read" or params.get("threadId") != NATIVE_TASK_ID:
                        raise AssertionError("unexpected App Server request")

            @contextmanager
            def state_connection(*_args, **_kwargs):
                yield database, {
                    "device": 1,
                    "inode": 2,
                    "identity_guarded": True,
                    "wal_aware": True,
                    "readonly_transaction": True,
                }

            session = {
                "created_at": "2026-07-21T00:00:00Z",
                "resolved_model_id": "gpt-5.6-sol",
                "reasoning_request": "ultra",
            }
            model = {
                "model": "gpt-5.6-sol",
                "modelProvider": "openai",
                "available": True,
                "supportedReasoningEfforts": [{"reasoningEffort": "ultra"}],
            }
            with mock.patch.object(
                bind_execution_session_module, "resolve_executable", return_value=Path("/bin/true")
            ), mock.patch.object(
                bind_execution_session_module, "CodexAppServer", return_value=FakeApp()
            ), mock.patch.object(
                bind_execution_session_module, "collect_model_items", return_value=[model]
            ), mock.patch.object(
                bind_execution_session_module,
                "canonical_state_connection",
                side_effect=state_connection,
            ):
                observed = bind_execution_session_module._mechanical_readback(
                    project,
                    plan,
                    session,
                    NATIVE_TASK_ID,
                    codex_bin="codex",
                    codex_home=None,
                    state_db=None,
                    timeout_seconds=20,
                )
            database.close()
            self.assertEqual(observed["native_task_id"], NATIVE_TASK_ID)
            self.assertEqual(observed["actual_model_id"], "gpt-5.6-sol")
            self.assertEqual(observed["actual_reasoning_effort"], "ultra")
            self.assertEqual(observed["status"], "active-unarchived")
            self.assertEqual(observed["model_turns_observed"], 1)

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
                catalog_mechanically_verified=True,
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
                catalog_mechanically_verified=True,
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
