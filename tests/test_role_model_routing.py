from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "resolve_role_route.py"
sys.path.insert(0, str(ROOT / "scripts"))
from resolve_role_route import load_json, resolve_plan, validate_policy  # noqa: E402


class RoleModelRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_json(ROOT / "assets" / "role-model-policy.json")

    def test_policy_maps_all_existing_roles_without_static_models(self) -> None:
        validate_policy(self.policy)
        self.assertEqual(
            set(self.policy["profiles"]),
            {"codebase-researcher", "technical-architect", "developer", "reviewer", "test-debugger"},
        )
        text = json.dumps(self.policy).lower()
        for forbidden in ('"gpt-', '"claude-', '"luna"', '"terra"', '"sol"'):
            self.assertNotIn(forbidden, text)

    def test_policy_rejects_embedded_exact_model_on_role(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["profiles"]["developer"]["model"] = "stale-model-id"
        with self.assertRaisesRegex(ValueError, "profile policy fields are invalid"):
            validate_policy(policy)

    def test_policy_rejects_root_or_advisor_safety_drift(self) -> None:
        for mutate, expected in (
            (lambda policy: policy.__setitem__("root_ownership", "never"), "preserve root ownership"),
            (lambda policy: policy["route_contract"].__setitem__("truth_states", ["confirmed"]), "safety values"),
            (lambda policy: policy["external_advisor"].__setitem__("may_edit", True), "root-facing, and read-only"),
        ):
            with self.subTest(expected=expected):
                policy = json.loads(json.dumps(self.policy))
                mutate(policy)
                with self.assertRaisesRegex(ValueError, expected):
                    validate_policy(policy)

    def test_economy_keeps_required_reviewer_and_returns_other_work_to_root(self) -> None:
        plan = resolve_plan(
            self.policy,
            ["developer", "reviewer", "codebase-researcher"],
            "medium",
            "economy",
            "inherit",
            None,
            None,
        )
        self.assertEqual([item["role"] for item in plan["delegated"]], ["reviewer"])
        self.assertEqual({item["role"] for item in plan["root_owned"]}, {"developer", "codebase-researcher"})
        self.assertLessEqual(plan["relative_cost_units"], plan["limits"]["relative_cost_units"])

    def test_high_risk_escalates_once_and_quality_budget_bounds_parallelism(self) -> None:
        plan = resolve_plan(
            self.policy,
            ["codebase-researcher", "developer", "reviewer"],
            "high",
            "quality",
            "inherit",
            None,
            None,
        )
        classes = {item["role"]: item["model_class"] for item in plan["delegated"]}
        self.assertEqual(classes["codebase-researcher"], "balanced")
        self.assertEqual(classes["developer"], "judgment")
        self.assertEqual(plan["limits"]["auto_upgrades_per_role"], 1)
        self.assertLessEqual(len(plan["delegated"]), plan["limits"]["parallel_roles"])

    def test_direct_route_selects_same_provider_and_requires_fork_none(self) -> None:
        catalog = {
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "test-host-catalog",
                "observed_for_current_task": True,
                "root_provider": "openai",
            },
            "models": [
                {
                    "id": "economical-a",
                    "provider": "openai",
                    "model_class": "efficient",
                    "supported_reasoning": ["medium", "high"],
                    "available": True,
                    "authenticated": True,
                    "relative_cost_units": 1,
                },
                {
                    "id": "other-provider-model",
                    "provider": "other",
                    "model_class": "efficient",
                    "supported_reasoning": ["medium"],
                    "available": True,
                    "authenticated": True,
                    "relative_cost_units": 0,
                },
            ]
        }
        plan = resolve_plan(
            self.policy,
            ["codebase-researcher"],
            "medium",
            "balanced",
            "direct",
            catalog,
            "openai",
        )
        route = plan["delegated"][0]
        self.assertEqual(route["model"], "economical-a")
        self.assertEqual(route["provider"], "openai")
        self.assertEqual(route["fork_turns"], "none")
        self.assertEqual(route["route_state"], "planned-unverified")
        self.assertFalse(plan["claims"]["catalog_provenance_confirmed"])
        self.assertFalse(plan["claims"]["accepted"])
        self.assertFalse(plan["claims"]["confirmed"])

    def test_missing_exact_route_falls_back_without_false_confirmation(self) -> None:
        plan = resolve_plan(
            self.policy,
            ["reviewer"],
            "critical",
            "quality",
            "direct",
            {
                "provenance": {
                    "source": "active-host-catalog",
                    "source_id": "empty-current-catalog",
                    "observed_for_current_task": True,
                    "root_provider": "openai",
                },
                "models": [],
            },
            "openai",
        )
        route = plan["delegated"][0]
        self.assertEqual(plan["status"], "plan-only-with-fallback")
        self.assertEqual(route["route_state"], "unavailable")
        self.assertIsNone(route["model"])
        self.assertFalse(plan["claims"]["confirmed"])

    def test_custom_agent_requires_authenticated_provider(self) -> None:
        catalog = {
            "provenance": {
                "source": "loaded-custom-agent",
                "source_id": "test-loaded-agent",
                "observed_for_current_task": True,
                "root_provider": None,
            },
            "models": [
                {
                    "id": "judgment-model",
                    "provider": "external",
                    "model_class": "judgment",
                    "supported_reasoning": ["high", "xhigh"],
                    "available": True,
                    "authenticated": False,
                    "loaded": True,
                    "provider_pinned": True,
                    "agent_type": "reviewer_external",
                }
            ]
        }
        plan = resolve_plan(
            self.policy,
            ["reviewer"],
            "medium",
            "balanced",
            "custom-agent",
            catalog,
            None,
        )
        self.assertEqual(plan["delegated"][0]["route_state"], "unavailable")

    def test_loaded_provider_pinned_custom_agent_is_planned_by_agent_type(self) -> None:
        catalog = {
            "provenance": {
                "source": "loaded-custom-agent",
                "source_id": "loaded-reviewer-readback",
                "observed_for_current_task": True,
                "root_provider": None,
            },
            "models": [
                {
                    "id": "review-model",
                    "provider": "external",
                    "model_class": "judgment",
                    "supported_reasoning": ["high", "xhigh"],
                    "available": True,
                    "authenticated": True,
                    "loaded": True,
                    "provider_pinned": True,
                    "agent_type": "external_reviewer",
                }
            ],
        }
        plan = resolve_plan(
            self.policy,
            ["reviewer"],
            "medium",
            "balanced",
            "custom-agent",
            catalog,
            None,
        )
        route = plan["delegated"][0]
        self.assertEqual(route["agent_type"], "external_reviewer")
        self.assertEqual(route["route_state"], "planned-unverified")
        self.assertFalse(plan["claims"]["accepted"])

    def test_exact_route_rejects_catalog_without_current_task_provenance(self) -> None:
        with self.assertRaisesRegex(ValueError, "catalog fields must be exactly"):
            resolve_plan(
                self.policy,
                ["reviewer"],
                "medium",
                "balanced",
                "direct",
                {"models": []},
                "openai",
            )

    def test_parallel_limit_is_enforced_independently(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["budget_modes"]["quality"]["max_parallel_roles"] = 1
        plan = resolve_plan(
            policy,
            ["codebase-researcher", "developer", "reviewer"],
            "medium",
            "quality",
            "inherit",
            None,
            None,
        )
        self.assertEqual(len(plan["delegated"]), 1)
        self.assertEqual(len(plan["root_owned"]), 2)

    def test_cli_human_output_hides_backstage_route_fields(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--roles",
                "developer,reviewer",
                "--budget",
                "balanced",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("采用平衡配置", result.stdout)
        for forbidden in ("provider", "reasoning", "fork_turns", "relative_cost_units", "{"):
            self.assertNotIn(forbidden, result.stdout)

    def test_cli_rejects_direct_route_without_root_provider(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--roles",
                "developer",
                "--route-mode",
                "direct",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --root-provider", result.stderr)


if __name__ == "__main__":
    unittest.main()
