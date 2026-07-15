from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelSmokeEntrypointTests(unittest.TestCase):
    def eval_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_EVAL_AUTH_JSON": "/credentials/eval auth.json",
                "CODEX_EVAL_CODEX": "/opt/Codex App/codex",
                "CODEX_EVAL_MODEL": "current-judgment-model",
                "CODEX_EVAL_REASONING_EFFORT": "high",
                "CODEX_EVAL_CATALOG": "/receipts/current catalog.json",
                "CODEX_EVAL_STATE_DB": "/state/Codex Home/state_5.sqlite",
                "CODEX_EVAL_THREAD_ID": "019f0000-0000-7000-8000-000000000000",
                "CODEX_EVAL_CATALOG_CWD": "/workspace/current project",
                "CODEX_EVAL_AUTH_CLASS": "dedicated",
            }
        )
        environment.pop("CODEX_HOME", None)
        return environment

    def test_make_target_fails_before_runner_when_release_identity_is_missing(self) -> None:
        required = {
            "CODEX_EVAL_MODEL": "set CODEX_EVAL_MODEL",
            "CODEX_EVAL_REASONING_EFFORT": "set CODEX_EVAL_REASONING_EFFORT",
            "CODEX_EVAL_CATALOG": "set CODEX_EVAL_CATALOG",
            "CODEX_EVAL_STATE_DB": "set CODEX_EVAL_STATE_DB",
            "CODEX_EVAL_THREAD_ID": "set CODEX_EVAL_THREAD_ID",
            "CODEX_EVAL_CATALOG_CWD": "set CODEX_EVAL_CATALOG_CWD",
        }
        for variable, expected_message in required.items():
            with self.subTest(variable=variable):
                environment = self.eval_environment()
                environment.pop(variable)
                result = subprocess.run(
                    ["make", "model-smoke"],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_message, result.stderr)

    def test_make_target_forwards_exact_release_identity_and_optional_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake_python = bin_dir / "python3"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = self.eval_environment()
            environment["PATH"] = f"{bin_dir}{os.pathsep}{environment.get('PATH', '')}"
            environment["CODEX_HOME"] = "/state/Alternate Codex Home"

            result = subprocess.run(
                ["make", "model-smoke"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = result.stdout.splitlines()
        self.assertEqual(arguments[:3], ["-I", "-S", "scripts/run_model_evals.py"])
        self.assertEqual(
            arguments[3:],
            [
                "--root",
                ".",
                "--out",
                next(value for value in arguments if value.startswith("validation/current/model-smoke-")),
                "--codex-executable",
                "/opt/Codex App/codex",
                "--model",
                "current-judgment-model",
                "--reasoning-effort",
                "high",
                "--catalog",
                "/receipts/current catalog.json",
                "--catalog-state-db",
                "/state/Codex Home/state_5.sqlite",
                "--catalog-thread-id",
                "019f0000-0000-7000-8000-000000000000",
                "--catalog-cwd",
                "/workspace/current project",
                "--catalog-codex-home",
                "/state/Alternate Codex Home",
                "--auth-json",
                "/credentials/eval auth.json",
                "--auth-credential-class",
                "dedicated",
                "--acknowledge-auth-readable-to-eval-process",
            ],
        )

    def test_isolated_runner_rejects_ignored_stdlib_shadow_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            scripts = repo / "scripts"
            shutil.copytree(
                ROOT / "scripts",
                scripts,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "add", "scripts"], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Model Smoke Bootstrap Test",
                    "-c",
                    "user.email=model-smoke@example.invalid",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                check=True,
            )
            sentinel = repo / "shadow-executed"
            (scripts / "json.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed')\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(scripts / "run_model_evals.py"),
                    "--help",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("local import tree differs", result.stderr)
            self.assertFalse(sentinel.exists())

            (scripts / "json.py").unlink()
            cache = scripts / "__pycache__"
            cache.mkdir()
            attack_source = repo / "unchecked_attack.py"
            attack_source.write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('unchecked-pyc-executed')\n",
                encoding="utf-8",
            )
            py_compile.compile(
                str(attack_source),
                cfile=str(cache / f"install_skill.{sys.implementation.cache_tag}.pyc"),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
            )
            pyc_result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(scripts / "run_model_evals.py"),
                    "--help",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(pyc_result.returncode, 0)
            self.assertIn("local import tree differs", pyc_result.stderr)
            self.assertFalse(sentinel.exists())

    def test_contributing_example_uses_the_make_contract(self) -> None:
        text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        mappings = {
            "--codex-executable": "CODEX_EVAL_CODEX",
            "--model": "CODEX_EVAL_MODEL",
            "--reasoning-effort": "CODEX_EVAL_REASONING_EFFORT",
            "--catalog": "CODEX_EVAL_CATALOG",
            "--catalog-state-db": "CODEX_EVAL_STATE_DB",
            "--catalog-thread-id": "CODEX_EVAL_THREAD_ID",
            "--catalog-cwd": "CODEX_EVAL_CATALOG_CWD",
        }
        for flag, variable in mappings.items():
            with self.subTest(flag=flag):
                self.assertIn(f'{flag} "${variable}"', text)
        self.assertIn("A primary credential or an unverified binding remains diagnostic", text)


if __name__ == "__main__":
    unittest.main()
