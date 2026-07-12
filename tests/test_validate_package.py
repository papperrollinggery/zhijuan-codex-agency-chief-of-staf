from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_GIT = next(
    path.resolve()
    for path in (
        Path("/usr/bin/git"),
        Path("/bin/git"),
        Path("/usr/local/bin/git"),
        Path("/opt/homebrew/bin/git"),
    )
    if path.is_file()
)


class ValidatePackageMutationTests(unittest.TestCase):
    def make_copy(self, base: Path) -> Path:
        target = base / "package"
        shutil.copytree(
            ROOT,
            target,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "validation", "*.pyc"),
        )
        return target

    def validate(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "validate_package.py"),
                "--git-executable",
                str(TRUSTED_GIT),
                str(root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def git(self, root: Path, *args: str) -> None:
        subprocess.run(
            [str(TRUSTED_GIT), "-C", str(root), *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
        )

    def test_current_package_is_valid(self) -> None:
        result = self.validate(ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 generated bundles", result.stdout)

    def test_rejects_noncanonical_authored_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "SKILL.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "name: agency-chief-of-staff",
                    "name: zhijuan-codex-agency-chief-of-staf",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected SKILL.md skill name", result.stderr)

    def test_rejects_missing_verified_boot_sequence_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "then read only this bundle's SKILL.md in full before any other action or progress, and immediately output COS_BOOT_RECEIPT. ",
                "",
                1,
            )
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("verified boot-sequence contract", result.stderr)

    def test_rejects_unquoted_colon_in_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace('description: "', "description: ", 1)
            text = text.replace('true."\n---', "true.\n---", 1)
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("YAML-quoted", result.stderr)

    def test_rejects_agents_routing_in_active_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "SKILL.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nAGENTS_ROUTING_SNIPPET\n",
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("routing injection marker", result.stderr)

    def test_rejects_conflicting_runtime_review_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "references" / "delivery-review.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "COLD_CONTEXT_ISOLATION: UNVERIFIED",
                    "cold-context isolation 未验证",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical review disclosure", result.stderr)

    def test_rejects_missing_runtime_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            (root / "references" / "real-threads.md").unlink()
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing file", result.stderr)

    def test_rejects_installer_manifest_self_proof_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            text = path.read_text(encoding="utf-8")
            text = text.replace('    "SKILL.md",\n', "", 1)
            text = text.replace('    "agents/openai.yaml",\n', "", 1)
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("independent package contract", result.stderr)

    def test_rejects_installer_skill_name_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'CANONICAL_SKILL_NAME = "agency-chief-of-staff"',
                    'CANONICAL_SKILL_NAME = "agency-chief-of-staff-mutated"',
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Skill names drifted", result.stderr)

    def test_rejects_generated_manifest_self_proof_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "        for rel in RUNTIME_FILES\n    }\n\n\ndef runtime_manifest",
                '        for rel in RUNTIME_FILES if rel != "SKILL.md"\n    }\n\n\ndef runtime_manifest',
                1,
            )
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manifest keys drifted", result.stderr)

    def test_rejects_legacy_implicit_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "  allow_implicit_invocation: false",
                    "  allow_implicit_invocation: true",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("allow_implicit_invocation must be false", result.stderr)

    def test_rejects_legacy_description_without_explicit_only_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    " invocation only.",
                    " invocation.",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit-only compatibility contract", result.stderr)

    def test_rejects_legacy_entrypoint_rendering_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '.replace("入口：canonical", "入口：legacy")',
                    '.replace("入口：canonical", "入口：canonical")',
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("legacy boot entrypoint", result.stderr)

    def test_rejects_legacy_activation_wording_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "        CANONICAL_ACTIVATION_SENTENCE, LEGACY_ACTIVATION_SENTENCE, 1",
                    "        CANONICAL_ACTIVATION_SENTENCE, CANONICAL_ACTIVATION_SENTENCE, 1",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit-only main-session activation", result.stderr)

    def test_rejects_legacy_drift_in_shared_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "scripts" / "install_skill.py"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                '    if rel == "agents/openai.yaml":\n',
                '    if rel == "references/real-threads.md":\n'
                '        return content + b"\\nlegacy-only-drift\\n"\n'
                '    if rel == "agents/openai.yaml":\n',
                1,
            )
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("may differ only", result.stderr)

    def test_rejects_malformed_openai_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "agents" / "openai.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    'display_name: "Zhijuan 结果负责型 Codex 幕僚长"',
                    'display_name: "unterminated',
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid quoted value", result.stderr)

    def test_rejects_unsafe_model_case_paths_and_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            text = text.replace('"id": "explicit-write-execute"', '"id": "../escape"', 1)
            text = text.replace('"sandbox": "workspace-write"', '"sandbox": "danger-full-access"', 1)
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe behavior case id", result.stderr)

    def test_rejects_worker_packet_with_empty_required_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "委派目标：只读 README 并返回 WORKER_RESULT。",
                "委派目标：",
                1,
            )
            path.write_text(text, encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("complete packet", result.stderr)

    def test_rejects_guard_bundle_that_does_not_match_worker_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "delegated-worker-bypass")
            case["allowed_guard_bundle"] = "legacy"
            path.write_text(
                json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uniquely match its explicit $slug", result.stderr)

    def test_rejects_missing_required_model_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "legacy-explicit-small-direct")
            case["model_smoke"] = False
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("full semantic contract drifted", result.stderr)

    def test_rejects_required_model_smoke_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "dual-explicit-canonical-priority")
            case["mode"] = "structured"
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "dual-explicit-canonical-priority full semantic contract drifted",
                result.stderr,
            )

    def test_rejects_required_model_smoke_prompt_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "explicit-small-direct")
            case["prompt"] += " 请简短回答。"
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("full semantic contract drifted", result.stderr)

    def test_rejects_missing_collaboration_boot_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(
                item for item in cases if item["id"] == "explicit-full-cycle"
            )
            del case["expected_boot_receipt"]
            path.write_text(
                json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "collaboration evidence requires an exact boot receipt",
                result.stderr,
            )

    def test_rejects_non_smoke_behavior_case_prompt_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "explicit-real-task")
            case["prompt"] = "hello"
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "explicit-real-task full semantic contract drifted",
                result.stderr,
            )

    def test_rejects_legacy_slug_in_public_prompt_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "examples" / "real-world-prompts.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "$agency-chief-of-staff",
                    "$zhijuan-codex-agency-chief-of-staf",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must use the canonical Skill slug", result.stderr)

    def test_rejects_malformed_public_worker_bypass_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "examples" / "real-world-prompts.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "AGENCY_WORKER: true\n使用 $agency-chief-of-staff。",
                    "使用 $agency-chief-of-staff。AGENCY_WORKER: true",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("public worker bypass example must start", result.stderr)

    def test_rejects_required_model_smoke_oracle_and_artifact_drift(self) -> None:
        mutations = (
            ("explicit-small-direct", "require_tool_event", False),
            ("explicit-small-direct", "must_contain", ["COS_BOOT_RECEIPT"]),
            ("explicit-small-direct", "must_not_contain", ["UNREVIEWED"]),
            ("explicit-write-execute", "expected_file", "renamed-README.md"),
            ("explicit-write-execute", "expected_text", "changed expected text"),
            (
                "explicit-write-execute",
                "expected_file_content",
                "# Agency model-eval fixture [readback-{runtime_nonce}]\n\n"
                "Repository name: agency-model-eval-fixture-v2.\n\n",
            ),
            (
                "explicit-write-execute",
                "review_evidence_marker",
                "Agency model-eval fixture [readback-{runtime_nonce}]",
            ),
            ("explicit-write-execute", "review_evidence_tier", "stable"),
            ("ordinary-small-answer", "exact_final", "您好"),
            ("ordinary-small-answer", "require_no_tool_events", False),
        )
        for case_id, key, value in mutations:
            with self.subTest(case_id=case_id, key=key), tempfile.TemporaryDirectory() as tmp:
                root = self.make_copy(Path(tmp))
                path = root / "evals" / "behavior_cases.json"
                cases = json.loads(path.read_text(encoding="utf-8"))
                case = next(item for item in cases if item["id"] == case_id)
                case[key] = value
                path.write_text(
                    json.dumps(cases, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                result = self.validate(root)
                self.assertNotEqual(result.returncode, 0)
                expected_error = (
                    "strict reviewer packet must match the canonical contract"
                    if case_id == "explicit-write-execute" and key == "expected_file"
                    else "full semantic contract drifted"
                )
                self.assertIn(
                    expected_error,
                    result.stderr,
                )

    def test_rejects_inconsistent_exact_output_and_isolation_oracles(self) -> None:
        mutations = (
            ("ordinary-small-answer", "exact_final", 7, "exact_final"),
            (
                "explicit-small-direct",
                "require_no_tool_events",
                True,
                "cannot require both tool use and no tool use",
            ),
            (
                "explicit-small-direct",
                "require_context_isolation",
                True,
                "context isolation requires",
            ),
        )
        for case_id, key, value, expected_error in mutations:
            with self.subTest(case_id=case_id, key=key), tempfile.TemporaryDirectory() as tmp:
                root = self.make_copy(Path(tmp))
                path = root / "evals" / "behavior_cases.json"
                cases = json.loads(path.read_text(encoding="utf-8"))
                case = next(item for item in cases if item["id"] == case_id)
                case[key] = value
                path.write_text(
                    json.dumps(cases, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                result = self.validate(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_rejects_high_confidence_secret_material(self) -> None:
        secret_samples = (
            ("openai", "sk-" + "A" * 32),
            ("github", "ghp_" + "B" * 36),
            ("slack", "xoxb-" + "1234567890-" + "C" * 32),
            ("private-key", "-----BEGIN " + "PRIVATE KEY-----"),
        )
        for label, secret in secret_samples:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = self.make_copy(Path(tmp))
                path = root / "README.md"
                path.write_text(
                    path.read_text(encoding="utf-8") + f"\nCredential: {secret}\n",
                    encoding="utf-8",
                )
                result = self.validate(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("high-confidence secret detected", result.stderr)
                self.assertNotIn(secret, result.stderr)

    def test_allows_redacted_secret_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "README.md"
            placeholders = "\n".join(
                (
                    "OPENAI_API_KEY=<set-me>",
                    "sk-example",
                    "ghp_REDACTED",
                    "xoxb-placeholder",
                    "-----BEGIN PUBLIC KEY-----",
                )
            )
            path.write_text(
                path.read_text(encoding="utf-8") + "\n" + placeholders + "\n",
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_force_added_secret_under_validation_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            self.git(root, "init", "-q")
            tracked = root / "validation" / "current" / "tracked-receipt.txt"
            tracked.parent.mkdir(parents=True)
            secret = "sk-" + "T" * 32
            tracked.write_text(f"credential={secret}\n", encoding="utf-8")
            self.git(root, "add", "-f", "--", "validation/current/tracked-receipt.txt")

            result = self.validate(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("high-confidence secret detected", result.stderr)
            self.assertIn("validation/current/tracked-receipt.txt", result.stderr)
            self.assertNotIn(secret, result.stderr)

    def test_rejects_force_added_symlink_under_validation_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self.make_copy(base)
            self.git(root, "init", "-q")
            external = base / "external.txt"
            external.write_text("outside publication root\n", encoding="utf-8")
            tracked = root / "validation" / "current" / "tracked-link.txt"
            tracked.parent.mkdir(parents=True)
            tracked.symlink_to(external)
            self.git(root, "add", "-f", "--", "validation/current/tracked-link.txt")

            result = self.validate(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("contains a symlink", result.stderr)

    def test_git_worktree_requires_public_gate_dependencies_to_be_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            self.git(root, "init", "-q")
            self.git(root, "add", "--", ".")
            self.git(
                root,
                "rm",
                "--cached",
                "--",
                "scripts/trusted_gate_helpers.sh",
            )

            result = self.validate(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("required public files that are not tracked", result.stderr)
            self.assertIn("scripts/trusted_gate_helpers.sh", result.stderr)

    def test_release_smoke_ignores_ambient_path_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            poison = base / "poison-bin"
            poison.mkdir()
            sentinel = base / "ambient-helper-was-used"
            bash_env_sentinel = base / "bash-env-was-sourced"
            bash_env = base / "bash-env.sh"
            bash_env.write_text(
                f"printf 'sourced\\n' >{str(bash_env_sentinel)!r}\n",
                encoding="utf-8",
            )
            python_poison = base / "python-poison"
            python_poison.mkdir()
            python_sentinel = base / "sitecustomize-was-imported"
            (python_poison / "sitecustomize.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(python_sentinel)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            for name in ("python3", "bash", "git", "mktemp", "rm"):
                helper = poison / name
                helper.write_text(
                    "#!/bin/sh\n"
                    f"printf '%s\\n' {name!r} >>\"$POISON_SENTINEL\"\n"
                    "exit 97\n",
                    encoding="utf-8",
                )
                helper.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(poison)
            env["POISON_SENTINEL"] = str(sentinel)
            env["BASH_ENV"] = str(bash_env)
            env["PYTHONPATH"] = str(python_poison)

            result = subprocess.run(
                [
                    "/bin/bash",
                    "-p",
                    str(ROOT / "scripts" / "release_smoke.sh"),
                    str(ROOT),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Release smoke passed", result.stdout)
            self.assertFalse(sentinel.exists())
            self.assertFalse(bash_env_sentinel.exists())
            self.assertFalse(python_sentinel.exists())

    def test_release_smoke_rejects_symlink_launcher_before_sourcing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            launcher = base / "release_smoke.sh"
            launcher.symlink_to(ROOT / "scripts" / "release_smoke.sh")
            sentinel = base / "untrusted-helper-was-sourced"
            (base / "trusted_gate_helpers.sh").write_text(
                f"printf 'sourced\\n' >{str(sentinel)!r}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["/bin/bash", "-p", str(launcher), str(ROOT)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not be invoked through a symlink", result.stderr)
            self.assertFalse(sentinel.exists())

    def test_release_smoke_rejects_non_privileged_bash_entry(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "scripts" / "release_smoke.sh"), str(ROOT)],
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": os.defpath},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires /bin/bash -p", result.stderr)

    def test_model_smoke_wrapper_ignores_ambient_python_and_shell_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            poison = base / "poison-bin"
            poison.mkdir()
            helper_sentinel = base / "ambient-python-was-used"
            bash_env_sentinel = base / "bash-env-was-sourced"
            bash_env = base / "bash-env.sh"
            bash_env.write_text(
                f"printf 'sourced\\n' >{str(bash_env_sentinel)!r}\n",
                encoding="utf-8",
            )
            python_sentinel = base / "sitecustomize-was-imported"
            (poison / "sitecustomize.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(python_sentinel)!r}).write_text('imported')\n",
                encoding="utf-8",
            )
            fake_python = poison / "python3"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"printf 'used\\n' >{str(helper_sentinel)!r}\n"
                "exit 97\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": str(poison),
                    "PYTHONPATH": str(poison),
                    "BASH_ENV": str(bash_env),
                }
            )
            result = subprocess.run(
                [
                    "/bin/bash",
                    "-p",
                    str(ROOT / "scripts" / "model_smoke.sh"),
                    "--help",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Run real Codex model smoke cases", result.stdout)
            self.assertFalse(helper_sentinel.exists())
            self.assertFalse(bash_env_sentinel.exists())
            self.assertFalse(python_sentinel.exists())

    def test_model_smoke_wrapper_rejects_symlink_and_non_privileged_bash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "model_smoke.sh"
            launcher.symlink_to(ROOT / "scripts" / "model_smoke.sh")
            linked = subprocess.run(
                ["/bin/bash", "-p", str(launcher), "--help"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(linked.returncode, 0)
            self.assertIn("must not be invoked through a symlink", linked.stderr)

        non_privileged = subprocess.run(
            ["/bin/bash", str(ROOT / "scripts" / "model_smoke.sh"), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env={"PATH": os.defpath},
        )
        self.assertNotEqual(non_privileged.returncode, 0)
        self.assertIn("requires /bin/bash -p", non_privileged.stderr)

    def test_rejects_weakened_exact_entrypoint_marker_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "explicit-small-direct")
            case["exact_marker_counts"]["COS_BOOT_RECEIPT"] = 0
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("weakens exact entrypoint marker counts", result.stderr)

    def test_rejects_nonexact_marker_count_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            cases = json.loads(path.read_text(encoding="utf-8"))
            case = next(item for item in cases if item["id"] == "ordinary-small-answer")
            case["exact_marker_counts"]["unreviewed-marker"] = 0
            path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid exact_marker_counts", result.stderr)

    def test_rejects_machine_specific_fixture_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "history_threads.sample.json"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "/tmp/agency-history/source-repo",
                    "/" + "Users/example/private-repo",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("machine-specific path", result.stderr)

    def test_rejects_missing_security_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            (root / "SECURITY.md").unlink()
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required files", result.stderr)

    def test_scans_security_policy_for_machine_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "SECURITY.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nPrivate path: /" + "Users/example/private\n",
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("machine-specific path", result.stderr)

    def test_rejects_root_agents_routing_reintroduction(self) -> None:
        for slug in ("agency-chief-of-staff", "zhijuan-codex-agency-chief-of-staf"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as tmp:
                root = self.make_copy(Path(tmp))
                (root / "AGENTS.md").write_text(
                    f"<!-- BEGIN {slug} routing -->\n",
                    encoding="utf-8",
                )
                result = self.validate(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("root AGENTS.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
