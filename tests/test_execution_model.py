from __future__ import annotations

import sqlite3
import tempfile
import unittest
import sys
import copy
import io
import json
from contextlib import redirect_stdout
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
    def test_policy_defaults_can_change_without_relaxing_safety_requirements(self) -> None:
        policy = execution_model_module.load_policy()
        self.assertEqual((policy["display_model"], policy["reasoning"]), ("GPT-6 Astra", "max"))
        for field, value in (("provider", "external"), ("require_live_catalog", False), ("silent_downgrade_allowed", True), ("fallback", "auto"), ("readback_required", [])):
            changed = copy.deepcopy(policy)
            changed[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "policy is invalid"):
                resolve_execution_model(live_catalog(), policy=changed, catalog_mechanically_verified=True)

    def test_explicit_model_effort_and_legacy_sol_requests_resolve(self) -> None:
        for model_id, display, effort in (
            ("gpt-6-astra", "GPT-6 Astra", "high"),
            ("gpt-5.6-terra", "GPT-5.6 Terra", "medium"),
            ("gpt-5.6-sol", "GPT-5.6 Sol", "ultra"),
            ("host-model-with-none", "Host Model", "none"),
        ):
            for request in (model_id, display):
                with self.subTest(request=request, effort=effort):
                    catalog = live_catalog()
                    catalog["models"] = [{
                        "id": model_id, "display_name": display, "provider": "openai",
                        "supported_reasoning": [effort],
                    }]
                    result = resolve_execution_model(
                        catalog, model_request=request, reasoning_request=effort,
                        catalog_mechanically_verified=True,
                    )
                    self.assertEqual(result["resolved_model_id"], model_id)
                    self.assertEqual(result["resolved_reasoning"], effort)
                    self.assertEqual(result["display_request"], request)
                    self.assertTrue(result["launch_allowed"])
                    self.assertFalse(result["readback_verified"])

    def test_ambiguous_alias_requires_exact_id_and_duplicate_id_fails_closed(self) -> None:
        catalog = live_catalog()
        other = copy.deepcopy(catalog["models"][0])
        other["id"] = "gpt-6-astra-snapshot"
        catalog["models"].append(other)
        result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
        self.assertEqual(result["reason"], "ambiguous_exact_model_id")
        self.assertFalse(result["launch_allowed"])
        result = resolve_execution_model(
            catalog, model_request=other["id"], catalog_mechanically_verified=True
        )
        self.assertEqual(result["resolved_model_id"], other["id"])
        self.assertTrue(result["launch_allowed"])
        catalog["models"].append(copy.deepcopy(other))
        result = resolve_execution_model(
            catalog, model_request=other["id"], catalog_mechanically_verified=True
        )
        self.assertFalse(result["launch_allowed"])

    def test_hidden_unavailable_or_unsupported_default_is_not_launchable(self) -> None:
        for field, value in (("hidden", True), ("available", False), ("isAvailable", False)):
            with self.subTest(field=field):
                catalog = live_catalog()
                catalog["models"][0][field] = value
                result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
                self.assertEqual(result["reason"], "requested_model_unavailable")
                self.assertFalse(result["launch_allowed"])
        catalog = live_catalog(max_effort=False)
        catalog["models"][0]["defaultReasoningEffort"] = "max"
        result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
        self.assertEqual(result["reason"], "requested_reasoning_not_supported")
        self.assertIsNone(result["resolved_reasoning"])

    def test_id_can_resolve_without_display_but_cannot_skip_live_attestation(self) -> None:
        catalog = live_catalog()
        del catalog["models"][0]["display_name"]
        for verified in (False, True):
            result = resolve_execution_model(
                catalog, model_request="gpt-6-astra", catalog_mechanically_verified=verified
            )
            self.assertEqual(result["launch_allowed"], verified)

    def test_cli_preserves_explicit_model_and_effort(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["resolver", "--model", "gpt-6-astra", "--reasoning-effort", "high"]),
            mock.patch.object(execution_model_module, "live_catalog", return_value=live_catalog()),
            redirect_stdout(output),
        ):
            execution_model_module.main()
        result = json.loads(output.getvalue())
        self.assertEqual((result["resolved_model_id"], result["resolved_reasoning"]), ("gpt-6-astra", "high"))

    def test_each_actual_identity_mismatch_fails(self) -> None:
        for field, value in (("provider", "other"), ("actual_model_id", "gpt-5.6-sol"), ("actual_reasoning_effort", "high")):
            with self.subTest(field=field):
                readback = {"provider": "openai", "actual_model_id": "gpt-6-astra", "actual_reasoning_effort": "max"}
                readback[field] = value
                result = resolve_execution_model(live_catalog(), spawn_readback=readback, catalog_mechanically_verified=True)
                self.assertEqual(result["status"], "FAIL")
                self.assertFalse(result["launch_allowed"])

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
                "model": "gpt-6-astra",
                "displayName": "GPT-6-Astra",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "high"},
                    {"reasoningEffort": "max"},
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
        self.assertEqual(resolved["resolved_model_id"], "gpt-6-astra")

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
                            "model": "gpt-6-astra",
                            "displayName": "GPT-6-Astra",
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "max"}
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

    def test_astra_max_effort_resolves_to_live_exact_id(self) -> None:
        result = resolve_execution_model(live_catalog(), catalog_mechanically_verified=True)
        self.assertEqual(result["resolved_model_id"], "gpt-6-astra")
        self.assertEqual(result["resolved_reasoning"], "max")
        self.assertTrue(result["launch_allowed"])

    def test_max_effort_unsupported_requires_user_choice_without_downgrade(self) -> None:
        result = resolve_execution_model(
            live_catalog(max_effort=False), catalog_mechanically_verified=True
        )
        self.assertEqual(result["resolution_status"], "user_choice_required")
        self.assertIsNone(result["resolved_reasoning"])
        self.assertFalse(result["launch_allowed"])
        self.assertEqual(len(result["choices"]), 3)

    def test_missing_astra_is_not_guessed(self) -> None:
        result = resolve_execution_model(
            live_catalog(include_astra=False), catalog_mechanically_verified=True
        )
        self.assertIsNone(result["resolved_model_id"])
        self.assertEqual(result["reason"], "requested_display_model_not_found")

    def test_matching_astra_without_provider_proof_is_not_launchable(self) -> None:
        catalog = live_catalog()
        catalog["models"][0]["provider"] = None
        result = resolve_execution_model(catalog, catalog_mechanically_verified=True)
        self.assertEqual(result["reason"], "requested_provider_unverified")
        self.assertEqual(result["candidate_model_ids"], ["gpt-6-astra"])
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
                "actual_model_id": "gpt-6-astra",
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
