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
                        "cwd": str(fixture.resolve()),
                        "model_provider": "openai",
                    },
                },
                {
                    "type": "turn_context",
                    "payload": {
                        "cwd": str(fixture.resolve()),
                        "model": "gpt-5.6-sol",
                        "effort": "max",
                    },
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
                    "session_count": 1,
                    "turn_count": 1,
                    "session_observations": [
                        {
                            "providers": ["openai"],
                            "models": ["gpt-5.6-sol"],
                            "reasoning_efforts": ["max"],
                            "session_count": 1,
                            "turn_count": 1,
                        }
                    ],
                },
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

    def test_artifact_review_prompt_carries_goal_diff_and_criteria_without_leaks(self) -> None:
        prompt = (
            "AGENCY_WORKER: true\n"
            "委派目标：独立复核当前 README.md 是否完成本次最小修改。\n"
            "读取范围：README.md；git diff -- README.md；git diff --check。\n"
            "写入范围：无。\n"
            "期望产物：REVIEW_READBACK、REVIEW_TARGET、REVIEW_VERDICT，均填实际读回值。\n"
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
            "REVIEW_READBACK: `Repository name: agency-model-eval-fixture-v2.`\n"
            "REVIEW_TARGET: `README.md`\n"
            "REVIEW_VERDICT: `PASS`"
        )
        self.assertEqual(
            runner.verified_reviewer_terminal(
                valid,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
            ),
            {
                "REVIEW_READBACK": "Repository name: agency-model-eval-fixture-v2.",
                "REVIEW_TARGET": "README.md",
                "REVIEW_VERDICT": "PASS",
            },
        )
        self.assertIsNone(
            runner.verified_reviewer_terminal(
                "准备审核。\n" + valid,
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
            )
        )
        self.assertIsNone(
            runner.verified_reviewer_terminal(
                valid.replace("README.md", "notes.md", 1),
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
            )
        )
        self.assertIsNone(
            runner.verified_reviewer_terminal(
                valid.replace("PASS", "FAIL", 1),
                "README.md",
                "Repository name: agency-model-eval-fixture-v2.",
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
            "期望产物：实际读回字段。\n"
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
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("实际读回字段。", "GO", 1)))
        self.assertFalse(runner.is_valid_worker_packet(valid.replace("直接读取当前 README。", "激活本技能", 1)))
        self.assertFalse(
            runner.is_valid_worker_packet(
                valid.replace("实际读回字段。", "REVIEW_TARGET=agency-model-eval-fixture-v2", 1)
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
                "receiver_thread_ids": ["reviewer"],
            },
        }
        parsed = runner.event_surface("\n".join(map(json.dumps, (progress, spawn, boot))), "")
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
            "dedicated",
            [],
        )
        self.assertFalse(unverified_identity)
        wrong_model, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-terra",
            "max",
            True,
            "dedicated",
            [],
        )
        wrong_effort, _ = runner.release_eligibility(
            "passed",
            True,
            "gpt-5.6-sol",
            "low",
            True,
            "dedicated",
            [],
        )
        self.assertFalse(wrong_model)
        self.assertFalse(wrong_effort)

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
                    str(ROOT / "scripts" / "run_model_evals.py"),
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
