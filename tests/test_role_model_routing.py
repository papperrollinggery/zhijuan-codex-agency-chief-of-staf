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
from resolve_role_route import (  # noqa: E402
    _issue_live_catalog_attestation,
    load_json,
    resolve_plan,
    validate_policy,
)


class RoleModelRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_json(ROOT / "assets" / "role-model-policy.json")

    def test_policy_maps_all_existing_roles_without_static_models(self) -> None:
        validate_policy(self.policy)
        self.assertEqual(
            set(self.policy["profiles"]),
            {
                "codebase-researcher",
                "technical-architect",
                "developer",
                "writer",
                "reviewer",
                "test-debugger",
                "supervisor",
            },
        )
        routing_core = dict(self.policy)
        routing_core.pop("external_advisor")
        text = json.dumps(routing_core).lower()
        for forbidden in ('"gpt-', '"claude-', '"luna"', '"terra"', '"sol"'):
            self.assertNotIn(forbidden, text)

    def test_policy_rejects_embedded_exact_model_on_role(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["profiles"]["developer"]["model"] = "stale-model-id"
        with self.assertRaisesRegex(ValueError, "profile policy fields are invalid"):
            validate_policy(policy)

    def test_policy_rejects_profile_set_drift(self) -> None:
        for mutation in ("extra", "missing"):
            with self.subTest(mutation=mutation):
                policy = json.loads(json.dumps(self.policy))
                if mutation == "extra":
                    policy["profiles"]["arbitrary-role"] = dict(
                        policy["profiles"]["developer"]
                    )
                else:
                    policy["profiles"].pop("writer")
                with self.assertRaisesRegex(ValueError, "exactly the seven"):
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

    def test_economy_never_auto_upgrades_model_class_or_reasoning(self) -> None:
        for risk in ("high", "critical"):
            with self.subTest(risk=risk):
                plan = resolve_plan(
                    self.policy,
                    ["codebase-researcher"],
                    risk,
                    "economy",
                    "inherit",
                    None,
                    None,
                )
                self.assertEqual(plan["limits"]["auto_upgrades_per_role"], 0)
                delegated = plan["delegated"][0]
                self.assertEqual(delegated["model_class"], "efficient")
                self.assertEqual(delegated["reasoning"], "medium")

    def test_policy_rejects_more_than_one_automatic_upgrade(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["budget_modes"]["quality"]["max_auto_upgrades_per_role"] = 2
        with self.assertRaisesRegex(ValueError, "zero or one"):
            validate_policy(policy)

        for value in (True, False):
            with self.subTest(value=value):
                policy = json.loads(json.dumps(self.policy))
                policy["budget_modes"]["quality"][
                    "max_auto_upgrades_per_role"
                ] = value
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    validate_policy(policy)

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
        reasoning = {item["role"]: item["reasoning"] for item in plan["delegated"]}
        self.assertEqual(reasoning["codebase-researcher"], "medium")
        self.assertEqual(reasoning["developer"], "high")
        self.assertEqual(reasoning["reviewer"], "high")
        self.assertEqual(plan["limits"]["auto_upgrades_per_role"], 1)
        self.assertEqual(len(plan["delegated"]), 3)
        self.assertEqual([item["dispatch_wave"] for item in plan["delegated"]], [1, 1, 1])
        self.assertLessEqual(
            sum(item["dispatch_wave"] == 1 for item in plan["delegated"]),
            plan["limits"]["parallel_roles"],
        )

        critical = resolve_plan(
            self.policy,
            ["codebase-researcher", "developer", "reviewer"],
            "critical",
            "quality",
            "inherit",
            None,
            None,
        )
        critical_reasoning = {
            item["role"]: item["reasoning"] for item in critical["delegated"]
        }
        self.assertEqual(critical_reasoning["codebase-researcher"], "high")
        self.assertEqual(critical_reasoning["developer"], "xhigh")
        self.assertEqual(critical_reasoning["reviewer"], "xhigh")

    def test_direct_route_selects_same_provider_and_requires_fork_none(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "test-host-catalog",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": True,
                "model_provider_evidence": "root-state-inferred",
            },
            "models": [
                {
                    "id": "economical-a",
                    "provider": "openai",
                    "model_class": "efficient",
                    "supported_reasoning": ["medium", "high"],
                    "available": True,
                    "provider_evidence": "root-state-inferred",
                    "authenticated": True,
                    "relative_cost_units": 1,
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
            _issue_live_catalog_attestation(catalog),
        )
        route = plan["delegated"][0]
        self.assertEqual(route["model"], "economical-a")
        self.assertEqual(route["provider"], "openai")
        self.assertEqual(route["fork_turns"], "none")
        self.assertEqual(route["route_state"], "planned")
        self.assertTrue(plan["claims"]["catalog_provenance_locally_consistent"])
        self.assertFalse(plan["claims"]["catalog_provenance_confirmed"])
        self.assertEqual(
            route["dispatch_contract"],
            {
                "namespace": "agents",
                "arguments": {
                    "model": "economical-a",
                    "reasoning_effort": "medium",
                    "fork_turns": "none",
                },
            },
        )
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
                "schema_version": 2,
                "provenance": {
                    "source": "active-host-catalog",
                    "source_id": "empty-current-catalog",
                    "observed_for_requested_thread": True,
                    "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                    "root_provider": "openai",
                    "canonical_state_store_bound": True,
                    "model_provider_evidence": "root-state-inferred",
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
            "schema_version": 2,
            "provenance": {
                "source": "loaded-custom-agent",
                "source_id": "test-loaded-agent",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": False,
                "model_provider_evidence": "loaded-custom-agent-readback",
            },
            "models": [
                {
                    "id": "judgment-model",
                    "provider": "openai",
                    "model_class": "judgment",
                    "supported_reasoning": ["high", "xhigh"],
                    "available": True,
                    "provider_evidence": "loaded-custom-agent-readback",
                    "authenticated": False,
                    "loaded": True,
                    "provider_pinned": True,
                    "agent_type": "reviewer",
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

    def test_loaded_custom_agent_stays_unverified_without_mechanical_attestor(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "loaded-custom-agent",
                "source_id": "loaded-reviewer-readback",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": False,
                "model_provider_evidence": "loaded-custom-agent-readback",
            },
            "models": [
                {
                    "id": "review-model",
                    "provider": "openai",
                    "model_class": "judgment",
                    "supported_reasoning": ["high", "xhigh"],
                    "available": True,
                    "provider_evidence": "loaded-custom-agent-readback",
                    "authenticated": True,
                    "loaded": True,
                    "provider_pinned": True,
                    "agent_type": "reviewer",
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
        self.assertIsNone(route["agent_type"])
        self.assertEqual(route["route_state"], "planned-unverified")
        self.assertIsNone(route["dispatch_contract"])
        self.assertFalse(plan["claims"]["accepted"])

    def test_unattested_catalog_never_emits_executable_dispatch_contract(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "self-asserted",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": True,
                "model_provider_evidence": "root-state-inferred",
            },
            "models": [
                {
                    "id": "self-asserted-writer",
                    "provider": "openai",
                    "model_class": "balanced",
                    "supported_reasoning": ["medium"],
                    "available": True,
                    "provider_evidence": "root-state-inferred",
                }
            ],
        }
        plan = resolve_plan(
            self.policy,
            ["writer"],
            "medium",
            "balanced",
            "direct",
            catalog,
            "openai",
        )
        route = plan["delegated"][0]
        self.assertEqual(route["route_state"], "planned-unverified")
        self.assertIsNone(route["dispatch_contract"])
        self.assertFalse(plan["claims"]["catalog_live_readback_verified"])
        self.assertFalse(plan["claims"]["catalog_provenance_locally_consistent"])

    def test_external_or_wrong_role_custom_agent_is_rejected_from_core_route(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "loaded-custom-agent",
                "source_id": "external-write-agent",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": False,
                "model_provider_evidence": "loaded-custom-agent-readback",
            },
            "models": [
                {
                    "id": "external-developer-model",
                    "provider": "external",
                    "provider_evidence": "loaded-custom-agent-readback",
                    "model_class": "balanced",
                    "supported_reasoning": ["medium"],
                    "available": True,
                    "authenticated": True,
                    "loaded": True,
                    "provider_pinned": True,
                    "agent_type": "developer",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "OpenAI provider"):
            resolve_plan(
                self.policy,
                ["developer"],
                "medium",
                "balanced",
                "custom-agent",
                catalog,
                None,
            )
        catalog["models"][0].update(
            id="openai-wrong-role",
            provider="openai",
            agent_type="writer",
        )
        plan = resolve_plan(
            self.policy,
            ["developer"],
            "medium",
            "balanced",
            "custom-agent",
            catalog,
            None,
        )
        self.assertEqual(plan["delegated"][0]["route_state"], "unavailable")

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
        self.assertEqual(len(plan["delegated"]), 3)
        self.assertEqual(len(plan["root_owned"]), 0)
        self.assertEqual([item["dispatch_wave"] for item in plan["delegated"]], [1, 2, 3])

    def test_catalog_schema_rejects_malformed_unselected_record(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "test-host-catalog",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": True,
                "model_provider_evidence": "root-state-inferred",
            },
            "models": [
                {
                    "id": "usable-efficient",
                    "provider": "openai",
                    "model_class": "efficient",
                    "supported_reasoning": ["medium"],
                    "available": True,
                    "provider_evidence": "root-state-inferred",
                },
                {
                    "id": "malformed-unselected",
                    "provider": "openai",
                    "model_class": "judgment",
                    "supported_reasoning": ["high"],
                    "available": "false",
                    "provider_evidence": "root-state-inferred",
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "availability is invalid"):
            resolve_plan(
                self.policy,
                ["codebase-researcher"],
                "medium",
                "balanced",
                "direct",
                catalog,
                "openai",
            )

    def test_catalog_schema_rejects_unknown_enums_duplicates_and_bad_route_fields(self) -> None:
        base = {
            "schema_version": 2,
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "test-host-catalog",
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": True,
                "model_provider_evidence": "root-state-inferred",
            },
            "models": [
                {
                    "id": "model-a",
                    "provider": "openai",
                    "model_class": "efficient",
                    "supported_reasoning": ["medium"],
                    "available": True,
                    "provider_evidence": "root-state-inferred",
                }
            ],
        }
        mutations = (
            ("model class", lambda item: item.update(model_class="mystery")),
            ("supported_reasoning", lambda item: item.update(supported_reasoning=["turbo"])),
            ("contains duplicates", lambda item: item.update(supported_reasoning=["medium", "medium"])),
            ("authenticated", lambda item: item.update(authenticated="yes")),
        )
        for expected, mutate in mutations:
            with self.subTest(expected=expected):
                catalog = json.loads(json.dumps(base))
                mutate(catalog["models"][0])
                with self.assertRaisesRegex(ValueError, expected):
                    resolve_plan(
                        self.policy,
                        ["codebase-researcher"],
                        "medium",
                        "balanced",
                        "direct",
                        catalog,
                        "openai",
                    )

        duplicated = json.loads(json.dumps(base))
        duplicated["models"].append(json.loads(json.dumps(duplicated["models"][0])))
        with self.assertRaisesRegex(ValueError, "duplicated"):
            resolve_plan(
                self.policy,
                ["codebase-researcher"],
                "medium",
                "balanced",
                "direct",
                duplicated,
                "openai",
            )

    def test_policy_rejects_parallel_limit_above_total_delegation(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["budget_modes"]["balanced"]["max_parallel_roles"] = 4
        with self.assertRaisesRegex(ValueError, "parallel role limit"):
            validate_policy(policy)

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

    def test_cli_rejects_symlink_policy_and_catalog_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            policy_link = directory / "policy.json"
            policy_link.symlink_to(ROOT / "assets" / "role-model-policy.json")
            policy_result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--roles",
                    "reviewer",
                    "--policy",
                    str(policy_link),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(policy_result.returncode, 0)
            self.assertIn("regular file", policy_result.stderr)

            policy_copy = directory / "policy-copy.json"
            policy_copy.write_bytes(
                (ROOT / "assets" / "role-model-policy.json").read_bytes()
            )
            policy_hardlink = directory / "policy-hardlink.json"
            policy_hardlink.hardlink_to(policy_copy)
            with self.assertRaisesRegex(ValueError, "single regular file"):
                load_json(policy_hardlink)

            catalog_target = directory / "catalog-target.json"
            catalog_target.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provenance": {
                            "source": "active-host-catalog",
                            "source_id": "test",
                            "observed_for_requested_thread": True,
                            "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                            "root_provider": "openai",
                            "canonical_state_store_bound": True,
                            "model_provider_evidence": "root-state-inferred",
                        },
                        "models": [],
                    }
                ),
                encoding="utf-8",
            )
            catalog_link = directory / "catalog.json"
            catalog_link.symlink_to(catalog_target)
            catalog_result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--roles",
                    "reviewer",
                    "--route-mode",
                    "direct",
                    "--root-provider",
                    "openai",
                    "--catalog",
                    str(catalog_link),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(catalog_result.returncode, 0)
            self.assertIn("regular file", catalog_result.stderr)


if __name__ == "__main__":
    unittest.main()
