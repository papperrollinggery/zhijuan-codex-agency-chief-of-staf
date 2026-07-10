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
