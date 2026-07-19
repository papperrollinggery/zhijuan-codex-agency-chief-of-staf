from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, live_catalog

sys.path.insert(0, str(ROOT / "scripts"))
from resolve_execution_model import resolve_execution_model  # noqa: E402


class ExecutionModelTests(unittest.TestCase):
    def test_sol_ultra_resolves_to_live_exact_id(self) -> None:
        result = resolve_execution_model(live_catalog())
        self.assertEqual(result["resolved_model_id"], "gpt-5.6-sol")
        self.assertEqual(result["resolved_reasoning"], "ultra")
        self.assertTrue(result["launch_allowed"])

    def test_ultra_unsupported_requires_user_choice_without_downgrade(self) -> None:
        result = resolve_execution_model(live_catalog(ultra=False))
        self.assertEqual(result["resolution_status"], "user_choice_required")
        self.assertIsNone(result["resolved_reasoning"])
        self.assertFalse(result["launch_allowed"])
        self.assertEqual(len(result["choices"]), 3)

    def test_missing_sol_is_not_guessed(self) -> None:
        result = resolve_execution_model(live_catalog(include_sol=False))
        self.assertIsNone(result["resolved_model_id"])
        self.assertEqual(result["reason"], "requested_display_model_not_found")

    def test_non_live_catalog_is_rejected(self) -> None:
        catalog = live_catalog()
        catalog["live_readback_verified"] = False
        result = resolve_execution_model(catalog)
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
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["resolution_status"], "readback_mismatch")


if __name__ == "__main__":
    unittest.main()
