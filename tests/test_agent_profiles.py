from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_agent_profiles.py"
sys.path.insert(0, str(ROOT / "scripts"))
import install_agent_profiles  # noqa: E402
from validate_agent_profiles import PROFILE_NAMES, parse_profile, validate_profile_set  # noqa: E402


class AgentProfileTests(unittest.TestCase):
    def run_installer(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(INSTALLER), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def write_skill(self, root: Path, name: str) -> Path:
        skill = root / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            f"---\nname: {name}\ndescription: test skill\n---\n\n# Test\n",
            encoding="utf-8",
        )
        return skill

    def write_skill_with_name_line(self, root: Path, name_line: str) -> Path:
        skill = root / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            f"---\n{name_line}\ndescription: test skill\n---\n\n# Test\n",
            encoding="utf-8",
        )
        return skill

    def test_source_profiles_and_templates_are_valid_and_equal(self) -> None:
        result = validate_profile_set(ROOT)
        self.assertTrue(result["project_template_parity"])
        self.assertEqual(result["profiles"], list(PROFILE_NAMES))

    def test_explicit_install_preserves_agents_md_and_unmanaged_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            target = project / ".codex" / "agents"
            target.mkdir(parents=True)
            agents_md = project / "AGENTS.md"
            agents_md.write_text("USER SENTINEL\n", encoding="utf-8")
            unmanaged = target / "user-owned.toml"
            unmanaged.write_text('name = "user-owned"\n', encoding="utf-8")

            result = self.run_installer("--target-root", str(target), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "installed")
            self.assertFalse(payload["agents_md_touched"])
            self.assertEqual(agents_md.read_text(encoding="utf-8"), "USER SENTINEL\n")
            self.assertEqual(unmanaged.read_text(encoding="utf-8"), 'name = "user-owned"\n')
            self.assertEqual(
                {path.stem for path in target.glob("*.toml") if path != unmanaged},
                set(PROFILE_NAMES),
            )

    def test_domain_skill_binding_uses_skills_config_and_self_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "project" / ".codex" / "agents"
            domain = self.write_skill(base / "skills", "api-design-test")
            result = self.run_installer(
                "--target-root",
                str(target),
                "--skill",
                f"developer={domain}",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = parse_profile(target / "developer.toml")
            self.assertEqual(
                parsed["skills.config"],
                [{"path": str(domain.resolve()), "enabled": True}],
            )

            self_skill = self.write_skill(base / "self", "agency-chief-of-staff")
            rejected = self.run_installer(
                "--target-root",
                str(base / "other" / ".codex" / "agents"),
                "--skill",
                f"developer={self_skill}",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("recursive self-skill binding", rejected.stderr)

            for index, name_line in enumerate(
                (
                    "name: 'agency-chief-of-staff'",
                    'name: "agency-chief-of-staff" # canonical entry',
                    "name: zhijuan-codex-agency-chief-of-staf # legacy entry",
                )
            ):
                disguised = self.write_skill_with_name_line(
                    base / f"disguised-{index}", name_line
                )
                disguised_result = self.run_installer(
                    "--target-root",
                    str(base / f"disguised-target-{index}" / ".codex" / "agents"),
                    "--skill",
                    f"developer={disguised}",
                )
                self.assertNotEqual(disguised_result.returncode, 0)
                self.assertIn("recursive self-skill binding", disguised_result.stderr)

    def test_conflict_fails_closed_and_force_replaces_only_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "project" / ".codex" / "agents"
            first = self.run_installer("--target-root", str(target))
            self.assertEqual(first.returncode, 0, first.stderr)
            managed = target / "developer.toml"
            managed.write_text("user changed managed profile\n", encoding="utf-8")
            unmanaged = target / "custom.toml"
            unmanaged.write_text("keep\n", encoding="utf-8")

            conflict = self.run_installer("--target-root", str(target))
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("differ", conflict.stderr)
            forced = self.run_installer("--target-root", str(target), "--force")
            self.assertEqual(forced.returncode, 0, forced.stderr)
            self.assertEqual(parse_profile(managed)["name"], "developer")
            self.assertEqual(unmanaged.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse(list(target.glob(".*.backup-*")))

    def test_target_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real = base / "real"
            real.mkdir()
            target = base / "project" / ".codex" / "agents"
            target.parent.mkdir(parents=True)
            target.symlink_to(real, target_is_directory=True)
            result = self.run_installer("--target-root", str(target))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not traverse a symlink", result.stderr)

    def test_parent_codex_symlink_and_non_project_targets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            external = base / "external"
            external.mkdir()
            project = base / "project"
            project.mkdir()
            (project / ".codex").symlink_to(external, target_is_directory=True)

            redirected = self.run_installer(
                "--target-root", str(project / ".codex" / "agents")
            )
            self.assertNotEqual(redirected.returncode, 0)
            self.assertIn("must not traverse a symlink", redirected.stderr)
            self.assertFalse((external / "agents").exists())

            wrong_suffix = self.run_installer(
                "--target-root", str(base / "project" / "agents")
            )
            self.assertNotEqual(wrong_suffix.returncode, 0)
            self.assertIn("must end with project/.codex/agents", wrong_suffix.stderr)

            relative = self.run_installer("--target-root", ".codex/agents")
            self.assertNotEqual(relative.returncode, 0)
            self.assertIn("must be an absolute", relative.stderr)

    def test_backup_cleanup_failure_is_reported_after_verified_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "project" / ".codex" / "agents"
            source = ROOT
            install_agent_profiles.install_profiles(source, target, {}, False, False)
            (target / "developer.toml").write_text(
                "user changed managed profile\n", encoding="utf-8"
            )
            real_remove = install_agent_profiles.best_effort_remove

            def fail_backup_cleanup(path: Path) -> bool:
                if ".backup-" in path.name:
                    return False
                return real_remove(path)

            with mock.patch.object(
                install_agent_profiles,
                "best_effort_remove",
                side_effect=fail_backup_cleanup,
            ):
                with self.assertRaisesRegex(RuntimeError, "backup cleanup failed"):
                    install_agent_profiles.install_profiles(
                        source, target, {}, True, False
                    )

            self.assertEqual(parse_profile(target / "developer.toml")["name"], "developer")


if __name__ == "__main__":
    unittest.main()
