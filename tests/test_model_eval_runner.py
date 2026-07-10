from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_model_evals as runner  # noqa: E402


class ModelEvalRunnerTests(unittest.TestCase):
    def base_case(self) -> dict[str, object]:
        return {
            "id": "safe-case",
            "prompt": "read only",
            "should_trigger": True,
            "mode": "direct",
            "collaboration": "none",
            "activation": "explicit",
            "model_smoke": True,
        }

    def test_isolated_env_drops_parent_secrets(self) -> None:
        env = runner.build_isolated_env(
            Path("/tmp/eval-home"),
            Path("/tmp/eval-codex"),
            {
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "OPENAI_API_KEY": "secret-api-key",
                "AWS_SECRET_ACCESS_KEY": "secret-aws-key",
                "SENTINEL_TOKEN": "secret-sentinel",
            },
        )
        self.assertEqual(env["PATH"], "/usr/bin:/bin")
        self.assertEqual(env["HOME"], "/tmp/eval-home")
        self.assertEqual(env["CODEX_HOME"], "/tmp/eval-codex")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("SENTINEL_TOKEN", env)

    def test_runtime_case_rejects_unsafe_inputs(self) -> None:
        unsafe_sandbox = self.base_case()
        unsafe_sandbox["sandbox"] = "danger-full-access"
        with self.assertRaisesRegex(RuntimeError, "unsafe sandbox"):
            runner.validate_runtime_case(unsafe_sandbox)

        unsafe_id = self.base_case()
        unsafe_id["id"] = "../../escape"
        with self.assertRaisesRegex(RuntimeError, "unsafe behavior case id"):
            runner.validate_runtime_case(unsafe_id)

        unsafe_file = self.base_case()
        unsafe_file.update({"expected_file": "../outside", "expected_text": "x"})
        with self.assertRaisesRegex(RuntimeError, "escapes the fixture"):
            runner.validate_runtime_case(unsafe_file)

    def test_review_requires_completed_wait_message(self) -> None:
        spawn = {
            "type": "item.completed",
            "item": {
                "id": "spawn",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "completed",
                "sender_thread_id": "main",
                "receiver_thread_ids": ["reviewer"],
                "prompt": "AGENCY_WORKER: true Goal: inspect README.md Read scope: git diff",
            },
        }
        without_wait = runner.event_surface(json.dumps(spawn), "done")
        self.assertEqual(without_wait["reviews_completed"], {})

        wait = {
            "type": "item.completed",
            "item": {
                "id": "wait",
                "type": "collab_tool_call",
                "tool": "wait",
                "status": "completed",
                "receiver_thread_ids": ["reviewer"],
                "agents_states": {
                    "reviewer": {"status": "completed", "message": "README.md diff is correct"}
                },
            },
        }
        events = "\n".join((json.dumps(spawn), json.dumps(wait)))
        completed = runner.event_surface(events, "done")["reviews_completed"]
        self.assertIn("reviewer", completed)

    def test_artifact_review_prompt_does_not_require_diff_keyword(self) -> None:
        prompt = (
            "AGENCY_WORKER: true\n"
            "委派目标：核对 README.md 已更新。\n"
            "读取范围：README.md。\n"
            "写入范围：无。\n"
            "期望产物：Repository name: agency-model-eval-fixture-v2.\n"
            "验证要求：读回文件内容。\n"
            "停止条件：完成只读检查后返回。"
        )
        self.assertTrue(
            runner.review_prompt_is_self_contained(
                prompt,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
            )
        )
        self.assertFalse(
            runner.review_prompt_is_self_contained(
                prompt.replace("agency-model-eval-fixture-v2", "wrong-value"),
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
            )
        )

    def test_failed_command_does_not_count_as_tool_evidence(self) -> None:
        event = {
            "type": "item.completed",
            "item": {
                "id": "cmd",
                "type": "command_execution",
                "status": "completed",
                "exit_code": 1,
            },
        }
        parsed = runner.event_surface(json.dumps(event), "done")
        self.assertEqual(parsed["tool_events"], 0)

    def test_contract_uses_trigger_mode_and_collaboration_fields(self) -> None:
        case = self.base_case()
        failures = runner.contract_failures(
            case,
            "COS_BOOT_RECEIPT：已接管；模式：结构化；协作：原生子代理。",
        )
        self.assertTrue(any("模式：直接" in failure for failure in failures))
        self.assertTrue(any("协作：无" in failure for failure in failures))

    def test_partial_success_cannot_be_full_pass(self) -> None:
        passed = [{"status": "passed"}]
        self.assertEqual(runner.receipt_status(False, passed), "passed_partial")
        self.assertEqual(runner.receipt_status(True, passed), "passed")
        self.assertEqual(runner.receipt_status(True, []), "failed")

    def test_release_eligibility_distinguishes_rc_from_stable(self) -> None:
        prerelease, stable = runner.release_eligibility(
            "passed",
            True,
            True,
            "primary",
            ["cold_review_context_isolation"],
        )
        self.assertFalse(prerelease)
        self.assertFalse(stable)
        dedicated_prerelease, dedicated_stable = runner.release_eligibility(
            "passed",
            True,
            True,
            "dedicated",
            ["cold_review_context_isolation"],
        )
        self.assertTrue(dedicated_prerelease)
        self.assertFalse(dedicated_stable)

    def test_required_smoke_suite_cannot_be_weakened(self) -> None:
        cases = json.loads(
            (ROOT / "evals" / "behavior_cases.json").read_text(encoding="utf-8")
        )
        validated = [runner.validate_runtime_case(case) for case in cases]
        self.assertGreaterEqual(
            len(runner.validate_smoke_suite(validated)),
            len(runner.REQUIRED_SMOKE_CONTRACT),
        )
        weakened = [
            case for case in validated if case["id"] != "ordinary-readiness-phrase"
        ]
        with self.assertRaisesRegex(RuntimeError, "missing required cases"):
            runner.validate_smoke_suite(weakened)

    def test_exact_auth_values_are_redacted(self) -> None:
        text, leaked = runner.redact_exact_auth_values(
            "token=0123456789abcdef", {"0123456789abcdef"}
        )
        self.assertTrue(leaked)
        self.assertNotIn("0123456789abcdef", text)

    def test_auth_source_read_is_regular_and_nofollow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            regular = base / "auth.json"
            regular.write_bytes(b'{"auth": "fixture"}\n')
            self.assertEqual(
                runner.read_regular_nofollow(regular),
                b'{"auth": "fixture"}\n',
            )
            symlink = base / "auth-link.json"
            symlink.symlink_to(regular)
            with self.assertRaisesRegex(RuntimeError, "cannot safely open"):
                runner.read_regular_nofollow(symlink)

    def test_cli_rejects_empty_smoke_set_without_calling_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "package"
            (root / "evals").mkdir(parents=True)
            (root / "evals" / "behavior_cases.json").write_text("[]\n", encoding="utf-8")
            auth = base / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_model_evals.py"),
                    "--root",
                    str(root),
                    "--out",
                    str(base / "output"),
                    "--auth-json",
                    str(auth),
                    "--acknowledge-auth-readable-to-eval-process",
                    "--auth-credential-class",
                    "primary",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required cases", result.stderr)


if __name__ == "__main__":
    unittest.main()
