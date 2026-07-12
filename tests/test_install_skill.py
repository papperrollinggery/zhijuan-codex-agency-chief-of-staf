from __future__ import annotations

import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_skill.py"
sys.path.insert(0, str(ROOT / "scripts"))
import install_skill  # noqa: E402


class InstallSkillTests(unittest.TestCase):
    def run_installer(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(INSTALLER), *args],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_minimal_install_never_touches_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            target_root = base / "skills"
            project.mkdir()
            agents = project / "AGENTS.md"
            agents.write_text("USER SENTINEL\n", encoding="utf-8")

            result = self.run_installer(
                "--target-root", str(target_root), "--json", cwd=project
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["agents_md_touched"])
            self.assertEqual(agents.read_text(encoding="utf-8"), "USER SENTINEL\n")

            self.assertEqual(set(payload["targets"]), set(install_skill.INSTALL_NAMES))
            for skill_name in install_skill.INSTALL_NAMES:
                installed = target_root / skill_name
                files = {
                    str(path.relative_to(installed))
                    for path in installed.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(files, set(payload["manifests"][skill_name]))
                self.assertNotIn("README.md", files)
                self.assertNotIn("AGENTS.md", files)
            legacy_yaml = (
                target_root / install_skill.LEGACY_SKILL_NAME / "agents/openai.yaml"
            ).read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", legacy_yaml)

    def test_force_replaces_stale_runtime_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            first = self.run_installer("--target-root", str(target_root))
            self.assertEqual(first.returncode, 0, first.stderr)
            installed = target_root / "zhijuan-codex-agency-chief-of-staf"
            (installed / "stale.txt").write_text("stale", encoding="utf-8")

            replaced = self.run_installer("--target-root", str(target_root), "--force")
            self.assertEqual(replaced.returncode, 0, replaced.stderr)
            self.assertFalse((installed / "stale.txt").exists())
            self.assertFalse(list(target_root.glob(".*.staging-*")))
            self.assertFalse(list(target_root.glob(".*.backup-*")))

    def test_removed_agents_routing_flag_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            agents = project / "AGENTS.md"
            agents.write_text("USER SENTINEL\n", encoding="utf-8")
            result = self.run_installer(
                "--target-root", str(base / "skills"),
                "--agents-routing", "project",
                cwd=project,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(agents.read_text(encoding="utf-8"), "USER SENTINEL\n")

    def test_removed_name_flag_cannot_select_a_partial_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_installer(
                "--target-root", str(Path(tmp) / "skills"), "--name", "../escape"
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertFalse((Path(tmp) / "escape").exists())

    def test_refuses_to_replace_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target_root = base / "skills"
            destination = base / "external-skill"
            target_root.mkdir()
            destination.mkdir()
            (destination / "sentinel.txt").write_text("keep", encoding="utf-8")
            (target_root / "zhijuan-codex-agency-chief-of-staf").symlink_to(
                destination, target_is_directory=True
            )

            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "conflict")
            self.assertIn("symlink", payload["message"])
            self.assertEqual(
                (destination / "sentinel.txt").read_text(encoding="utf-8"), "keep"
            )

    def test_refuses_nested_symlink_before_reading_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target_root = base / "skills"
            installed = target_root / "zhijuan-codex-agency-chief-of-staf"
            external = base / "external.txt"
            installed.mkdir(parents=True)
            external.write_text("DO NOT READ OR REPLACE", encoding="utf-8")
            (installed / "linked.txt").symlink_to(external)

            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "conflict")
            self.assertIn("symlink", payload["message"])
            self.assertEqual(external.read_text(encoding="utf-8"), "DO NOT READ OR REPLACE")

    def test_runtime_source_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            package = base / "package"
            external = base / "external.md"
            package.mkdir()
            external.write_text("external", encoding="utf-8")
            (package / "SKILL.md").symlink_to(external)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                install_skill.runtime_source_path(package, "SKILL.md")

    def test_backup_cleanup_failure_keeps_verified_new_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "skills" / "zhijuan-codex-agency-chief-of-staf"
            target.mkdir(parents=True)
            (target / "stale.txt").write_text("old", encoding="utf-8")
            real_rmtree = install_skill.shutil.rmtree

            def flaky_rmtree(path: object, *args: object, **kwargs: object) -> None:
                candidate = Path(path)  # type: ignore[arg-type]
                if ".backup-" in candidate.name:
                    stale = candidate / "stale.txt"
                    if stale.exists():
                        stale.unlink()
                    raise OSError("injected backup cleanup failure")
                real_rmtree(candidate, *args, **kwargs)

            with mock.patch.object(install_skill.shutil, "rmtree", side_effect=flaky_rmtree):
                install_skill.replace_from_staging(ROOT, target)

            self.assertEqual(
                install_skill.installed_manifest(target),
                install_skill.runtime_manifest(ROOT, install_skill.LEGACY_SKILL_NAME),
            )
            self.assertFalse((target / "stale.txt").exists())

    def test_force_replaces_regular_file_without_backup_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            target_root.mkdir()
            target = target_root / "zhijuan-codex-agency-chief-of-staf"
            target.write_text("stale regular file", encoding="utf-8")

            result = self.run_installer("--target-root", str(target_root), "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_dir())
            self.assertEqual(
                install_skill.installed_manifest(target),
                install_skill.runtime_manifest(ROOT, install_skill.LEGACY_SKILL_NAME),
            )
            self.assertFalse(list(target_root.glob(".*.backup-*")))

    def test_failed_backup_rename_preserves_existing_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "skills" / "zhijuan-codex-agency-chief-of-staf"
            target.mkdir(parents=True)
            sentinel = target / "sentinel.txt"
            sentinel.write_text("keep existing install", encoding="utf-8")
            real_rename = Path.rename

            def fail_target_backup_rename(path: Path, destination: object) -> Path:
                destination_path = Path(destination)  # type: ignore[arg-type]
                if path == target and ".backup-" in destination_path.name:
                    raise OSError("injected target-to-backup rename failure")
                return real_rename(path, destination_path)

            with mock.patch.object(Path, "rename", autospec=True, side_effect=fail_target_backup_rename):
                with self.assertRaisesRegex(OSError, "target-to-backup"):
                    install_skill.replace_from_staging(ROOT, target)

            self.assertTrue(target.is_dir())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep existing install")
            self.assertFalse(list(target.parent.glob(".*.backup-*")))


if __name__ == "__main__":
    unittest.main()
