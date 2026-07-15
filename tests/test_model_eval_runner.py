from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_model_evals as runner  # noqa: E402
import run_profile_compat  # noqa: E402


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

    def test_evaluated_codex_kills_descendants_on_success_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fake = base / "fake-codex"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, subprocess, sys, time\n"
                "child = (\"import pathlib,sys,time; time.sleep(0.35); \"\n"
                "         \"pathlib.Path(sys.argv[1]).write_text('survived')\")\n"
                "subprocess.Popen([sys.executable, '-c', child, sys.argv[2]], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                "if sys.argv[1] == 'timeout': time.sleep(10)\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            for mode, should_timeout in (("success", False), ("timeout", True)):
                with self.subTest(mode=mode):
                    sentinel = base / f"{mode}-descendant-survived"
                    completed, timed_out = runner.run_evaluated_codex(
                        [str(fake), mode, str(sentinel)],
                        timeout=0.1 if should_timeout else 2,
                        env=os.environ.copy(),
                    )
                    self.assertEqual(timed_out, should_timeout)
                    self.assertIsNotNone(completed.returncode)
                    time.sleep(0.5)
                    self.assertFalse(sentinel.exists())

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
        self.assertEqual(env["PATH"], runner.EVAL_TOOL_PATH)
        self.assertEqual(env["HOME"], "/tmp/eval-home")
        self.assertEqual(env["CODEX_HOME"], "/tmp/eval-codex")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("SENTINEL_TOKEN", env)

    def test_codex_executable_requires_an_absolute_regular_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "codex"
            executable.write_bytes(b"MZ\x00\x00")
            executable.chmod(0o700)
            self.assertEqual(
                runner.resolve_codex_executable(str(executable)), executable.resolve()
            )
            self.assertEqual(
                runner.sha256_regular_nofollow(executable),
                runner.sha256_bytes(executable.read_bytes()),
            )
            with self.assertRaisesRegex(RuntimeError, "required"):
                runner.resolve_codex_executable(None)
            with self.assertRaisesRegex(RuntimeError, "absolute path"):
                runner.resolve_codex_executable("codex")
            link = Path(tmp) / "codex-link"
            link.symlink_to(executable)
            with self.assertRaisesRegex(RuntimeError, "non-symlink"):
                runner.resolve_codex_executable(str(link))
            script = Path(tmp) / "shell-wrapper"
            script.write_text("#!/bin/sh\n", encoding="utf-8")
            script.chmod(0o700)
            with self.assertRaisesRegex(RuntimeError, "native executable format"):
                runner.resolve_codex_executable(str(script))

    def test_reads_isolated_session_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture"
            fixture.mkdir()
            rollout = root / "codex" / "sessions" / "2026" / "07" / "run.jsonl"
            rollout.parent.mkdir(parents=True)
            records = [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "019f57b8-6477-76d0-ae82-0e7b39a3ae6b",
                        "cwd": str(fixture.resolve()),
                        "model_provider": "openai",
                    },
                },
                {
                    "type": "turn_context",
                    "payload": {
                        "turn_id": "turn-1",
                        "cwd": str(fixture.resolve()),
                        "model": "gpt-5.6-sol",
                        "effort": "max",
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": "turn-1"},
                },
            ]
            rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                runner.observed_execution_identity(root / "codex", fixture),
                {
                    "models": ["gpt-5.6-sol"],
                    "providers": ["openai"],
                    "reasoning_efforts": ["max"],
                    "thread_ids": ["019f57b8-6477-76d0-ae82-0e7b39a3ae6b"],
                    "session_count": 1,
                    "turn_count": 1,
                    "task_complete_count": 1,
                    "parse_errors": 0,
                    "session_observations": [
                        {
                            "providers": ["openai"],
                            "models": ["gpt-5.6-sol"],
                            "reasoning_efforts": ["max"],
                            "thread_ids": [
                                "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
                            ],
                            "session_count": 1,
                            "turn_count": 1,
                            "task_complete_count": 1,
                            "context_turn_ids": ["turn-1"],
                            "completion_turn_ids": ["turn-1"],
                            "parse_errors": 0,
                        }
                    ],
                },
            )

    def test_root_identity_allows_separately_observed_child_session(self) -> None:
        root_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
        root = {
            "providers": ["openai"],
            "models": ["gpt-5.6-sol"],
            "reasoning_efforts": ["max"],
            "thread_ids": [root_id],
            "session_count": 1,
            "turn_count": 1,
            "task_complete_count": 1,
            "context_turn_ids": ["turn-root"],
            "completion_turn_ids": ["turn-root"],
            "parse_errors": 0,
        }
        child = {
            **root,
            "thread_ids": ["019f57ba-4b5d-76a2-bfe9-93cc7f0403c7"],
            "context_turn_ids": ["turn-child"],
            "completion_turn_ids": ["turn-child"],
        }
        identity = {"session_observations": [root, child]}
        self.assertTrue(
            runner.execution_identity_matches(identity, "gpt-5.6-sol", "max", root_id)
        )
        self.assertFalse(
            runner.execution_identity_matches(
                identity,
                "gpt-5.6-sol",
                "max",
                "019f57bc-0000-7000-8000-000000000000",
            )
        )
    def test_source_git_state_binds_head_and_worktree_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            (root / "tracked.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
            clean = runner.source_git_state(root)
            self.assertEqual(clean["available"], True)
            self.assertEqual(clean["worktree_dirty"], False)
            self.assertTrue(str(clean["head"]))
            (root / "tracked.txt").write_text("two\n", encoding="utf-8")
            dirty = runner.source_git_state(root)
            self.assertEqual(dirty["available"], True)
            self.assertEqual(dirty["head"], clean["head"])
            self.assertEqual(dirty["worktree_dirty"], True)
            self.assertNotEqual(dirty["worktree_status_sha256"], clean["worktree_status_sha256"])

    def test_source_git_state_does_not_execute_local_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Eval Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "eval@example.invalid",
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
            observed = runner.source_git_state(root)
            self.assertFalse(sentinel.exists())
            self.assertTrue(observed["available"])
            self.assertTrue(observed["worktree_dirty"])
            self.assertTrue(observed["fsmonitor_disabled"])
            self.assertTrue(observed["lazy_fetch_disabled"])

    def test_hardened_git_ignores_replace_refs_for_head_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "scripts").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Replace Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "replace@example.invalid",
                ],
                check=True,
            )
            source = root / "scripts" / "a.py"
            source.write_text("print('trusted')\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "scripts/a.py"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "trusted"], check=True
            )
            trusted = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            source.write_text("print('replacement')\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "commit", "-qam", "replacement"], check=True)
            replacement = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "-C", str(root), "replace", trusted, replacement], check=True
            )
            subprocess.run(
                ["git", "-C", str(root), "reset", "--hard", "-q", trusted], check=True
            )
            self.assertEqual(source.read_text(encoding="utf-8"), "print('replacement')\n")
            ordinary = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ordinary.stdout, "")
            observed = runner.hardened_git_observation(root)
            self.assertEqual(observed["head"], trusted)
            self.assertTrue(bytes(observed["status_bytes"]).strip())
            self.assertTrue(observed["replace_objects_disabled"])
            self.assertEqual(
                runner.require_hardened_git(
                    root,
                    ["cat-file", "blob", "HEAD:scripts/a.py"],
                    "trusted HEAD read",
                ),
                b"print('trusted')\n",
            )

    def test_source_git_state_fails_closed_on_executable_clean_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Eval Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "eval@example.invalid",
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
            info_attributes = root / ".git" / "info" / "attributes"
            info_attributes.write_text("artifact.txt filter=hostile\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "executable clean filter"):
                runner.source_git_state(root)

    def test_source_git_state_rejects_non_git_and_unsupported_safe_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "Git worktree"):
                runner.source_git_state(Path(tmp))
        unsupported = subprocess.CompletedProcess(
            args=["git", "--no-lazy-fetch"],
            returncode=129,
            stdout=b"",
            stderr=b"unknown option: --no-lazy-fetch\n",
        )
        with mock.patch.object(runner, "run_hardened_git", return_value=unsupported):
            with self.assertRaisesRegex(RuntimeError, "unknown option"):
                runner.source_git_state(Path("/tmp/reviewed-checkout"))

    def test_fixture_git_ignores_host_templates_hooks_and_fsmonitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture = base / "fixture"
            fixture.mkdir()
            (fixture / "README.md").write_text("before\n", encoding="utf-8")
            payload = fixture / ".agents" / "payload.txt"
            payload.parent.mkdir()
            payload.write_text("fixture\n", encoding="utf-8")

            sentinel = base / "host-hook-ran"
            hostile_template = base / "hostile-template"
            template_hooks = hostile_template / "hooks"
            template_hooks.mkdir(parents=True)
            template_hook = template_hooks / "pre-commit"
            template_hook.write_text(
                f"#!/bin/sh\ntouch {sentinel}\n", encoding="utf-8"
            )
            template_hook.chmod(0o700)
            hostile_hooks = base / "hostile-hooks"
            hostile_hooks.mkdir()
            global_hook = hostile_hooks / "pre-commit"
            global_hook.write_text(
                f"#!/bin/sh\ntouch {sentinel}\n", encoding="utf-8"
            )
            global_hook.chmod(0o700)
            global_config = base / "hostile.gitconfig"
            global_config.write_text(
                "[init]\n"
                f"\ttemplateDir = {hostile_template}\n"
                "[core]\n"
                f"\thooksPath = {hostile_hooks}\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}, clear=False
            ):
                runner.initialize_fixture_repository(fixture)
            self.assertFalse(sentinel.exists())
            self.assertFalse((fixture / ".git" / "hooks" / "pre-commit").exists())
            self.assertEqual(runner.changed_paths(fixture), set())

            fsmonitor_sentinel = base / "fsmonitor-ran"
            fsmonitor = base / "fsmonitor.sh"
            fsmonitor.write_text(
                f"#!/bin/sh\ntouch {fsmonitor_sentinel}\nprintf '0\\n'\n",
                encoding="utf-8",
            )
            fsmonitor.chmod(0o700)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(fixture),
                    "config",
                    "core.fsmonitor",
                    str(fsmonitor),
                ],
                check=True,
            )
            (fixture / "README.md").write_text("after\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(fixture), "status", "--porcelain=v1"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(fsmonitor_sentinel.exists())
            fsmonitor_sentinel.unlink()
            self.assertEqual(runner.changed_paths(fixture), {"README.md"})
            self.assertFalse(fsmonitor_sentinel.exists())

    def test_fixture_manifest_detects_committed_scope_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            fixture.mkdir()
            (fixture / "README.md").write_text("before\n", encoding="utf-8")
            payload = fixture / ".agents" / "payload.txt"
            payload.parent.mkdir()
            payload.write_text("fixture\n", encoding="utf-8")
            runner.initialize_fixture_repository(fixture)
            baseline_manifest = runner.fixture_file_manifest(fixture)
            baseline_head = runner.hardened_git_observation(fixture)["head"]

            (fixture / "committed-extra.txt").write_text("escape\n", encoding="utf-8")
            runner.require_hardened_git(
                fixture,
                ["-c", "core.hooksPath=/dev/null", "add", "--", "committed-extra.txt"],
                "test add",
            )
            runner.require_hardened_git(
                fixture,
                ["-c", "core.hooksPath=/dev/null", "commit", "-qm", "scope escape"],
                "test commit",
            )
            (fixture / "README.md").write_text("after\n", encoding="utf-8")
            self.assertEqual(runner.changed_paths(fixture), {"README.md"})
            final_manifest = runner.fixture_file_manifest(fixture)
            final_head = runner.hardened_git_observation(fixture)["head"]
            failures, changed = runner.fixture_scope_failures(
                baseline_manifest,
                final_manifest,
                baseline_head,
                final_head,
                "README.md",
            )
            self.assertEqual(changed, ["README.md", "committed-extra.txt"])
            self.assertTrue(any("manifest scope mismatch" in item for item in failures))
            self.assertTrue(any("HEAD changed" in item for item in failures))

    def test_fixture_manifest_ignores_assume_unchanged_concealment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            fixture.mkdir()
            (fixture / "README.md").write_text("before\n", encoding="utf-8")
            payload = fixture / ".agents" / "payload.txt"
            payload.parent.mkdir()
            payload.write_text("fixture\n", encoding="utf-8")
            runner.initialize_fixture_repository(fixture)
            baseline_manifest = runner.fixture_file_manifest(fixture)
            baseline_head = runner.hardened_git_observation(fixture)["head"]

            runner.require_hardened_git(
                fixture,
                ["update-index", "--assume-unchanged", "--", ".agents/payload.txt"],
                "test assume-unchanged",
            )
            payload.write_text("concealed\n", encoding="utf-8")
            (fixture / "README.md").write_text("after\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "index flags can conceal"):
                runner.hardened_git_observation(fixture)
            failures, changed = runner.fixture_scope_failures(
                baseline_manifest,
                runner.fixture_file_manifest(fixture),
                baseline_head,
                baseline_head,
                "README.md",
            )
            self.assertEqual(changed, [".agents/payload.txt", "README.md"])
            self.assertTrue(any("manifest scope mismatch" in item for item in failures))

    def test_fixture_manifest_ignores_skip_worktree_concealment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "fixture"
            fixture.mkdir()
            (fixture / "README.md").write_text("before\n", encoding="utf-8")
            payload = fixture / ".agents" / "payload.txt"
            payload.parent.mkdir()
            payload.write_text("fixture\n", encoding="utf-8")
            runner.initialize_fixture_repository(fixture)
            baseline_manifest = runner.fixture_file_manifest(fixture)
            baseline_head = runner.hardened_git_observation(fixture)["head"]
            runner.require_hardened_git(
                fixture,
                ["update-index", "--skip-worktree", "--", ".agents/payload.txt"],
                "test skip-worktree",
            )
            payload.write_text("concealed\n", encoding="utf-8")
            (fixture / "README.md").write_text("after\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "index flags can conceal"):
                runner.hardened_git_observation(fixture)
            failures, changed = runner.fixture_scope_failures(
                baseline_manifest,
                runner.fixture_file_manifest(fixture),
                baseline_head,
                baseline_head,
                "README.md",
            )
            self.assertEqual(changed, [".agents/payload.txt", "README.md"])
            self.assertTrue(any("manifest scope mismatch" in item for item in failures))

    def test_fixture_scope_allows_only_new_parents_of_nested_expected_file(self) -> None:
        baseline = {"README.md": "file:644:before"}
        final = {
            "README.md": "file:644:before",
            "reports": "directory:755",
            "reports/current": "directory:755",
            "reports/current/result.md": "file:644:after",
        }
        failures, changed = runner.fixture_scope_failures(
            baseline,
            final,
            "head",
            "head",
            "reports/current/result.md",
        )
        self.assertEqual(failures, [])
        self.assertEqual(
            changed,
            ["reports", "reports/current", "reports/current/result.md"],
        )
        final["reports/unexpected.txt"] = "file:644:extra"
        failures, _changed = runner.fixture_scope_failures(
            baseline,
            final,
            "head",
            "head",
            "reports/current/result.md",
        )
        self.assertTrue(any("manifest scope mismatch" in item for item in failures))

    def test_session_identity_cannot_be_assembled_across_journals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture"
            fixture.mkdir()
            sessions = root / "codex" / "sessions" / "2026" / "07"
            sessions.mkdir(parents=True)
            (sessions / "meta.jsonl").write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "cwd": str(fixture.resolve()),
                            "model_provider": "openai",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (sessions / "turn.jsonl").write_text(
                json.dumps(
                    {
                        "type": "turn_context",
                        "payload": {
                            "cwd": str(fixture.resolve()),
                            "model": "gpt-5.6-sol",
                            "effort": "max",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            observed = runner.observed_execution_identity(root / "codex", fixture)
            self.assertEqual(observed["providers"], ["openai"])
            self.assertEqual(observed["models"], ["gpt-5.6-sol"])
            self.assertEqual(observed["reasoning_efforts"], ["max"])
            self.assertEqual(len(observed["session_observations"]), 2)
            self.assertTrue(
                any(item["session_count"] == 0 for item in observed["session_observations"])
            )
            self.assertTrue(
                any(item["turn_count"] == 0 for item in observed["session_observations"])
            )
            self.assertFalse(
                runner.execution_identity_matches(observed, "gpt-5.6-sol", "max")
            )

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

    def test_runtime_case_rejects_reviewer_target_marker_and_verdict_leaks(self) -> None:
        case = self.base_case()
        case.update(
            {
                "collaboration": "native_subagents",
                "require_collab_event": True,
                "expected_file": "README.md",
                "expected_text": "Repository name: fixture-v2.",
                "expected_file_content": "# fixture\nRepository name: fixture-v2.\n",
                "review_evidence_marker": "# fixture",
            }
        )
        for leaked, error in (
            ("Repository name: fixture-v2.", "expected target"),
            ("# fixture", "evidence marker"),
            ("REVIEW_VERDICT: GO", "reviewer verdict"),
        ):
            leaked_case = dict(case)
            leaked_case["prompt"] = f"reviewer packet: {leaked}"
            with self.assertRaisesRegex(RuntimeError, error):
                runner.validate_runtime_case(leaked_case)

    def test_runtime_case_fails_closed_for_incomplete_cold_review_contract(self) -> None:
        case = self.base_case()
        case.update(
            {
                "collaboration": "native_subagents",
                "require_collab_event": True,
                "expected_file": "README.md",
                "expected_text": "Repository name: fixture-v2.",
                "review_evidence_marker": "# fixture",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "exact expected artifact"):
            runner.validate_runtime_case(case)
        case["expected_file_content"] = "# fixture\nRepository name: fixture-v2.\n"
        case["model_smoke"] = False
        with self.assertRaisesRegex(RuntimeError, "native-subagent model smoke"):
            runner.validate_runtime_case(case)

    def test_review_requires_completed_wait_message(self) -> None:
        root_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
        reviewer_id = "019f57ba-4b5d-76a2-bfe9-93cc7f0403c7"
        started = {"type": "thread.started", "thread_id": root_id}
        spawn = {
            "type": "item.completed",
            "item": {
                "id": "spawn",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "completed",
                "sender_thread_id": root_id,
                "receiver_thread_ids": [reviewer_id],
                "prompt": "AGENCY_WORKER: true Goal: inspect README.md Read scope: git diff",
            },
        }
        without_wait = runner.event_surface(
            "\n".join((json.dumps(started), json.dumps(spawn))), "done"
        )
        self.assertEqual(without_wait["reviews_completed"], {})

        wait = {
            "type": "item.completed",
            "item": {
                "id": "wait",
                "type": "collab_tool_call",
                "tool": "wait",
                "status": "completed",
                "sender_thread_id": root_id,
                "receiver_thread_ids": [reviewer_id],
                "agents_states": {
                    reviewer_id: {"status": "completed", "message": "README.md diff is correct"}
                },
            },
        }
        events = "\n".join(
            (json.dumps(started), json.dumps(spawn), json.dumps(wait))
        )
        completed = runner.event_surface(events, "done")["reviews_completed"]
        self.assertIn(reviewer_id, completed)

        nested_spawn = json.loads(json.dumps(spawn))
        nested_spawn["item"]["sender_thread_id"] = reviewer_id
        nested = runner.event_surface(
            "\n".join(
                (json.dumps(started), json.dumps(nested_spawn), json.dumps(wait))
            ),
            "done",
        )
        self.assertEqual(nested["reviews_completed"], {})
        self.assertTrue(nested["collaboration_identity_errors"])

    def test_artifact_review_prompt_carries_goal_diff_and_criteria_without_leaks(self) -> None:
        prompt = (
            "AGENCY_WORKER: true\n"
            "委派目标：独立复核当前 README.md 是否完成本次最小修改。\n"
            "读取范围：README.md；git diff -- README.md；git diff --check。\n"
            "写入范围：无。\n"
            "期望产物：REVIEW_TARGET、REVIEW_READBACK、REVIEW_FINDINGS、REVIEW_RESIDUAL_RISK、REVIEW_VERDICT，均填实际读回值。\n"
            "验证要求：直接读取当前 artifact 与相关 diff 后返回实际读回及判定；不得使用主线程提供的值。\n"
            "停止条件：返回唯一终态；不启动、不派发。"
        )
        self.assertTrue(
            runner.review_prompt_is_self_contained(
                prompt,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )
        self.assertFalse(
            runner.review_prompt_is_self_contained(
                prompt + "\n期望行：Repository name: agency-model-eval-fixture-v2.",
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )
        self.assertFalse(
            runner.review_prompt_is_self_contained(
                prompt + "\n使用 $zhijuan-codex-agency-chief-of-staf。",
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )
        self.assertFalse(
            runner.review_prompt_is_self_contained(
                prompt.replace("实际读回值。", "实际读回值。UmVwb3NpdG9yeSBuYW1l", 1),
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )
        self.assertFalse(
            runner.review_prompt_is_self_contained(
                prompt.replace("git diff -- README.md", "README.md", 1),
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )

    def test_reviewer_terminal_requires_exact_schema_target_and_pass_readback(self) -> None:
        valid = (
            "REVIEW_TARGET: README.md\n"
            "REVIEW_READBACK: Repository name: agency-model-eval-fixture-v2.\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS"
        )
        self.assertEqual(
            runner.verified_reviewer_terminal(
                valid,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "Repository name: agency-model-eval-fixture-v2.",
            ),
            {
                "REVIEW_TARGET": "README.md",
                "REVIEW_READBACK": "Repository name: agency-model-eval-fixture-v2.",
                "REVIEW_FINDINGS": "NONE",
                "REVIEW_RESIDUAL_RISK": "fixture only",
                "REVIEW_VERDICT": "PASS",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            artifact = project / "README.md"
            artifact.write_text(
                "Repository name: agency-model-eval-fixture-v2.\n", encoding="utf-8"
            )
            reviewer_kwargs = {
                "artifact": artifact,
                "project_root": project,
                "markers": ["Repository name: agency-model-eval-fixture-v2."],
            }
            self.assertEqual(
                run_profile_compat.verify_reviewer_schema(valid, **reviewer_kwargs)[
                    "review_verdict"
                ],
                "PASS",
            )
            with self.assertRaisesRegex(ValueError, "target does not match"):
                run_profile_compat.verify_reviewer_schema(
                    valid.replace("README.md", "notes.md", 1), **reviewer_kwargs
                )
            self.assertEqual(
                run_profile_compat.verify_reviewer_schema(
                    valid.replace("PASS", "FAIL", 1), **reviewer_kwargs
                )["review_verdict"],
                "FAIL",
            )
        for semantically_unaccepted in (
            valid.replace("README.md", "notes.md", 1),
            valid.replace("PASS", "FAIL", 1),
        ):
            self.assertIsNone(
                runner.verified_reviewer_terminal(
                    semantically_unaccepted,
                    "README.md",
                    "Repository name: agency-model-eval-fixture-v2.",
                    "Repository name: agency-model-eval-fixture-v2.",
                )
            )
        for malformed in (
            "准备审核。\n" + valid,
            valid + "\nEXTRA: evidence",
            valid.replace(
                "REVIEW_TARGET: README.md\nREVIEW_READBACK",
                "REVIEW_READBACK",
                1,
            ),
            valid.replace(
                "REVIEW_READBACK: Repository name: agency-model-eval-fixture-v2.",
                "REVIEW_TARGET: duplicate.md",
                1,
            ),
        ):
            self.assertIsNone(
                runner.verified_reviewer_terminal(
                    malformed,
                    "README.md",
                    "Repository name: agency-model-eval-fixture-v2.",
                    "Repository name: agency-model-eval-fixture-v2.",
                )
            )
            with self.assertRaises(ValueError):
                run_profile_compat.verify_reviewer_schema(
                    malformed, **reviewer_kwargs
                )

        missing_marker = valid.replace(
            "Repository name: agency-model-eval-fixture-v2.",
            "Repository name: agency-model-eval-fixture-v2. without hidden proof",
            1,
        )
        self.assertIsNone(
            runner.verified_reviewer_terminal(
                missing_marker,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
                "# Agency model-eval fixture",
            )
        )

    def test_review_final_cannot_invent_a_reviewer_when_spawn_chain_is_absent(self) -> None:
        invented = (
            "Reviewer 已返回；采纳 PASS。\n"
            "REVIEW_READBACK: Repository name: fixture-v2."
        )
        failures = runner.independent_review_final_failures(invented, {}, {})
        self.assertIn("final answer did not disclose independent review unverified", failures)
        self.assertIn(
            "final answer claimed reviewer evidence without a completed spawn chain", failures
        )
        self.assertEqual(
            runner.independent_review_final_failures("独立审核未验证", {}, {}), []
        )

    def test_worker_packet_requires_ordered_nonleaking_fields(self) -> None:
        valid = (
            "AGENCY_WORKER: true\n"
            "委派目标：审查 README。\n"
            "读取范围：README.md。\n"
            "写入范围：无。\n"
            "期望产物：WORKER_RESULT。\n"
            "验证要求：直接读取当前 README。\n"
            "停止条件：返回唯一终态；不启动、不派发。"
        )
        self.assertTrue(runner.is_valid_worker_packet(valid))
        self.assertTrue(
            runner.is_valid_worker_packet(
                valid.replace("审查 README。", "使用 $openai-docs 核对 README。", 1)
            )
        )
        self.assertFalse(
            runner.is_valid_worker_packet(valid + "\n使用 $agency-chief-of-staff。")
        )
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("审查 README。", "使用 $zhijuan-codex-agency-chief-of-staf 审查 README。", 1)
            )
        )
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("读取范围", "验证范围", 1)))
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("委派目标", "读取范围", 1).replace("读取范围：README.md", "委派目标：审查 README", 1)
            )
        )
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("WORKER_RESULT。", "GO", 1)))
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("直接读取当前 README。", "激活本技能", 1)))
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("WORKER_RESULT。", "REVIEW_TARGET=agency-model-eval-fixture-v2", 1)
            )
        )
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("直接读取当前 README。", "读回 README；隐藏 marker 是 #fixture", 1)
            )
        )
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("返回唯一终态；不启动、不派发。", "返回通过结论。", 1)
            )
        )
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace(
                    "返回唯一终态；不启动、不派发。",
                    "返回 expected target agency-model-eval-fixture-v2。",
                    1,
                )
            )
        )
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("\n读取范围", "\n\n读取范围", 1)))
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace(
                    "返回唯一终态；不启动、不派发。",
                    "返回唯一终态；不启动、不派发。SENTINEL_Z9K4",
                    1,
                )
            )
        )
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace(
                    "返回唯一终态；不启动、不派发。",
                    "返回唯一终态；不启动、不派发。结论：没有问题",
                    1,
                )
            )
        )

    def test_boot_precedes_progress_and_reviewer_spawn(self) -> None:
        case = self.base_case()
        case.update({"collaboration": "native_subagents"})
        root_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
        reviewer_id = "019f57ba-4b5d-76a2-bfe9-93cc7f0403c7"
        started = {"type": "thread.started", "thread_id": root_id}
        progress = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "MAIN_PROGRESS: PLAN"},
        }
        boot = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "<!-- COS_BOOT_RECEIPT；模式：直接；协作：原生子代理。 -->\n任务已接管｜正在核对事实"},
        }
        spawn = {
            "type": "item.completed",
            "item": {
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "completed",
                "sender_thread_id": root_id,
                "receiver_thread_ids": [reviewer_id],
            },
        }
        parsed = runner.event_surface(
            "\n".join(map(json.dumps, (started, progress, spawn, boot))), ""
        )
        failures = runner.contract_failures(case, parsed)
        self.assertIn("main progress preceded COS_BOOT_RECEIPT", failures)
        self.assertIn("reviewer spawn preceded COS_BOOT_RECEIPT", failures)

    def test_boot_precedes_task_action_and_worker_cannot_progress_or_delegate(self) -> None:
        started_task_action = {
            "type": "item.started",
            "item": {
                "id": "readme",
                "type": "command_execution",
                "status": "in_progress",
                "command": "cat README.md",
            },
        }
        task_action = {
            "type": "item.completed",
            "item": {
                "id": "readme",
                "type": "command_execution",
                "status": "completed",
                "exit_code": 0,
                "command": "cat README.md",
            },
        }
        boot = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n任务已接管｜正在核对事实"},
        }
        parsed = runner.event_surface(
            "\n".join(map(json.dumps, (started_task_action, boot, task_action))), ""
        )
        failures = runner.contract_failures(self.base_case(), parsed)
        self.assertIn("task action preceded COS_BOOT_RECEIPT", failures)

        preboot_wait = {
            "type": "item.started",
            "item": {
                "id": "wait",
                "type": "collab_tool_call",
                "tool": "wait",
                "status": "in_progress",
            },
        }
        wait_failures = runner.contract_failures(
            self.base_case(), runner.event_surface("\n".join(map(json.dumps, (preboot_wait, boot))), "")
        )
        self.assertIn("task action preceded COS_BOOT_RECEIPT", wait_failures)

        failed_spawn = {
            "type": "item.completed",
            "item": {
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "failed",
                "receiver_thread_ids": [],
            },
        }
        failed_spawn_failures = runner.contract_failures(
            self.base_case(), runner.event_surface("\n".join(map(json.dumps, (failed_spawn, boot))), "")
        )
        self.assertIn("task action preceded COS_BOOT_RECEIPT", failed_spawn_failures)

        preboot_commentary = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "我先检查 README。"},
        }
        commentary_failures = runner.contract_failures(
            self.base_case(), runner.event_surface("\n".join(map(json.dumps, (preboot_commentary, boot))), "")
        )
        self.assertIn("assistant message preceded COS_BOOT_RECEIPT", commentary_failures)

        worker = self.base_case()
        worker.update({"should_trigger": False, "activation": "worker", "mode": "worker"})
        worker_spawn = {
            "type": "item.completed",
            "item": {
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "completed",
                "receiver_thread_ids": ["child"],
            },
        }
        worker_progress = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "进度：准备派发"},
        }
        worker_extra_commentary = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "先读取 README。"},
        }
        parsed_worker = runner.event_surface(
            "\n".join(map(json.dumps, (worker_spawn, worker_progress, worker_extra_commentary))), ""
        )
        worker_failures = runner.contract_failures(worker, parsed_worker)
        self.assertIn("worker or ordinary case emitted main-thread progress", worker_failures)
        self.assertIn("worker or ordinary case attempted collaboration", worker_failures)
        self.assertIn("worker must return exactly one terminal message", worker_failures)

        failed_worker_spawn = {
            "type": "item.completed",
            "item": {
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "status": "failed",
                "receiver_thread_ids": [],
            },
        }
        self.assertIn(
            "worker or ordinary case attempted collaboration",
            runner.contract_failures(
                worker, runner.event_surface(json.dumps(failed_worker_spawn), "")
            ),
        )

    def test_only_single_cat_skill_read_is_passive_before_boot(self) -> None:
        cat_skill_started = {
            "type": "item.started",
            "item": {
                "id": "skill",
                "type": "command_execution",
                "status": "in_progress",
                "command": "/bin/cat /tmp/skill/SKILL.md",
            },
        }
        cat_skill = {
            "type": "item.completed",
            "item": {
                "id": "skill",
                "type": "command_execution",
                "status": "completed",
                "exit_code": 0,
                "command": "/bin/cat /tmp/skill/SKILL.md",
            },
        }
        bootstrap = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n任务已接管｜正在核对事实"},
        }
        allowed = runner.contract_failures(
            self.base_case(),
            runner.event_surface(
                "\n".join(map(json.dumps, (cat_skill_started, cat_skill, bootstrap))),
                "",
                installed_skill_path=Path("/tmp/skill/SKILL.md"),
            ),
        )
        self.assertNotIn("task action preceded COS_BOOT_RECEIPT", allowed)
        smuggled = dict(cat_skill)
        smuggled["item"] = {**cat_skill["item"], "command": "touch x; /bin/cat /tmp/skill/SKILL.md"}
        rejected = runner.contract_failures(
            self.base_case(),
            runner.event_surface(
                "\n".join(map(json.dumps, (smuggled, bootstrap))),
                "",
                installed_skill_path=Path("/tmp/skill/SKILL.md"),
            ),
        )
        self.assertIn("task action preceded COS_BOOT_RECEIPT", rejected)
        foreign_skill = dict(cat_skill)
        foreign_skill["item"] = {
            **cat_skill["item"],
            "command": "/bin/cat /tmp/foreign/SKILL.md",
        }
        foreign = runner.contract_failures(
            self.base_case(),
            runner.event_surface(
                "\n".join(map(json.dumps, (foreign_skill, bootstrap))),
                "",
                installed_skill_path=Path("/tmp/skill/SKILL.md"),
            ),
        )
        self.assertIn("task action preceded COS_BOOT_RECEIPT", foreign)

    def test_allows_one_narrow_platform_skill_announcement_before_boot(self) -> None:
        announcement = {
            "type": "item.completed",
            "item": {
                "type": "assistant_message",
                "text": "我会使用 agency-chief-of-staff Skill，因为本任务匹配它的职责；先完整读取 Skill 说明。",
            },
        }
        boot = {
            "type": "item.completed",
            "item": {
                "type": "assistant_message",
                "text": "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n任务已接管｜正在核对事实",
            },
        }
        parsed = runner.event_surface("\n".join(map(json.dumps, (announcement, boot))), "")
        failures = runner.contract_failures(self.base_case(), parsed)
        self.assertNotIn("assistant message preceded COS_BOOT_RECEIPT", failures)

        progress_disguised_as_announcement = {
            "type": "item.completed",
            "item": {
                "type": "assistant_message",
                "text": "我会使用 agency-chief-of-staff Skill，因为本任务匹配它的职责；先完整读取 Skill 说明。下一步开始修改文件。",
            },
        }
        rejected = runner.contract_failures(
            self.base_case(),
            runner.event_surface(
                "\n".join(map(json.dumps, (progress_disguised_as_announcement, boot))), ""
            ),
        )
        self.assertIn("assistant message preceded COS_BOOT_RECEIPT", rejected)

        duplicate = runner.contract_failures(
            self.base_case(),
            runner.event_surface(
                "\n".join(map(json.dumps, (announcement, announcement, boot))), ""
            ),
        )
        self.assertIn("assistant message preceded COS_BOOT_RECEIPT", duplicate)

        for suffix in ("然后修改文件。", "已经发现启动校验有缺口。", "计划完成后发布。"):
            smuggled = {
                "type": "item.completed",
                "item": {
                    "type": "assistant_message",
                    "text": "我会使用 agency-chief-of-staff Skill，因为本任务匹配它的职责；先完整读取 Skill 说明。" + suffix,
                },
            }
            failures = runner.contract_failures(
                self.base_case(),
                runner.event_surface("\n".join(map(json.dumps, (smuggled, boot))), ""),
            )
            self.assertIn("assistant message preceded COS_BOOT_RECEIPT", failures)

    def test_visible_takeover_line_is_sufficient_when_host_strips_comments(self) -> None:
        boot = {
            "type": "item.completed",
            "item": {
                "type": "assistant_message",
                "text": "任务已接管｜正在核对事实\n\n目标：交付用户可读结果",
            },
        }
        failures = runner.contract_failures(
            self.base_case(), runner.event_surface(json.dumps(boot), "")
        )
        self.assertNotIn("should_trigger=true but no takeover line was observed", failures)
        self.assertNotIn("boot marker and first visible takeover line are not atomic", failures)
        self.assertNotIn("main session must emit exactly one takeover line", failures)

    def test_failed_command_is_not_tool_evidence_but_still_preboot_task_action(self) -> None:
        event = {
            "type": "item.completed",
            "item": {
                "id": "cmd",
                "type": "command_execution",
                "status": "completed",
                "exit_code": 1,
                "command": "cat README.md",
            },
        }
        boot = {
            "type": "item.completed",
            "item": {"type": "assistant_message", "text": "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n任务已接管｜正在核对事实"},
        }
        parsed = runner.event_surface("\n".join(map(json.dumps, (event, boot))), "done")
        self.assertEqual(parsed["tool_events"], 0)
        self.assertIn(
            "task action preceded COS_BOOT_RECEIPT",
            runner.contract_failures(self.base_case(), parsed),
        )

    def test_event_stream_and_tool_success_fields_fail_closed(self) -> None:
        thread_id = "019f57b8-6477-76d0-ae82-0e7b39a3ae6b"
        lifecycle = [
            {"type": "thread.started", "thread_id": thread_id},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "cmd-ok",
                    "type": "command_execution",
                    "status": "completed",
                    "exit_code": 0,
                },
            },
            {"type": "turn.completed"},
        ]
        parsed = runner.event_surface(
            "\n".join(json.dumps(item) for item in lifecycle), ""
        )
        self.assertEqual(parsed["thread_started_ids"], [thread_id])
        self.assertEqual(parsed["turn_started_count"], 1)
        self.assertEqual(parsed["turn_completed_count"], 1)
        self.assertEqual(parsed["jsonl_parse_errors"], 0)
        self.assertEqual(parsed["tool_events"], 1)

        missing_fields = [
            {
                "type": "item.completed",
                "item": {"id": "cmd", "type": "command_execution"},
            },
            {
                "type": "item.completed",
                "item": {"id": "edit", "type": "file_change"},
            },
            {
                "type": "item.completed",
                "item": {"id": "mcp", "type": "mcp_tool_call"},
            },
        ]
        rejected = runner.event_surface(
            "\n".join(json.dumps(item) for item in missing_fields) + "\nnot-json",
            "",
        )
        self.assertEqual(rejected["tool_events"], 0)
        self.assertEqual(rejected["jsonl_parse_errors"], 1)

    def test_contract_uses_trigger_mode_and_collaboration_fields(self) -> None:
        case = self.base_case()
        failures = runner.contract_failures(
            case,
            "<!-- COS_BOOT_RECEIPT；模式：结构化；协作：原生子代理。 -->\n任务已接管｜正在核对事实",
        )
        self.assertTrue(any("模式：直接" in failure for failure in failures))
        self.assertTrue(any("协作：无" in failure for failure in failures))

    def test_boot_marker_must_be_adjacent_to_first_visible_takeover_line(self) -> None:
        case = self.base_case()
        invalid = (
            "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n"
            "正在加载内部系统\n"
            "任务已接管｜正在核对事实"
        )
        failures = runner.contract_failures(case, invalid)
        self.assertIn(
            "boot marker and first visible takeover line are not atomic",
            failures,
        )
        valid = (
            "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n"
            "任务已接管｜正在核对事实"
        )
        self.assertNotIn(
            "boot marker and first visible takeover line are not atomic",
            runner.contract_failures(case, valid),
        )

    def test_visualization_contract_checks_required_and_forbidden_markers(self) -> None:
        case = self.base_case()
        case["visualization"] = {
            "surface": "task-stage",
            "fallback": "markdown-step-list",
            "must_not_claim": ["进度100%"],
            "must_contain_any": ["阶段路径", "离散阶段"],
            "must_not_contain": ["::codex-inline-vis", "100%"],
        }
        base = (
            "<!-- COS_BOOT_RECEIPT；模式：直接；协作：无。 -->\n"
            "任务已接管｜正在核对事实\n"
        )
        missing = runner.contract_failures(case, base + "当前进度")
        self.assertIn(
            "visualization output did not match any required surface marker",
            missing,
        )
        forbidden = runner.contract_failures(case, base + "阶段路径 100%")
        self.assertIn(
            "visualization output contains forbidden marker '100%'",
            forbidden,
        )
        forbidden_claim = runner.contract_failures(case, base + "阶段路径 进度100%")
        self.assertIn(
            "visualization output makes forbidden claim '进度100%'",
            forbidden_claim,
        )
        wrong_surface = runner.contract_failures(
            {**case, "visualization": {**case["visualization"], "surface": "decision"}},
            base + "只有普通文本",
        )
        self.assertIn(
            "visualization output does not represent surface 'decision'",
            wrong_surface,
        )
        missing_fallback = runner.contract_failures(case, base + "可视化内容")
        self.assertIn(
            "visualization fallback 'markdown-step-list' was not represented",
            missing_fallback,
        )
        passed = runner.contract_failures(case, base + "使用离散阶段展示当前进度")
        self.assertFalse(any("visualization output" in item for item in passed))

    def test_partial_success_cannot_be_full_pass(self) -> None:
        passed = [{"status": "passed"}]
        self.assertEqual(runner.receipt_status(False, passed), "passed_partial")
        self.assertEqual(runner.receipt_status(True, passed), "passed")
        self.assertEqual(runner.receipt_status(True, []), "failed")

    def test_release_eligibility_distinguishes_rc_from_stable(self) -> None:
        prerelease, stable = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            "max",
            True,
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
            "gpt-5.6-sol",
            "max",
            True,
            True,
            True,
            "dedicated",
            ["cold_review_context_isolation"],
        )
        self.assertTrue(dedicated_prerelease)
        self.assertFalse(dedicated_stable)
        missing_effort, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            None,
            True,
            True,
            True,
            "dedicated",
            [],
        )
        self.assertFalse(missing_effort)
        unverified_identity, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            "max",
            False,
            True,
            True,
            "dedicated",
            [],
        )
        self.assertFalse(unverified_identity)
        missing_catalog, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-terra",
            "max",
            True,
            False,
            True,
            "dedicated",
            [],
        )
        supported_effort, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            "low",
            True,
            True,
            True,
            "dedicated",
            [],
        )
        self.assertFalse(missing_catalog)
        self.assertTrue(supported_effort)
        missing_git_state, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            "max",
            True,
            True,
            False,
            "dedicated",
            [],
        )
        self.assertFalse(missing_git_state)

    def test_release_catalog_requires_current_openai_judgment_binding(self) -> None:
        catalog = {
            "schema_version": 2,
            "provenance": {
                "source": "active-host-catalog",
                "source_id": "codex-app-server:model/list:" + "a" * 64,
                "observed_for_requested_thread": True,
                "requested_thread_id": "11111111-1111-1111-1111-111111111111",
                "root_provider": "openai",
                "canonical_state_store_bound": True,
                "model_provider_evidence": "root-state-inferred",
            },
            "models": [
                {
                    "id": "current-judgment-model",
                    "provider": "openai",
                    "provider_evidence": "root-state-inferred",
                    "model_class": "judgment",
                    "supported_reasoning": ["high", "ultra"],
                    "available": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            receipt = runner.verify_release_catalog(
                path, "current-judgment-model", "ultra"
            )
            self.assertFalse(receipt["verified"])
            self.assertTrue(receipt["schema_validated"])
            self.assertEqual(receipt["model_class"], "judgment")
            with mock.patch.object(runner, "verify_live_catalog") as live:
                live_receipt = runner.verify_release_catalog(
                    path,
                    "current-judgment-model",
                    "ultra",
                    codex_bin="/bin/true",
                    state_db=Path(tmp) / "state_5.sqlite",
                    thread_id="11111111-1111-1111-1111-111111111111",
                    cwd=Path(tmp),
                )
            self.assertTrue(live_receipt["verified"])
            self.assertTrue(live_receipt["live_readback_verified"])
            live.assert_called_once()
            catalog["models"][0]["model_class"] = "efficient"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "judgment model"):
                runner.verify_release_catalog(
                    path, "current-judgment-model", "ultra"
                )

            catalog["models"][0]["model_class"] = "judgment"
            catalog["provenance"]["requested_thread_id"] = "not-a-thread"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "requested-thread"):
                runner.verify_release_catalog(
                    path, "current-judgment-model", "ultra"
                )

            catalog["provenance"]["requested_thread_id"] = (
                "11111111-1111-1111-1111-111111111111"
            )
            catalog["models"][0]["provider_evidence"] = "catalog-advertised"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "judgment model"):
                runner.verify_release_catalog(
                    path, "current-judgment-model", "ultra"
                )

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

    def test_role_model_smoke_cases_cannot_be_removed(self) -> None:
        cases = json.loads(
            (ROOT / "evals" / "behavior_cases.json").read_text(encoding="utf-8")
        )
        validated = [runner.validate_runtime_case(case) for case in cases]
        for case_id in ("role-model-balanced-budget", "role-model-route-unavailable"):
            with self.subTest(case_id=case_id):
                weakened = [case for case in validated if case["id"] != case_id]
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
            runner_repo = base / "runner"
            shutil.copytree(
                ROOT / "scripts",
                runner_repo / "scripts",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            shutil.copytree(ROOT / "assets", runner_repo / "assets")
            subprocess.run(["git", "init", "-q", str(runner_repo)], check=True)
            subprocess.run(
                ["git", "-C", str(runner_repo), "add", "scripts", "assets"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(runner_repo),
                    "-c",
                    "user.name=Model Eval Test",
                    "-c",
                    "user.email=model-eval@example.invalid",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "runner baseline",
                ],
                check=True,
            )
            root = base / "package"
            (root / "evals").mkdir(parents=True)
            (root / "evals" / "behavior_cases.json").write_text("[]\n", encoding="utf-8")
            auth = base / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            executable = base / "codex"
            executable.write_bytes(b"MZ\x00\x00")
            executable.chmod(0o700)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(runner_repo / "scripts" / "run_model_evals.py"),
                    "--root",
                    str(root),
                    "--out",
                    str(base / "output"),
                    "--codex-executable",
                    str(executable),
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
