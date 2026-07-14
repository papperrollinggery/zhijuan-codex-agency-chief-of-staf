from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
            ["python3", str(root / "scripts" / "validate_package.py"), str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

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

    def test_rejects_malformed_openai_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "agents" / "openai.yaml"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    'display_name: "Zhijuan 可视化结果幕僚长"',
                    'display_name: "unterminated',
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid quoted value", result.stderr)

    def test_rejects_backstage_terms_in_visible_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "assets" / "visualizations" / "task-surface.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "任务正在推进",
                    "请查看 JSON 与 sha256",
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exposes backstage term", result.stderr)

    def test_rejects_visualization_surface_registry_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "assets" / "visualizations" / "surface-registry.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('"kind": "numeric-trend"', '"kind": "decorative-curve"'), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported surface set", result.stderr)

    def test_rejects_hover_dependent_task_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "assets" / "visualizations" / "task-surface.html"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "</style>",
                    ".card:hover{transform:scale(1.01)}</style>",
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hover-only styling", result.stderr)

    def test_rejects_network_and_animation_in_task_visualization(self) -> None:
        for injection, expected in (
            ('<img src="https://example.invalid/a.png">', "external resources"),
            ('<style>.card{background-image:url(https://example.invalid/a.png)}</style>', "network-capable"),
            ('<style>@keyframes pulse{to{opacity:.5}}</style>', "animate or transition"),
        ):
            with self.subTest(injection=injection), tempfile.TemporaryDirectory() as tmp:
                root = self.make_copy(Path(tmp))
                path = root / "assets" / "visualizations" / "task-surface.html"
                path.write_text(path.read_text(encoding="utf-8").replace("</body>", injection + "</body>"), encoding="utf-8")
                result = self.validate(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_rejects_missing_visualization_behavior_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace('"id": "visualized-dependent-stages"', '"id": "missing-stage-case"'), encoding="utf-8")
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing visualization coverage", result.stderr)

    def test_rejects_role_model_case_removed_from_model_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            marker = '"id": "role-model-balanced-budget"'
            start = text.index(marker)
            smoke = text.index('"model_smoke": true', start)
            path.write_text(
                text[:smoke] + '"model_smoke": false' + text[smoke + len('"model_smoke": true'):],
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required model smoke", result.stderr)

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

    def test_rejects_worker_and_reviewer_packet_outcome_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "返回唯一终态；不启动、不派发。",
                    "返回唯一终态；不启动、不派发。SENTINEL_Z9K4",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("complete packet", result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            path = root / "evals" / "behavior_cases.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "reviewer 不得输出 COS_BOOT_RECEIPT 或进度；主线程不得把第一行内容转述给 reviewer。",
                    "reviewer 不得输出 COS_BOOT_RECEIPT 或进度；REVIEW_VERDICT: GO。",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review verdict", result.stderr)

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
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_copy(Path(tmp))
            (root / "AGENTS.md").write_text(
                "<!-- BEGIN zhijuan-codex-agency-chief-of-staf routing -->\n",
                encoding="utf-8",
            )
            result = self.validate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("root AGENTS.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
