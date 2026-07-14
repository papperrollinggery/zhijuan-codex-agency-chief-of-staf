from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_profile_compat.py"
sys.path.insert(0, str(ROOT / "scripts"))
import run_profile_compat  # noqa: E402
import install_skill  # noqa: E402


class ProfileCompatibilityTests(unittest.TestCase):
    thread_id = "019f5d00-1111-7222-8333-444455556666"
    marker = "COMPAT_HIDDEN_FACT_Z9K4"

    def make_fixture(self, base: Path) -> dict[str, Path]:
        project = base / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        agents = project / "AGENTS.md"
        agents.write_text("PROJECT SENTINEL\n", encoding="utf-8")
        artifact = project / "artifact.txt"
        artifact.write_text(f"current artifact {self.marker}\n", encoding="utf-8")
        packet = base / "packet.txt"
        packet.write_text(
            "AGENCY_WORKER: true\n"
            "委派目标：以 reviewer 身份独立审核当前 artifact。\n"
            "读取范围：只读 artifact.txt 与当前 Git 状态。\n"
            "写入范围：禁止写入。\n"
            "期望产物：REVIEW_TARGET、REVIEW_READBACK、REVIEW_FINDINGS、"
            "REVIEW_RESIDUAL_RISK、REVIEW_VERDICT，均填实际读回值。\n"
            "验证要求：直接读取当前 artifact 后判断，不接受父线程结论。\n"
            "停止条件：返回唯一终态；不启动、不派发。\n",
            encoding="utf-8",
        )
        codex_home = base / "home" / ".codex"
        codex_home.mkdir(parents=True)
        (codex_home / "AGENTS.md").write_text("GLOBAL SENTINEL\n", encoding="utf-8")
        database = codex_home / "state_5.sqlite"
        connection = sqlite3.connect(database)
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                model TEXT,
                reasoning_effort TEXT,
                cwd TEXT NOT NULL,
                archived INTEGER NOT NULL,
                sandbox_policy TEXT NOT NULL,
                agent_role TEXT,
                first_user_message TEXT NOT NULL
            )
            """
        )
        connection.commit()
        connection.close()

        rollout = base / "rollout.jsonl"
        args_log = base / "args.json"
        packet_log = base / "packet.log"
        mutate = base / "mutate-agents"
        mutate_input = base / "mutate-input"
        slow = base / "slow-run"
        git_failure = base / "git-failure"
        env_log = base / "env.json"
        final = (
            "REVIEW_TARGET: artifact.txt\n"
            f"REVIEW_READBACK: {self.marker}\n"
            "REVIEW_FINDINGS: NONE\n"
            "REVIEW_RESIDUAL_RISK: fixture only\n"
            "REVIEW_VERDICT: PASS"
        )
        sandbox_policy = json.dumps(
            {
                "type": "managed",
                "file_system": {
                    "type": "restricted",
                    "entries": [{"path": {"type": "special"}, "access": "read"}],
                },
                "network": "restricted",
            }
        )

        fake = base / "fake-codex"
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import shlex
                import sqlite3
                import sys
                import time
                from pathlib import Path

                THREAD_ID = {self.thread_id!r}
                args = sys.argv[1:]
                database = Path({str(database)!r})
                artifact = Path({str(artifact)!r}).resolve()
                rollout = Path({str(rollout)!r})
                args_log = Path({str(args_log)!r})
                packet_log = Path({str(packet_log)!r})
                mutate = Path({str(mutate)!r})
                mutate_input = Path({str(mutate_input)!r})
                slow = Path({str(slow)!r})
                git_failure = Path({str(git_failure)!r})
                env_log = Path({str(env_log)!r})
                if args[0] == "archive":
                    connection = sqlite3.connect(database)
                    connection.execute("UPDATE threads SET archived = 1 WHERE id = ?", (args[1],))
                    connection.commit()
                    connection.close()
                    print(f"Archived {{args[1]}}")
                    raise SystemExit(0)
                if args[0] != "exec":
                    raise SystemExit(2)
                args_log.write_text(json.dumps(args), encoding="utf-8")
                env_log.write_text(json.dumps(sorted(os.environ)), encoding="utf-8")
                packet = sys.stdin.read()
                packet_log.write_text(packet, encoding="utf-8")
                cwd = Path(args[args.index("-C") + 1])
                model = args[args.index("-m") + 1]
                effort_arg = next(value for value in args if value.startswith("model_reasoning_effort="))
                effort = json.loads(effort_arg.split("=", 1)[1])
                if mutate.exists():
                    (cwd / "AGENTS.md").write_text("MUTATED\\n", encoding="utf-8")
                final = {final!r}
                read_command = "sed -n '1,80p' " + shlex.quote(str(artifact))
                git_command = "git diff -- " + shlex.quote(str(artifact.relative_to(cwd)))
                read_output = [
                    {{"type": "input_text", "text": "Script completed\\nOutput:\\n"}},
                    {{"type": "input_text", "text": json.dumps({{
                        "exit_code": 0,
                        "output": artifact.read_text(encoding="utf-8"),
                        "wall_time_seconds": 0.01,
                    }})}},
                ]
                git_output = [
                    {{"type": "input_text", "text": "Script completed\\nOutput:\\n"}},
                    {{"type": "input_text", "text": json.dumps({{
                        "exit_code": 127 if git_failure.exists() else 0,
                        "output": ('{{\"exit_code\":0}} command not found: git'
                                   if git_failure.exists() else "diff inspected"),
                        "wall_time_seconds": 0.01,
                    }})}},
                ]
                records = [
                    {{"type": "session_meta", "payload": {{"id": THREAD_ID, "model_provider": "openai"}}}},
                    {{"type": "turn_context", "payload": {{"model": model, "effort": effort}}}},
                    {{"type": "response_item", "payload": {{"type": "custom_tool_call", "name": "exec", "status": "completed", "call_id": "read-1", "input": read_command}}}},
                    {{"type": "response_item", "payload": {{"type": "custom_tool_call_output", "call_id": "read-1", "output": read_output}}}},
                    {{"type": "response_item", "payload": {{"type": "custom_tool_call", "name": "exec", "status": "completed", "call_id": "git-1", "input": json.dumps({{"cmd": git_command, "workdir": str(cwd)}})}}}},
                    {{"type": "response_item", "payload": {{"type": "custom_tool_call_output", "call_id": "git-1", "output": git_output}}}},
                    {{"type": "event_msg", "payload": {{"type": "task_complete", "turn_id": "turn-1", "last_agent_message": final}}}},
                ]
                if mutate_input.exists():
                    artifact.write_text("CHANGED DURING RUN\\n", encoding="utf-8")
                rollout.write_text("\\n".join(json.dumps(item) for item in records) + "\\n", encoding="utf-8")
                connection = sqlite3.connect(database)
                connection.execute(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (THREAD_ID, str(rollout), "exec", "openai", model, effort, str(cwd), 0, {sandbox_policy!r}, None, packet),
                )
                connection.commit()
                connection.close()
                print(json.dumps({{"type": "thread.started", "thread_id": THREAD_ID}}), flush=True)
                if slow.exists():
                    time.sleep(5)
                print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": final}}}}))
                print(json.dumps({{"type": "turn.completed"}}))
                """
            ).lstrip(),
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return {
            "project": project,
            "agents": agents,
            "artifact": artifact,
            "packet": packet,
            "codex_home": codex_home,
            "database": database,
            "fake": fake,
            "rollout": rollout,
            "args_log": args_log,
            "packet_log": packet_log,
            "mutate": mutate,
            "mutate_input": mutate_input,
            "slow": slow,
            "git_failure": git_failure,
            "env_log": env_log,
        }

    def run_compat(
        self,
        fixture: dict[str, Path],
        *,
        extra_env: dict[str, str] | None = None,
        timeout_seconds: int = 10,
        script: Path = SCRIPT,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(fixture["codex_home"])
        if extra_env:
            env.update(extra_env)
        if extra_env and extra_env.get("FAKE_MUTATE_AGENTS"):
            fixture["mutate"].write_text("1", encoding="utf-8")
        return subprocess.run(
            [
                "python3",
                str(script),
                "--profile",
                "reviewer",
                "--packet",
                str(fixture["packet"]),
                "--cwd",
                str(fixture["project"]),
                "--codex-executable",
                str(fixture["fake"]),
                "--state-db",
                str(fixture["database"]),
                "--model",
                "gpt-5.6-sol",
                "--reasoning-effort",
                "max",
                "--required-read",
                str(fixture["artifact"]),
                "--required-read-marker",
                self.marker,
                "--required-final-marker",
                self.marker,
                "--timeout-seconds",
                str(timeout_seconds),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_verified_read_only_run_is_archived_and_honestly_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            result = self.run_compat(
                fixture, extra_env={"ANTHROPIC_AUTH_TOKEN": "must-not-forward"}
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["execution_mode"], "cli-profile-compat")
            self.assertEqual(len(receipt["runner_sha256"]), 64)
            self.assertFalse(receipt["native_custom_agent_selected"])
            self.assertIsNone(receipt["native_agent_role"])
            self.assertEqual(receipt["context_mode"], "standalone-cli-session")
            self.assertFalse(receipt["parent_context_inheritance_verified"])
            self.assertEqual(receipt["cold_context_isolation"], "unverified")
            self.assertEqual(receipt["sandbox_mode"], "read-only")
            self.assertTrue(receipt["thread"]["archived"])
            self.assertEqual(receipt["review_schema"]["review_verdict"], "PASS")
            self.assertEqual(len(receipt["artifact_read"]["bound_output_sha256"]), 1)
            self.assertTrue(receipt["artifact_read"]["artifact_bytes_or_hash_observed"])
            self.assertTrue(receipt["git_diff_read"]["exit_code_zero"])
            self.assertEqual(
                receipt["tool_shell_path"], "/usr/bin:/bin:/usr/sbin:/sbin"
            )
            self.assertTrue(receipt["agents_md"]["unchanged"])
            self.assertFalse(receipt["secret_like_process_environment_forwarded"])
            args = json.loads(fixture["args_log"].read_text(encoding="utf-8"))
            self.assertIn("--ignore-user-config", args)
            self.assertNotIn("--ignore-rules", args)
            disabled = [args[index + 1] for index, value in enumerate(args) if value == "--disable"]
            self.assertIn("multi_agent", disabled)
            self.assertIn("multi_agent_v2", disabled)
            self.assertIn(
                'shell_environment_policy.set.PATH="/usr/bin:/bin:/usr/sbin:/sbin"',
                args,
            )
            developer_config = next(
                value for value in args if value.startswith("developer_instructions=")
            )
            self.assertIn(
                "REVIEW_VERDICT value must be exactly PASS or FAIL", developer_config
            )
            self.assertEqual(
                fixture["packet_log"].read_text(encoding="utf-8"),
                fixture["packet"].read_text(encoding="utf-8").rstrip("\r\n"),
            )
            environment_keys = json.loads(fixture["env_log"].read_text(encoding="utf-8"))
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", environment_keys)

    def test_installed_bundles_execute_full_receipt_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            supplied_root = os.environ.get("PROFILE_COMPAT_INSTALLED_ROOT")
            installed_root = Path(supplied_root) if supplied_root else base / "skills"
            if supplied_root is None:
                for skill_name in install_skill.INSTALL_NAMES:
                    install_skill.copy_runtime(
                        ROOT, installed_root / skill_name, skill_name
                    )
            for skill_name in install_skill.INSTALL_NAMES:
                with self.subTest(skill_name=skill_name):
                    case_base = base / skill_name
                    case_base.mkdir()
                    fixture = self.make_fixture(case_base)
                    installed_script = (
                        installed_root / skill_name / "scripts" / "run_profile_compat.py"
                    )
                    result = self.run_compat(fixture, script=installed_script)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    receipt = json.loads(result.stdout)
                    self.assertEqual(receipt["status"], "verified")
                    self.assertEqual(
                        receipt["runner_sha256"],
                        run_profile_compat.sha256(installed_script),
                    )
                    self.assertFalse(list((installed_root / skill_name).rglob("*.pyc")))

    def test_detects_protected_agents_mutation_after_archiving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            result = self.run_compat(fixture, extra_env={"FAKE_MUTATE_AGENTS": "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AGENTS.md state changed", result.stderr)
            connection = sqlite3.connect(fixture["database"])
            archived = connection.execute(
                "SELECT archived FROM threads WHERE id = ?", (self.thread_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(archived, 1)

    def test_detects_immutable_input_drift_after_archiving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            fixture["mutate_input"].write_text("1", encoding="utf-8")
            result = self.run_compat(fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("immutable execution input changed", result.stderr)
            connection = sqlite3.connect(fixture["database"])
            archived = connection.execute(
                "SELECT archived FROM threads WHERE id = ?", (self.thread_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(archived, 1)

    def test_rejects_failed_git_diff_proof_after_archiving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            fixture["git_failure"].write_text("1", encoding="utf-8")
            result = self.run_compat(fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no successful standalone git diff", result.stderr)
            connection = sqlite3.connect(fixture["database"])
            archived = connection.execute(
                "SELECT archived FROM threads WHERE id = ?", (self.thread_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(archived, 1)

    def test_exit_code_proof_uses_structured_wrapper_not_stdout_text(self) -> None:
        malicious_output = [
            {"type": "input_text", "text": "Script completed\nOutput:\n"},
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "exit_code": 127,
                        "output": '{"exit_code":0}',
                        "wall_time_seconds": 0.01,
                    }
                ),
            },
        ]
        self.assertFalse(run_profile_compat.output_proves_exit_zero(malicious_output))
        malicious_output[1]["text"] = json.dumps(
            {"exit_code": 0, "output": "diff inspected", "wall_time_seconds": True}
        )
        self.assertFalse(run_profile_compat.output_proves_exit_zero(malicious_output))
        malicious_output[1]["text"] = json.dumps(
            {"exit_code": 0, "output": "diff inspected", "wall_time_seconds": 0.01}
        )
        self.assertTrue(run_profile_compat.output_proves_exit_zero(malicious_output))

    def test_rejects_write_profile_and_luna_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            base_command = [
                "python3",
                str(SCRIPT),
                "--profile",
                "developer",
                "--packet",
                str(fixture["packet"]),
                "--cwd",
                str(fixture["project"]),
                "--codex-executable",
                str(fixture["fake"]),
                "--state-db",
                str(fixture["database"]),
                "--model",
                "gpt-5.6-sol",
                "--reasoning-effort",
                "max",
                "--required-read",
                str(fixture["artifact"]),
                "--required-read-marker",
                self.marker,
                "--required-final-marker",
                self.marker,
            ]
            env = os.environ | {"CODEX_HOME": str(fixture["codex_home"])}
            developer = subprocess.run(
                base_command, text=True, capture_output=True, check=False, env=env
            )
            self.assertNotEqual(developer.returncode, 0)
            self.assertIn("only supports read-only", developer.stderr)
            luna_command = [
                "gpt-5.6-luna" if item == "gpt-5.6-sol" else item for item in base_command
            ]
            luna = subprocess.run(
                luna_command, text=True, capture_output=True, check=False, env=env
            )
            self.assertNotEqual(luna.returncode, 0)
            self.assertIn("non-Luna", luna.stderr)

    def test_reviewer_schema_rejects_duplicates_extra_lines_and_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            artifact = project / "artifact.txt"
            artifact.write_text("current value\n", encoding="utf-8")
            valid = (
                "REVIEW_TARGET: artifact.txt\n"
                "REVIEW_READBACK: current value\n"
                "REVIEW_FINDINGS: NONE\n"
                "REVIEW_RESIDUAL_RISK: limited fixture\n"
                "REVIEW_VERDICT: PASS"
            )
            kwargs = {
                "artifact": artifact,
                "project_root": project,
                "markers": ["current value"],
            }
            self.assertEqual(
                run_profile_compat.verify_reviewer_schema(valid, **kwargs)[
                    "review_verdict"
                ],
                "PASS",
            )
            for invalid in (
                valid + "\nEXTRA: value",
                valid.replace(
                    "REVIEW_TARGET: artifact.txt",
                    "REVIEW_TARGET: one\nREVIEW_TARGET: two",
                ),
                valid.replace(
                    "REVIEW_VERDICT: PASS", "REVIEW_VERDICT: PASS_WITH_WARNINGS"
                ),
            ):
                with self.assertRaises(ValueError):
                    run_profile_compat.verify_reviewer_schema(invalid, **kwargs)

    def test_sandbox_policy_requires_structural_read_only_access(self) -> None:
        managed_read_only = json.dumps(
            {
                "type": "managed",
                "file_system": {
                    "type": "restricted",
                    "entries": [{"path": {"type": "special"}, "access": "read"}],
                },
                "network": "restricted",
            }
        )
        self.assertEqual(
            run_profile_compat.verify_read_only_sandbox(managed_read_only)["type"],
            "managed",
        )
        with self.assertRaisesRegex(ValueError, "non-read access"):
            run_profile_compat.verify_read_only_sandbox(
                managed_read_only.replace('"access": "read"', '"access": "write"')
            )
        with self.assertRaisesRegex(ValueError, "restricted managed"):
            run_profile_compat.verify_read_only_sandbox(
                managed_read_only.replace('"network": "restricted"', '"network": "enabled"')
            )
        with self.assertRaisesRegex(ValueError, "structured JSON"):
            run_profile_compat.verify_read_only_sandbox("read-only")
        with self.assertRaisesRegex(ValueError, "restricted managed"):
            run_profile_compat.verify_read_only_sandbox('{"type":"read_only"}')

    def test_current_exec_json_call_format_proves_direct_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.txt"
            artifact.write_text("current fact\n", encoding="utf-8")
            call_input = (
                'const r = await tools.exec_command({"cmd":"/bin/cat artifact.txt",'
                f'"workdir":{json.dumps(str(artifact.parent))},'
                '"yield_time_ms":10000}); text(JSON.stringify(r))'
            )
            self.assertTrue(
                run_profile_compat.command_reads_artifact(call_input, artifact)
            )
            escaped_js_input = (
                'const r = await tools.exec_command({\n'
                '  cmd: "cat artifact.txt",\n'
                f'  workdir: {json.dumps(str(artifact.parent))}\n'
                '}); text(JSON.stringify(r));'
            )
            self.assertTrue(
                run_profile_compat.command_reads_artifact(escaped_js_input, artifact)
            )
            piped = escaped_js_input.replace(
                'cat artifact.txt',
                'cat artifact.txt | wc -l',
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(piped, artifact)
            )

    def test_direct_read_rejects_marker_from_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            artifact = base / "artifact.txt"
            decoy = base / "decoy.txt"
            marker = "DECOY_MARKER_9KQ2"
            artifact.write_text("target bytes only\n", encoding="utf-8")
            decoy.write_text(marker + "\n", encoding="utf-8")
            records = [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "read-1",
                        "input": json.dumps({
                            "cmd": f"sed -n '1,20p' {artifact} {decoy}",
                            "workdir": str(base),
                        }),
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "read-1",
                        "output": [
                            {
                                "type": "input_text",
                                "text": json.dumps(
                                    {
                                        "exit_code": 0,
                                        "output": artifact.read_text(encoding="utf-8")
                                        + decoy.read_text(encoding="utf-8"),
                                        "wall_time_seconds": 0.01,
                                    }
                                ),
                            }
                        ],
                    },
                },
                {"type": "event_msg", "payload": {"type": "task_complete"}},
            ]
            with self.assertRaisesRegex(ValueError, "marker is not present"):
                run_profile_compat.verify_direct_read(records, artifact, [marker])

    def test_direct_read_rejects_multi_command_wrapper_and_decoy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            artifact = base / "artifact.txt"
            decoy = base / "decoy.txt"
            artifact.write_text("artifact bytes\n", encoding="utf-8")
            decoy.write_text("decoy bytes\n", encoding="utf-8")
            multi_call = (
                "const results = await Promise.all(["
                f"tools.exec_command({{\"cmd\":\"cat {artifact}\",\"workdir\":\"{base}\"}}),"
                f"tools.exec_command({{\"cmd\":\"cat {decoy}\",\"workdir\":\"{base}\"}})"
                "]); text(results);"
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(multi_call, artifact)
            )
            reversed_hidden = (
                "const decoy = await tools.exec_command({"
                f'"workdir":"{base}","cmd":"cat {decoy}"}});'
                "const target = await tools.exec_command({"
                f'"cmd":"cat {artifact}","workdir":"{base}"}});'
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(reversed_hidden, artifact)
            )
            bracket_hidden = (
                "const target = await tools.exec_command({"
                f'"cmd":"cat {artifact}","workdir":"{base}"}});'
                "const decoy = await tools[\"exec_command\"]({"
                f'"workdir":"{base}","cmd":"cat {decoy}"}});'
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(bracket_hidden, artifact)
            )
            aliased_hidden = (
                "const run = tools.exec_command;"
                f'run({{"cmd":"cat {artifact}","workdir":"{base}"}});'
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(aliased_hidden, artifact)
            )
            computed_hidden = (
                "const target = await tools.exec_command({"
                f'"cmd":"cat {artifact}","workdir":"{base}"}});'
                "const t = tools; const method = [\"exec\", \"command\"].join(\"_\");"
                f't[method]({{"cmd":"cat {decoy}","workdir":"{base}"}});'
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(computed_hidden, artifact)
            )
            dynamic_bracket = (
                "const target = await tools.exec_command({"
                f'"cmd":"cat {artifact}","workdir":"{base}"}}); '
                "const method = \"exec_\" + \"command\";"
                f'tools[method]({{"workdir":"{base}","cmd":"cat {decoy}"}}); '
                "text(JSON.stringify(target))"
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(dynamic_bracket, artifact)
            )
            dynamic_alias = (
                "const target = await tools.exec_command({"
                f'"cmd":"cat {artifact}","workdir":"{base}"}}); '
                "const t = globalThis[\"to\" + \"ols\"];"
                "const method = \"exec_\" + \"command\";"
                f't[method]({{"workdir":"{base}","cmd":"cat {decoy}"}}); '
                "text(JSON.stringify(target))"
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(dynamic_alias, artifact)
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(
                    json.dumps({"cmd": f"/tmp/cat {artifact}", "workdir": str(base)}),
                    artifact.resolve(),
                )
            )
            self.assertFalse(
                run_profile_compat.command_reads_artifact(
                    json.dumps(
                        {
                            "cmd": f"sed -n '1,20p' {artifact} {decoy}",
                            "workdir": str(base),
                        }
                    ),
                    artifact,
                )
            )

    def test_git_diff_receipt_rejects_arbitrary_git_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            artifact = project / "artifact.txt"
            artifact.write_text("current\n", encoding="utf-8")
            self.assertTrue(
                run_profile_compat.command_reads_git_diff(
                    json.dumps(
                        {"cmd": "git diff -- artifact.txt", "workdir": str(project)}
                    ),
                    project.resolve(),
                    artifact.resolve(),
                )
            )
            for executable in ("./git", "/tmp/git"):
                self.assertFalse(
                    run_profile_compat.command_reads_git_diff(
                        json.dumps(
                            {
                                "cmd": f"{executable} diff -- artifact.txt",
                                "workdir": str(project),
                            }
                        ),
                        project.resolve(),
                        artifact.resolve(),
                    )
                )
    def test_reviewer_schema_binds_target_and_readback_to_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            artifact = project / "artifact.txt"
            artifact.write_text(self.marker + "\n", encoding="utf-8")
            valid = (
                "REVIEW_TARGET: artifact.txt\n"
                f"REVIEW_READBACK: {self.marker}\n"
                "REVIEW_FINDINGS: NONE\n"
                "REVIEW_RESIDUAL_RISK: fixture only\n"
                "REVIEW_VERDICT: PASS"
            )
            parsed = run_profile_compat.verify_reviewer_schema(
                valid,
                artifact=artifact,
                project_root=project,
                markers=[self.marker],
            )
            self.assertEqual(parsed["review_target"], "artifact.txt")
            with self.assertRaisesRegex(ValueError, "target does not match"):
                run_profile_compat.verify_reviewer_schema(
                    valid.replace("artifact.txt", "unrelated.txt", 1),
                    artifact=artifact,
                    project_root=project,
                    markers=[self.marker],
                )
            with self.assertRaisesRegex(ValueError, "readback"):
                run_profile_compat.verify_reviewer_schema(
                    valid.replace(self.marker, "invented fact", 1),
                    artifact=artifact,
                    project_root=project,
                    markers=[self.marker],
                )

    def test_direct_read_requires_structured_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            artifact = base / "artifact.txt"
            marker = "TARGET_MARKER_Z8P1"
            artifact.write_text(marker + "\n", encoding="utf-8")
            records = [
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "read-1",
                        "input": json.dumps({
                            "cmd": f"sed -n '1,20p' {artifact}",
                            "workdir": str(base),
                        }),
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "read-1",
                        "output": [
                            {
                                "type": "input_text",
                                "text": json.dumps(
                                    {
                                        "exit_code": 1,
                                        "output": artifact.read_text(encoding="utf-8"),
                                        "wall_time_seconds": 0.01,
                                    }
                                ),
                            }
                        ],
                    },
                },
                {"type": "event_msg", "payload": {"type": "task_complete"}},
            ]
            with self.assertRaisesRegex(ValueError, "no single direct exec/output pair"):
                run_profile_compat.verify_direct_read(records, artifact, [marker])

    def test_packet_rejects_trailing_blank_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            fixture["packet"].write_text(
                fixture["packet"].read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly 7"):
                run_profile_compat.read_packet(fixture["packet"])

    def test_packet_rejects_predicted_outcome_and_self_recursion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.txt"
            path.write_text(
                "AGENCY_WORKER: true\n"
                "委派目标：使用 $agency-chief-of-staff 审核。\n"
                "读取范围：当前文件。\n"
                "写入范围：禁止。\n"
                "期望产物：REVIEW_RESULT。\n"
                "验证要求：当前读回。\n"
                "停止条件：返回唯一终态；不启动、不派发。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "recursively invoke"):
                run_profile_compat.read_packet(path)

            path.write_text(
                "AGENCY_WORKER: true\n"
                "委派目标：独立审核当前工件。\n"
                "读取范围：当前文件。\n"
                "写入范围：禁止。\n"
                "期望产物：REVIEW_TARGET=README.md，均填实际读回值。\n"
                "验证要求：当前读回。\n"
                "停止条件：返回唯一终态；不启动、不派发。",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected value"):
                run_profile_compat.read_packet(path)

    def test_packet_accepts_benign_failure_and_readme_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.txt"
            path.write_text(
                "AGENCY_WORKER: true\n"
                "委派目标：诊断当前失败测试，并为 README 添加安装说明。\n"
                "读取范围：README.md 与当前测试日志。\n"
                "写入范围：禁止写入。\n"
                "期望产物：DIAGNOSIS_READBACK、DIAGNOSIS_STATUS，均填实际读回值。\n"
                "验证要求：直接读取当前文件并返回实际读回。\n"
                "停止条件：返回唯一终态；不启动、不派发。",
                encoding="utf-8",
            )
            parsed = run_profile_compat.parse_worker_packet(
                run_profile_compat.read_packet(path)
            )
            self.assertIn("失败测试", parsed["委派目标"])

    def test_packet_rejects_values_encoded_as_output_field_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.txt"
            valid = (
                "AGENCY_WORKER: true\n"
                "委派目标：独立审核当前工件。\n"
                "读取范围：当前文件。\n"
                "写入范围：禁止写入。\n"
                "期望产物：WORKER_RESULT。\n"
                "验证要求：直接读取当前文件并返回实际读回。\n"
                "停止条件：返回唯一终态；不启动、不派发。"
            )
            for leaked_schema in (
                "README_MD、PASS，均填实际读回值。",
                "SECRET_MARKER_ABC123，均填实际读回值。",
                "REVIEW_TARGET、PASS，均填实际读回值。",
            ):
                with self.subTest(leaked_schema=leaked_schema):
                    path.write_text(
                        valid.replace("WORKER_RESULT。", leaked_schema),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "not allowlisted"):
                        run_profile_compat.read_packet(path)

    def test_state_database_allows_only_in_home_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            target = codex_home / "sqlite" / "state_5.sqlite"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"sqlite fixture")
            link = codex_home / "state_5.sqlite"
            link.symlink_to(target)
            self.assertEqual(
                run_profile_compat.resolve_state_database(link, codex_home), target.resolve()
            )
            outside = base / "outside.sqlite"
            outside.write_bytes(b"outside")
            link.unlink()
            link.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "inside CODEX_HOME"):
                run_profile_compat.resolve_state_database(link, codex_home)

    def test_timeout_kills_and_archives_started_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_fixture(Path(tmp))
            fixture["slow"].write_text("1", encoding="utf-8")
            result = self.run_compat(fixture, timeout_seconds=1)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exceeded the 1-second limit", result.stderr)
            self.assertIn(self.thread_id, result.stderr)
            connection = sqlite3.connect(fixture["database"])
            archived = connection.execute(
                "SELECT archived FROM threads WHERE id = ?", (self.thread_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(archived, 1)


if __name__ == "__main__":
    unittest.main()
