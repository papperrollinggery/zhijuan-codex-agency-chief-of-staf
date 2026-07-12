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

    def write_rollout(self, path: Path, thread_id: str, final: str) -> None:
        records = [
            {
                "type": "session_meta",
                "payload": {"id": thread_id, "model_provider": "openai"},
            },
            {
                "type": "turn_context",
                "payload": {"model": "gpt-5.6-sol", "effort": "max"},
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
        self.write_rollout(parent_rollout, self.parent_id, "RESULT: complete\nREVIEW: accepted")
        self.write_rollout(reviewer_rollout, self.reviewer_id, "REVIEW_VERDICT: PASS")

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
                "--require-archived",
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
            self.assertFalse(payload["agents_md_routing_dependency"])

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
