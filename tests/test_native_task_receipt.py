from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_native_task_receipt.py"
sys.path.insert(0, str(ROOT / "scripts"))
import install_skill  # noqa: E402
from verify_native_task_receipt import (  # noqa: E402
    git_state,
    read_regular_bytes,
    require_unchanged_snapshot,
    write_new_private_file,
)


class NativeTaskReceiptTests(unittest.TestCase):
    parent_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
    reviewer_id = "019f57ba-4b5d-76a2-bfe9-93cc7f0403c7"

    def test_git_state_does_not_execute_local_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Receipt Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "receipt@example.invalid",
                ],
                check=True,
            )
            artifact = root / "artifact.txt"
            artifact.write_text("before\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "artifact.txt"], check=True
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "base"], check=True
            )
            sentinel = root / "fsmonitor-ran"
            helper = root / "fsmonitor.sh"
            helper.write_text(
                f"#!/bin/sh\ntouch {sentinel}\nprintf '0\\n'\n", encoding="utf-8"
            )
            helper.chmod(0o700)
            subprocess.run(
                ["git", "-C", str(root), "config", "core.fsmonitor", str(helper)],
                check=True,
            )
            artifact.write_text("after\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(sentinel.exists())
            sentinel.unlink()
            observed = git_state(root)
            self.assertFalse(sentinel.exists())
            self.assertFalse(observed["clean"])
            self.assertTrue(observed["fsmonitor_disabled"])
            self.assertTrue(observed["lazy_fetch_disabled"])

    def write_rollout(
        self,
        path: Path,
        thread_id: str,
        final: str,
        parent_id: str | None = None,
        artifact: Path | None = None,
    ) -> None:
        session = {
            "id": thread_id,
            "model_provider": "openai",
            "agent_path": "/root/reviewer",
        }
        if parent_id:
            session["parent_thread_id"] = parent_id
        records = [
            {
                "type": "session_meta",
                "payload": session,
            },
            {
                "type": "turn_context",
                "payload": {
                    "turn_id": "turn-1",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "status": "completed",
                    "call_id": "call-read",
                    "input": json.dumps(
                        {
                            "cmd": "cat -- README.md",
                            "workdir": str(path.parent),
                        }
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-read",
                    "output": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "exit_code": 0,
                                    "output": (
                                        artifact.read_text(encoding="utf-8")
                                        if artifact
                                        else "Delivery status: ready-for-review."
                                    ),
                                    "wall_time_seconds": 0.01,
                                }
                            ),
                        }
                    ],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "turn-1",
                    "last_agent_message": final,
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

    def make_fixture(self, base: Path) -> tuple[Path, Path]:
        source_root = base / "source"
        source_root.mkdir()
        install_skill.copy_runtime(ROOT, source_root)
        subprocess.run(["git", "init", "-q", str(source_root)], check=True)
        subprocess.run(
            ["git", "-C", str(source_root), "config", "user.name", "Receipt Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source_root), "config", "user.email", "receipt@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(source_root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(source_root), "commit", "-qm", "receipt source"],
            check=True,
        )
        installed_root = base / "skills"
        for skill_name in install_skill.INSTALL_NAMES:
            install_skill.copy_runtime(source_root, installed_root / skill_name, skill_name)

        parent_rollout = base / "parent.jsonl"
        reviewer_rollout = base / "reviewer.jsonl"
        artifact = base / "README.md"
        artifact.write_text("Delivery status: ready-for-review.\n", encoding="utf-8")
        self.write_rollout(
            parent_rollout,
            self.parent_id,
            "RESULT: complete\nREVIEW: accepted by /root/reviewer",
        )
        self.write_rollout(
            reviewer_rollout,
            self.reviewer_id,
            "REVIEW_TARGET: README.md\n"
            "REVIEW_READBACK: Delivery status: ready-for-review.\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS",
            parent_id=self.parent_id,
            artifact=artifact,
        )

        database_path = base / "state_5.sqlite"
        database = sqlite3.connect(database_path)
        database.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT,
                model_provider TEXT, model TEXT, reasoning_effort TEXT,
                cwd TEXT, archived INTEGER, first_user_message TEXT,
                sandbox_policy TEXT, agent_role TEXT,
                created_at_ms INTEGER, updated_at_ms INTEGER
            )
            """
        )
        database.execute(
            "CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY, status TEXT)"
        )
        database.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    self.parent_id,
                    str(parent_rollout),
                    "vscode",
                    "openai",
                    "gpt-5.6-sol",
                    "max",
                    str(base),
                    1,
                    "使用 $agency-chief-of-staff 完成任务",
                    json.dumps({"type": "workspace-write"}),
                    None,
                    1,
                    2,
                ),
                (
                    self.reviewer_id,
                    str(reviewer_rollout),
                    "vscode",
                    "openai",
                    "gpt-5.6-sol",
                    "max",
                    str(base),
                    1,
                    f"<source_thread_id>{self.parent_id}</source_thread_id>\n"
                    "AGENCY_WORKER: true\n"
                    "委派目标：独立审核当前 README.md。\n"
                    "读取范围：README.md 与当前 Git 状态。\n"
                    "写入范围：禁止写入。\n"
                    "期望产物：REVIEW_TARGET、REVIEW_READBACK、REVIEW_FINDINGS、REVIEW_RESIDUAL_RISK、REVIEW_VERDICT，均填实际读回值。\n"
                    "验证要求：直接读取当前 README.md 并返回实际读回。\n"
                    "停止条件：返回唯一终态；不启动、不派发。",
                    json.dumps(
                        {
                            "type": "managed",
                            "file_system": {
                                "type": "restricted",
                                "entries": [
                                    {"path": {"type": "special"}, "access": "read"}
                                ],
                            },
                            "network": "restricted",
                        }
                    ),
                    "reviewer",
                    2,
                    3,
                ),
            ],
        )
        database.execute(
            "INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
            (self.parent_id, self.reviewer_id, "open"),
        )
        database.commit()
        database.close()
        return database_path, installed_root

    def run_verifier(
        self,
        database: Path,
        installed_root: Path,
        model: str = "gpt-5.6-sol",
        script: Path = SCRIPT,
        out: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        output_args = ["--out", str(out)] if out is not None else []
        return subprocess.run(
            [
                "python3",
                str(script),
                "--state-db",
                str(database),
                "--codex-home",
                str(database.parent),
                "--source-root",
                str(database.parent / "source"),
                "--installed-root",
                str(installed_root),
                "--parent-id",
                self.parent_id,
                "--reviewer-id",
                self.reviewer_id,
                "--model",
                model,
                "--reasoning-effort",
                "max",
                "--parent-final-marker",
                "RESULT: complete",
                "--reviewer-final-marker",
                "REVIEW_VERDICT: PASS",
                "--reviewer-read-marker",
                "Delivery status: ready-for-review.",
                "--reviewer-artifact",
                str(database.parent / "README.md"),
                "--require-archived",
                "--require-clean-source",
                *output_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_receipt_output_is_new_private_and_never_follows_existing_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            direct = base / "direct.json"
            written = write_new_private_file(direct, b"verified\n")
            self.assertEqual(written, direct)
            self.assertEqual(direct.read_bytes(), b"verified\n")
            self.assertEqual(direct.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                write_new_private_file(direct, b"clobber\n")

            external = base / "external.txt"
            external.write_text("DO-NOT-CLOBBER\n", encoding="utf-8")
            hardlink = base / "hardlink.json"
            hardlink.hardlink_to(external)
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                write_new_private_file(hardlink, b"clobber\n")
            self.assertEqual(external.read_text(encoding="utf-8"), "DO-NOT-CLOBBER\n")

            symlink = base / "symlink.json"
            symlink.symlink_to(external)
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                write_new_private_file(symlink, b"clobber\n")
            self.assertEqual(external.read_text(encoding="utf-8"), "DO-NOT-CLOBBER\n")

    def test_verifier_out_refuses_existing_hardlink_without_clobbering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database, installed_root = self.make_fixture(base)
            external = base / "external.txt"
            external.write_text("DO-NOT-CLOBBER\n", encoding="utf-8")
            output = base / "receipt.json"
            output.hardlink_to(external)
            result = self.run_verifier(database, installed_root, out=output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing overwrite", result.stderr)
            self.assertEqual(external.read_text(encoding="utf-8"), "DO-NOT-CLOBBER\n")

    def test_verifies_bound_native_parent_and_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            result = self.run_verifier(database, installed_root)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "verified")
            self.assertEqual(payload["parent"]["thread_id"], self.parent_id)
            self.assertEqual(payload["reviewer"]["thread_id"], self.reviewer_id)
            self.assertEqual(
                payload["reviewer_binding"]["parent_thread_id"], self.parent_id
            )
            self.assertEqual(payload["reviewer_tool_read"]["paired_exec_outputs"], 1)
            self.assertEqual(payload["reviewer_identity"]["agent_role"], "reviewer")
            self.assertTrue(payload["canonical_state_store_bound"])
            self.assertTrue(payload["state_identity_guarded"])
            self.assertTrue(payload["state_wal_aware"])
            self.assertFalse(payload["historical_writes_verified"])
            self.assertEqual(payload["agents_md_state"], "unverified")
            self.assertIn("current_source_observation", payload)
            self.assertNotIn("source", payload)
            self.assertNotIn("agents_md_routing_dependency", payload)

    def test_completion_turn_must_bind_expected_model_and_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            rollout_path = Path(
                connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?", (self.parent_id,)
                ).fetchone()[0]
            )
            connection.close()
            records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
            for record in records:
                if record.get("type") == "turn_context":
                    record["payload"]["turn_id"] = "earlier-turn"
            records.insert(
                2,
                {
                    "type": "turn_context",
                    "payload": {
                        "turn_id": "turn-1",
                        "model": "switched-model",
                        "effort": "low",
                    },
                },
            )
            rollout_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = self.run_verifier(database, installed_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("completion turn model identity mismatch", result.stderr)

    def test_state_database_must_be_canonical_and_not_arbitrary_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database, installed_root = self.make_fixture(base)
            arbitrary = base / "arbitrary.sqlite"
            arbitrary.write_bytes(database.read_bytes())
            arbitrary_result = self.run_verifier(arbitrary, installed_root)
            self.assertNotEqual(arbitrary_result.returncode, 0)
            self.assertIn("codexHome/state_5.sqlite", arbitrary_result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database, installed_root = self.make_fixture(base)
            real = base / "real-state.sqlite"
            database.rename(real)
            allowed = base / "sqlite" / "state_5.sqlite"
            allowed.parent.mkdir()
            allowed.write_bytes(real.read_bytes())
            database.symlink_to(real)
            symlink_result = self.run_verifier(database, installed_root)
            self.assertNotEqual(symlink_result.returncode, 0)
            self.assertIn("symlink target is invalid", symlink_result.stderr)

    def test_secure_snapshot_detects_same_path_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.txt"
            artifact.write_text("first\n", encoding="utf-8")
            _data, snapshot = read_regular_bytes(artifact, "artifact")
            artifact.write_text("second\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed during"):
                require_unchanged_snapshot(artifact, "artifact", snapshot)

    def test_canonical_state_reader_observes_uncheckpointed_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            writer = sqlite3.connect(database)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute(
                    "UPDATE threads SET source = ? WHERE id = ?",
                    ("wal-visible", self.parent_id),
                )
                writer.commit()
                self.assertTrue(Path(str(database) + "-wal").is_file())
                result = self.run_verifier(database, installed_root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["parent"]["source"], "wal-visible")
            finally:
                writer.close()

    def test_installed_bundles_include_and_run_native_receipt_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            for skill_name in install_skill.INSTALL_NAMES:
                with self.subTest(skill_name=skill_name):
                    installed_script = (
                        installed_root
                        / skill_name
                        / "scripts"
                        / "verify_native_task_receipt.py"
                    )
                    self.assertTrue(installed_script.is_file())
                    result = self.run_verifier(
                        database, installed_root, script=installed_script
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(list((installed_root / skill_name).rglob("*.pyc")))

    def test_native_receipt_accepts_current_json_exec_read_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            rollout_path = Path(
                connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                ).fetchone()[0]
            )
            connection.close()
            records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
            for record in records:
                payload = record.get("payload", {})
                if payload.get("type") == "custom_tool_call":
                    payload["input"] = json.dumps(
                        {
                            "cmd": "cat -- README.md",
                            "workdir": str(database.parent),
                        }
                    )
            rollout_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = self.run_verifier(database, installed_root)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_native_spawn_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            connection.execute("DELETE FROM thread_spawn_edges")
            connection.commit()
            connection.close()
            result = self.run_verifier(database, installed_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no native spawn edge", result.stderr)

    def test_rejects_wrong_role_writable_sandbox_and_incomplete_packet(self) -> None:
        mutations = (
            ("agent_role = 'developer'", "agent_role is not reviewer"),
            ("sandbox_policy = '{\"type\":\"workspace-write\"}'", "restricted managed"),
            ("first_user_message = 'AGENCY_WORKER: true'", "worker packet is invalid"),
        )
        for assignment, expected in mutations:
            with self.subTest(assignment=assignment), tempfile.TemporaryDirectory() as tmp:
                database, installed_root = self.make_fixture(Path(tmp))
                connection = sqlite3.connect(database)
                connection.execute(
                    f"UPDATE threads SET {assignment} WHERE id = ?", (self.reviewer_id,)
                )
                connection.commit()
                connection.close()
                result = self.run_verifier(database, installed_root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_rejects_printed_artifact_path_as_direct_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            rollout_path = Path(
                connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                ).fetchone()[0]
            )
            connection.close()
            records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
            for record in records:
                payload = record.get("payload", {})
                if payload.get("type") == "custom_tool_call":
                    payload["input"] = (
                        f"printf '{database.parent / 'README.md'}'  # no artifact read"
                    )
            rollout_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = self.run_verifier(database, installed_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no single reviewer exec/output pair", result.stderr)

    def test_rejects_allowlisted_read_hidden_in_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            rollout_path = Path(
                connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                ).fetchone()[0]
            )
            connection.close()
            records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
            for record in records:
                payload = record.get("payload", {})
                if payload.get("type") == "custom_tool_call":
                    payload["input"] = (
                        f"python3 -c 'pass' # cat {database.parent / 'README.md'}"
                    )
            rollout_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = self.run_verifier(database, installed_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no single reviewer exec/output pair", result.stderr)

    def test_rejects_failed_reviewer_read_even_when_output_contains_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            connection = sqlite3.connect(database)
            rollout_path = Path(
                connection.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                ).fetchone()[0]
            )
            connection.close()
            records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
            for record in records:
                payload = record.get("payload", {})
                if payload.get("type") == "custom_tool_call_output":
                    payload["output"][0]["text"] = json.dumps(
                        {
                            "exit_code": 1,
                            "output": "Delivery status: ready-for-review.\n",
                            "wall_time_seconds": 0.01,
                        }
                    )
            rollout_path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            result = self.run_verifier(database, installed_root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no single reviewer exec/output pair", result.stderr)

    def test_requires_reviewer_markers_and_release_state(self) -> None:
        result = subprocess.run(
            ["python3", str(SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--reviewer-id REVIEWER_ID", result.stdout)

        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            command = self.run_verifier(database, installed_root).args
            reviewer_index = command.index("--reviewer-id")
            missing_reviewer_command = (
                command[:reviewer_index] + command[reviewer_index + 2 :]
            )
            missing_reviewer = subprocess.run(
                missing_reviewer_command, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(missing_reviewer.returncode, 0)
            self.assertIn("--reviewer-id", missing_reviewer.stderr)

            command = [
                item
                for item in command
                if item not in {"--reviewer-final-marker", "REVIEW_VERDICT: PASS"}
            ]
            missing_marker = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(missing_marker.returncode, 0)
            self.assertIn("--reviewer-final-marker is required", missing_marker.stderr)

            weak_command = [":" if item in {
                "RESULT: complete",
                "REVIEW_VERDICT: PASS",
                "Delivery status: ready-for-review.",
            } else item for item in self.run_verifier(database, installed_root).args]
            weak_marker = subprocess.run(
                weak_command, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(weak_marker.returncode, 0)
            self.assertIn("at least 16 characters", weak_marker.stderr)

    def test_rejects_wrong_model_and_external_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            wrong = self.run_verifier(database, installed_root, model="gpt-5.6-terra")
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("model identity mismatch", wrong.stderr)
            external = self.run_verifier(database, installed_root, model="claude-fable-5")
            self.assertNotEqual(external.returncode, 0)
            self.assertIn("external Claude models are disabled", external.stderr)

    def test_rejects_duplicate_extra_and_prefixed_pass_reviewer_schema(self) -> None:
        invalid_finals = (
            "REVIEW_TARGET: README.md\n"
            "REVIEW_TARGET: duplicate.md\n"
            "REVIEW_READBACK: Delivery status: ready-for-review.\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS",
            "REVIEW_TARGET: README.md\n"
            "REVIEW_READBACK: Delivery status: ready-for-review.\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS\n"
            "EXTRA: not allowed",
            "REVIEW_TARGET: README.md\n"
            "REVIEW_READBACK: Delivery status: ready-for-review.\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS_WITH_WARNINGS",
        )
        for final in invalid_finals:
            with self.subTest(final=final), tempfile.TemporaryDirectory() as tmp:
                database, installed_root = self.make_fixture(Path(tmp))
                connection = sqlite3.connect(database)
                rollout_path = Path(
                    connection.execute(
                        "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                    ).fetchone()[0]
                )
                connection.close()
                records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
                for record in records:
                    payload = record.get("payload", {})
                    if payload.get("type") == "task_complete":
                        payload["last_agent_message"] = final
                rollout_path.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                result = self.run_verifier(database, installed_root)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, r"exactly five|field order|exactly PASS")

    def test_rejects_reviewer_target_and_readback_not_bound_to_artifact(self) -> None:
        invalid_replacements = (
            ("REVIEW_TARGET: README.md", "REVIEW_TARGET: unrelated.md", "target does not match"),
            (
                "REVIEW_READBACK: Delivery status: ready-for-review.",
                "REVIEW_READBACK: invented fact",
                "readback",
            ),
        )
        for original, replacement, error in invalid_replacements:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as tmp:
                database, installed_root = self.make_fixture(Path(tmp))
                connection = sqlite3.connect(database)
                rollout_path = Path(
                    connection.execute(
                        "SELECT rollout_path FROM threads WHERE id = ?", (self.reviewer_id,)
                    ).fetchone()[0]
                )
                connection.close()
                records = [json.loads(line) for line in rollout_path.read_text().splitlines()]
                for record in records:
                    payload = record.get("payload", {})
                    if payload.get("type") == "task_complete":
                        payload["last_agent_message"] = payload["last_agent_message"].replace(
                            original, replacement, 1
                        )
                rollout_path.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                result = self.run_verifier(database, installed_root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)


if __name__ == "__main__":
    unittest.main()
