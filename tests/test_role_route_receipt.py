from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_role_route_receipt as receipt_module  # noqa: E402
from verify_role_route_receipt import verify_receipt  # noqa: E402


PARENT_ID = "11111111-1111-1111-1111-111111111111"
CHILD_ID = "22222222-2222-2222-2222-222222222222"


class RoleRouteReceiptTests(unittest.TestCase):
    def fixture(
        self,
        root: Path,
        *,
        child_model: str = "child-model",
        child_effort: str = "medium",
        rollout_model: str | None = None,
        agent_role: str | None = None,
        with_parent_spawn: bool = False,
    ) -> Path:
        rollout = root / "child-rollout.jsonl"
        records = [
            {
                "type": "session_meta",
                "payload": {
                    "id": CHILD_ID,
                    "parent_thread_id": PARENT_ID,
                    "model_provider": "openai",
                },
            },
            {
                "type": "turn_context",
                "payload": {
                    "turn_id": "turn-child",
                    "model": rollout_model or child_model,
                    "effort": child_effort,
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn-child",
                    "last_agent_message": "child completed",
                },
            },
        ]
        rollout.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        parent_rollout = root / "parent-rollout.jsonl"
        parent_records = [
            {
                "type": "session_meta",
                "payload": {
                    "id": PARENT_ID,
                    "model_provider": "openai",
                },
            }
        ]
        if with_parent_spawn:
            parent_records.extend(
                [
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "namespace": "agents",
                            "name": "spawn_agent",
                            "call_id": "call-spawn",
                            "arguments": json.dumps(
                                {
                                    "task_name": "native_smoke",
                                    "message": "self-contained packet",
                                    "model": child_model,
                                    "reasoning_effort": child_effort,
                                    "fork_turns": "none",
                                }
                            ),
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-spawn",
                            "output": json.dumps(
                                {
                                    "task_name": "/root/native_smoke",
                                    "nickname": "Einstein",
                                }
                            ),
                        },
                    },
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "sub_agent_activity",
                            "event_id": "call-spawn",
                            "agent_thread_id": CHILD_ID,
                            "agent_path": "/root/native_smoke",
                            "kind": "started",
                        },
                    },
                ]
            )
        parent_rollout.write_text(
            "\n".join(json.dumps(record) for record in parent_records) + "\n",
            encoding="utf-8",
        )
        database_path = root / "state_5.sqlite"
        database = sqlite3.connect(database_path)
        try:
            database.executescript(
                """
                CREATE TABLE threads (
                    id TEXT PRIMARY KEY,
                    rollout_path TEXT,
                    model_provider TEXT,
                    model TEXT,
                    reasoning_effort TEXT,
                    archived INTEGER,
                    agent_role TEXT
                );
                CREATE TABLE thread_spawn_edges (
                    parent_thread_id TEXT,
                    child_thread_id TEXT,
                    status TEXT
                );
                """
            )
            database.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    PARENT_ID,
                    str(parent_rollout),
                    "openai",
                    "root-model",
                    "high",
                    0,
                    None,
                ),
            )
            database.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    CHILD_ID,
                    str(rollout),
                    "openai",
                    child_model,
                    child_effort,
                    1,
                    agent_role,
                ),
            )
            database.execute(
                "INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                (PARENT_ID, CHILD_ID, "completed"),
            )
            database.commit()
        finally:
            database.close()
        return database_path

    def test_direct_heterogeneous_route_binds_edge_state_and_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(Path(tmp))
            receipt = verify_receipt(
                state_db=database,
                parent_id=PARENT_ID,
                child_id=CHILD_ID,
                expected_provider="openai",
                expected_model="child-model",
                expected_effort="medium",
                route_kind="direct",
                expected_agent_role=None,
                expected_edge_status="completed",
                require_archived=True,
                codex_home=Path(tmp),
            )
        self.assertEqual(receipt["status"], "locally-consistent")
        self.assertTrue(receipt["canonical_state_store_bound"])
        self.assertFalse(receipt["current_task_binding_verified"])
        self.assertTrue(receipt["heterogeneous"])
        self.assertEqual(receipt["child"]["model"], "child-model")
        self.assertTrue(receipt["rollout_binding"]["turn_context_bound"])
        self.assertFalse(receipt["native_spawn_call_arguments_verified"])

    def test_parent_native_spawn_call_and_output_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(Path(tmp), with_parent_spawn=True)
            receipt = verify_receipt(
                state_db=database,
                parent_id=PARENT_ID,
                child_id=CHILD_ID,
                expected_provider="openai",
                expected_model="child-model",
                expected_effort="medium",
                route_kind="direct",
                expected_agent_role=None,
                expected_edge_status="completed",
                require_archived=True,
                require_native_spawn_call=True,
                codex_home=Path(tmp),
            )
        self.assertTrue(receipt["native_spawn_call_arguments_verified"])
        self.assertEqual(receipt["native_spawn_binding"]["fork_turns"], "none")
        self.assertEqual(receipt["native_spawn_binding"]["model"], "child-model")
        self.assertEqual(receipt["native_spawn_binding"]["call_id"], "call-spawn")
        self.assertTrue(receipt["native_spawn_binding"]["activity_child_bound"])
        self.assertIsNotNone(receipt["parent_rollout_sha256"])

    def test_parent_spawn_call_must_be_unique_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root, with_parent_spawn=True)
            parent_rollout = root / "parent-rollout.jsonl"
            records = [
                json.loads(line) for line in parent_rollout.read_text().splitlines()
            ]
            call = json.loads(json.dumps(records[1]))
            call["payload"]["call_id"] = "call-spawn-2"
            records.append(call)
            output = json.loads(json.dumps(records[2]))
            output["payload"]["call_id"] = "call-spawn-2"
            records.append(output)
            parent_rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly one matching"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    require_native_spawn_call=True,
                    codex_home=root,
                )

    def test_parent_spawn_activity_must_bind_the_expected_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root, with_parent_spawn=True)
            parent_rollout = root / "parent-rollout.jsonl"
            records = [
                json.loads(line) for line in parent_rollout.read_text().splitlines()
            ]
            records[3]["payload"]["agent_thread_id"] = (
                "33333333-3333-3333-3333-333333333333"
            )
            parent_rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected child thread"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    require_native_spawn_call=True,
                    codex_home=root,
                )

    def test_parent_spawn_activity_must_be_unique_and_match_output_path(self) -> None:
        for mutation, expected in (
            ("missing", "exactly one matching started activity"),
            ("duplicate", "exactly one matching started activity"),
            ("path", "activity path"),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                database = self.fixture(root, with_parent_spawn=True)
                parent_rollout = root / "parent-rollout.jsonl"
                records = [
                    json.loads(line)
                    for line in parent_rollout.read_text().splitlines()
                ]
                if mutation == "missing":
                    records.pop(3)
                elif mutation == "duplicate":
                    records.append(json.loads(json.dumps(records[3])))
                else:
                    records[3]["payload"]["agent_path"] = "/root/other-task"
                parent_rollout.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, expected):
                    verify_receipt(
                        state_db=database,
                        parent_id=PARENT_ID,
                        child_id=CHILD_ID,
                        expected_provider="openai",
                        expected_model="child-model",
                        expected_effort="medium",
                        route_kind="direct",
                        expected_agent_role=None,
                        expected_edge_status="completed",
                        require_archived=True,
                        require_native_spawn_call=True,
                        codex_home=root,
                    )

    def test_parent_spawn_call_requires_exact_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root, with_parent_spawn=True)
            parent_rollout = root / "parent-rollout.jsonl"
            records = [
                json.loads(line) for line in parent_rollout.read_text().splitlines()
            ]
            arguments = json.loads(records[1]["payload"]["arguments"])
            arguments["reasoning_effort"] = "low"
            records[1]["payload"]["arguments"] = json.dumps(arguments)
            parent_rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly one matching"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    require_native_spawn_call=True,
                    codex_home=root,
                )

    def test_rollout_fifo_and_oversize_file_fail_without_blocking_or_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            rollout.unlink()
            os.mkfifo(rollout)
            with self.assertRaisesRegex(ValueError, "single regular file"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    codex_home=root,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            with rollout.open("wb") as handle:
                handle.truncate(receipt_module.MAX_ROLLOUT_BYTES + 1)
            with self.assertRaisesRegex(ValueError, "64 MiB"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    codex_home=root,
                )

    def test_custom_agent_route_requires_persisted_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(Path(tmp), agent_role="reviewer")
            receipt = verify_receipt(
                state_db=database,
                parent_id=PARENT_ID,
                child_id=CHILD_ID,
                expected_provider="openai",
                expected_model="child-model",
                expected_effort="medium",
                route_kind="custom-agent",
                expected_agent_role="reviewer",
                expected_edge_status=None,
                require_archived=False,
                codex_home=Path(tmp),
            )
        self.assertEqual(receipt["child"]["agent_role"], "reviewer")

    def test_external_provider_is_rejected_even_if_caller_claims_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "only support.*OpenAI"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="anthropic",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=Path(tmp),
                )

    def test_external_model_slug_is_rejected_even_with_openai_provider_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(Path(tmp), child_model="claude-fable-5")
            with self.assertRaisesRegex(ValueError, "external Claude models"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="claude-fable-5",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=Path(tmp),
                )

    def test_inherited_route_and_rollout_identity_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(
                Path(tmp), child_model="root-model", child_effort="high"
            )
            with self.assertRaisesRegex(ValueError, "not heterogeneous"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="root-model",
                    expected_effort="high",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=Path(tmp),
                )

        with tempfile.TemporaryDirectory() as tmp:
            database = self.fixture(
                Path(tmp), child_model="child-model", rollout_model="different-model"
            )
            with self.assertRaisesRegex(ValueError, "completion turn"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=Path(tmp),
                )

    def test_completion_turn_must_match_expected_model_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            records = [json.loads(line) for line in rollout.read_text().splitlines()]
            records[1]["payload"]["turn_id"] = "earlier-turn"
            records.insert(
                2,
                {
                    "type": "turn_context",
                    "payload": {
                        "turn_id": "turn-child",
                        "model": "switched-model",
                        "effort": "low",
                    },
                },
            )
            rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "completion turn"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=root,
                )

    def test_arbitrary_state_database_is_not_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            renamed = root / "arbitrary.sqlite"
            database.rename(renamed)
            with self.assertRaisesRegex(ValueError, "codexHome/state_5.sqlite"):
                verify_receipt(
                    state_db=renamed,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=root,
                )

    def test_completion_turn_rejects_ambiguous_contexts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            records = [json.loads(line) for line in rollout.read_text().splitlines()]
            records.insert(
                2,
                {
                    "type": "turn_context",
                    "payload": {
                        "turn_id": "turn-child",
                        "model": "other-model",
                        "effort": "low",
                    },
                },
            )
            rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly one turn context"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=root,
                )

    def test_rollout_symlink_is_rejected_before_validation_or_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            target = root / "target-rollout.jsonl"
            rollout.rename(target)
            rollout.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "non-symlink regular file"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status=None,
                    require_archived=False,
                    codex_home=root,
                )

    def test_rollout_drift_after_bound_read_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            rollout = root / "child-rollout.jsonl"
            original = receipt_module.verify_child_rollout

            def mutate_after_validation(*args, **kwargs):
                result = original(*args, **kwargs)
                rollout.write_text(
                    rollout.read_text(encoding="utf-8")
                    + json.dumps({"type": "event_msg", "payload": {"type": "raced"}})
                    + "\n",
                    encoding="utf-8",
                )
                return result

            with mock.patch.object(
                receipt_module,
                "verify_child_rollout",
                side_effect=mutate_after_validation,
            ), self.assertRaisesRegex(ValueError, "changed during receipt"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    codex_home=root,
                )

    def test_state_drift_between_observation_windows_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            original = receipt_module.require_unchanged_snapshot
            checkpoint_calls = 0

            def mutate_after_first_checkpoint(*args, **kwargs):
                nonlocal checkpoint_calls
                original(*args, **kwargs)
                checkpoint_calls += 1
                if checkpoint_calls == 1:
                    connection = sqlite3.connect(database)
                    try:
                        connection.execute(
                            "UPDATE threads SET model = ? WHERE id = ?",
                            ("raced-model", CHILD_ID),
                        )
                        connection.commit()
                    finally:
                        connection.close()

            with mock.patch.object(
                receipt_module,
                "require_unchanged_snapshot",
                side_effect=mutate_after_first_checkpoint,
            ), self.assertRaisesRegex(ValueError, "state changed"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    codex_home=root,
                )

    def test_same_content_state_database_replacement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self.fixture(root)
            original = receipt_module.require_unchanged_snapshot
            replaced = False

            def replace_after_first_checkpoint(*args, **kwargs):
                nonlocal replaced
                original(*args, **kwargs)
                if not replaced:
                    replacement = root / "replacement.sqlite"
                    shutil.copy2(database, replacement)
                    os.replace(replacement, database)
                    replaced = True

            with mock.patch.object(
                receipt_module,
                "require_unchanged_snapshot",
                side_effect=replace_after_first_checkpoint,
            ), self.assertRaisesRegex(ValueError, "store identity changed"):
                verify_receipt(
                    state_db=database,
                    parent_id=PARENT_ID,
                    child_id=CHILD_ID,
                    expected_provider="openai",
                    expected_model="child-model",
                    expected_effort="medium",
                    route_kind="direct",
                    expected_agent_role=None,
                    expected_edge_status="completed",
                    require_archived=True,
                    codex_home=root,
                )


if __name__ == "__main__":
    unittest.main()
