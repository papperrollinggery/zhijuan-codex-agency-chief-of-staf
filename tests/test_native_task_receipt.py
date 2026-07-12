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


class NativeTaskReceiptTests(unittest.TestCase):
    parent_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
    reviewer_id = "019f57ba-4b5d-76a2-bfe9-93cc7f0403c7"

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
                "payload": {"model": "gpt-5.6-sol", "effort": "max"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "status": "completed",
                    "call_id": "call-read",
                    "input": (
                        f"sed -n '1,20p' {artifact}"
                        if artifact
                        else "sed -n '1,20p' README.md"
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-read",
                    "output": (
                        artifact.read_text(encoding="utf-8")
                        if artifact
                        else "Delivery status: ready-for-review."
                    ),
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
        installed_root = base / "skills"
        for skill_name in install_skill.INSTALL_NAMES:
            install_skill.copy_runtime(ROOT, installed_root / skill_name, skill_name)

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

        database_path = base / "state.sqlite"
        database = sqlite3.connect(database_path)
        database.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT,
                model_provider TEXT, model TEXT, reasoning_effort TEXT,
                cwd TEXT, archived INTEGER, first_user_message TEXT,
                created_at_ms INTEGER, updated_at_ms INTEGER
            )
            """
        )
        database.execute(
            "CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY, status TEXT)"
        )
        database.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    f"<source_thread_id>{self.parent_id}</source_thread_id>\nAGENCY_WORKER: true",
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
        self, database: Path, installed_root: Path, model: str = "gpt-5.6-sol"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--state-db",
                str(database),
                "--source-root",
                str(ROOT),
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
            ],
            text=True,
            capture_output=True,
            check=False,
        )

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
            self.assertFalse(payload["agents_md_routing_dependency"])

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

    def test_rejects_wrong_model_and_luna(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database, installed_root = self.make_fixture(Path(tmp))
            wrong = self.run_verifier(database, installed_root, model="gpt-5.6-terra")
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("model identity mismatch", wrong.stderr)
            luna = self.run_verifier(database, installed_root, model="gpt-5.6-luna")
            self.assertNotEqual(luna.returncode, 0)
            self.assertIn("Luna is not allowed", luna.stderr)


if __name__ == "__main__":
    unittest.main()
