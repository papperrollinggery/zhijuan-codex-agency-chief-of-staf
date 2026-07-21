from __future__ import annotations

import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, live_catalog

sys.path.insert(0, str(ROOT / "scripts"))
import resolve_execution_model as execution_model_module  # noqa: E402
from resolve_execution_model import (  # noqa: E402
    live_catalog as read_live_catalog,
    resolve_execution_model,
)


class ExecutionModelTests(unittest.TestCase):
    def test_live_catalog_uses_explicit_root_state_when_provider_is_omitted(self) -> None:
        thread_id = "11111111-1111-1111-1111-111111111111"

        class FakeApp:
            def __init__(self, codex_home: Path) -> None:
                self.codex_home = codex_home

            def __enter__(self) -> "FakeApp":
                return self

            def __exit__(self, *_: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            codex_home = Path(raw) / "codex-home"
            project.mkdir()
            codex_home.mkdir()
            app = FakeApp(codex_home)
            database = sqlite3.connect(codex_home / "state_5.sqlite")
            database.execute("CREATE TABLE threads (id TEXT, model_provider TEXT)")
            database.execute(
                "INSERT INTO threads (id, model_provider) VALUES (?, ?)",
                (thread_id, "openai"),
            )
            database.commit()
            database.close()

            item = {
                "model": "gpt-5.6-sol",
                "displayName": "GPT-5.6-Sol",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "high"},
                    {"reasoningEffort": "ultra"},
                ],
            }
            with (
                mock.patch.object(
                    execution_model_module,
                    "resolve_executable",
                    return_value=Path("/bin/true"),
                ),
                mock.patch.object(
                    execution_model_module, "CodexAppServer", return_value=app
                ),
                mock.patch.object(
                    execution_model_module, "collect_model_items", return_value=[item]
                ),
            ):
                catalog = read_live_catalog(
                    codex_bin="codex", project=project, thread_id=thread_id
                )

        self.assertEqual(catalog["models"][0]["provider"], "openai")
        self.assertEqual(
            catalog["models"][0]["provider_evidence"],
            "selected-root-state-inferred",
        )
        resolved = resolve_execution_model(
            catalog, catalog_mechanically_verified=True
        )
        self.assertTrue(resolved["launch_allowed"])
        self.assertEqual(resolved["resolved_model_id"], "gpt-5.6-sol")

    def test_live_catalog_does_not_guess_provider_without_explicit_root(self) -> None:
        class FakeApp:
            def __init__(self, codex_home: Path) -> None:
                self.codex_home = codex_home

            def __enter__(self) -> "FakeApp":
                return self

            def __exit__(self, *_: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            codex_home = Path(raw) / "codex-home"
            project.mkdir()
            codex_home.mkdir()
            with (
                mock.patch.object(
                    execution_model_module,
                    "resolve_executable",
                    return_value=Path("/bin/true"),
                ),
                mock.patch.object(
                    execution_model_module,
                    "CodexAppServer",
                    return_value=FakeApp(codex_home),
                ),
                mock.patch.object(
                    execution_model_module,
                    "collect_model_items",
                    return_value=[
                        {
                            "model": "gpt-5.6-sol",
                            "displayName": "GPT-5.6-Sol",
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "ultra"}
                            ],
                        }
                    ],
                ),
            ):
                catalog = read_live_catalog(codex_bin="codex", project=project)

        self.assertIsNone(catalog["models"][0]["provider"])
        self.assertEqual(catalog["models"][0]["provider_evidence"], "unverified")
        result = resolve_execution_model(
            catalog, catalog_mechanically_verified=True
        )
        self.assertEqual(result["reason"], "requested_provider_unverified")

    def test_state_database_cannot_be_selected_without_a_root_thread(self) -> None:
        with self.assertRaisesRegex(ValueError, "state_db requires thread_id"):
            read_live_catalog(
                codex_bin="codex",
                project=Path.cwd(),
                state_db=Path("state_5.sqlite"),
            )

    def test_sol_ultra_resolves_to_live_exact_id(self) -> None:
        result = resolve_execution_model(live_catalog(), catalog_mechanically_verified=True)
        self.assertEqual(result["resolved_model_id"], "gpt-5.6-sol")
        self.assertEqual(result["resolved_reasoning"], "ultra")
        self.assertTrue(result["launch_allowed"])

    def test_ultra_unsupported_requires_user_choice_without_downgrade(self) -> None:
        result = resolve_execution_model(
            live_catalog(ultra=False), catalog_mechanically_verified=True
        )
        self.assertEqual(result["resolution_status"], "user_choice_required")
        self.assertIsNone(result["resolved_reasoning"])
        self.assertFalse(result["launch_allowed"])
        self.assertEqual(len(result["choices"]), 3)

    def test_missing_sol_is_not_guessed(self) -> None:
        result = resolve_execution_model(
            live_catalog(include_sol=False), catalog_mechanically_verified=True
        )
        self.assertIsNone(result["resolved_model_id"])
        self.assertEqual(result["reason"], "requested_display_model_not_found")

    def test_matching_sol_without_provider_proof_is_not_launchable(self) -> None:
        catalog = live_catalog()
        catalog["models"][0]["provider"] = None
        result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
        self.assertEqual(result["reason"], "requested_provider_unverified")
        self.assertEqual(result["candidate_model_ids"], ["gpt-5.6-sol"])
        self.assertFalse(result["launch_allowed"])

    def test_non_live_catalog_is_rejected(self) -> None:
        catalog = live_catalog()
        catalog["live_readback_verified"] = False
        result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
        self.assertEqual(result["reason"], "live_catalog_required")
        self.assertFalse(result["launch_allowed"])

    def test_spawn_readback_mismatch_is_fail(self) -> None:
        result = resolve_execution_model(
            live_catalog(),
            spawn_readback={
                "provider": "openai",
                "actual_model_id": "gpt-5.6-sol",
                "actual_reasoning_effort": "xhigh",
            },
            catalog_mechanically_verified=True,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["resolution_status"], "readback_mismatch")

    def test_serialized_self_attested_catalog_cannot_launch(self) -> None:
        result = resolve_execution_model(live_catalog())
        self.assertEqual(result["reason"], "serialized_catalog_unverified")
        self.assertEqual(result["catalog_attestation"], "caller-asserted-unverified")
        self.assertFalse(result["launch_allowed"])


if __name__ == "__main__":
    unittest.main()
