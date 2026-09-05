from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import agency_doctor  # noqa: E402
import install_skill  # noqa: E402


class AgencyDoctorTests(unittest.TestCase):
    def test_doctor_reads_pair_policies_profiles_and_performs_no_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            skills = base / "skills"
            project.mkdir()
            sentinel = project / "AGENTS.md"
            sentinel.write_text("USER SENTINEL\n", encoding="utf-8")
            for name in install_skill.MANAGED_INSTALL_NAMES:
                install_skill.copy_runtime(ROOT, skills / name, name)
                install_skill.seal_runtime_tree(skills / name)
            native = {
                "codex": "/usr/bin/codex",
                "agents_namespace": {"status": "read", "value": "agents"},
                "task_thread": {"status": "read-surface-available", "create_verified": False},
                "model_catalog": {"status": "live-read", "requested_model_matches": []},
                "error": None,
            }
            with mock.patch.object(agency_doctor, "native_report", return_value=native):
                report = agency_doctor.doctor(project, skills, "codex", 1)
            self.assertEqual(report["status"], "healthy")
            self.assertTrue(report["checks"]["canonical_implicit_true"])
            self.assertTrue(report["checks"]["legacy_implicit_false"])
            self.assertTrue(report["checks"]["discovery_installed"])
            self.assertTrue(report["checks"]["discovery_implicit_true"])
            self.assertTrue(report["canonical"]["permissions_current"])
            self.assertEqual(report["project_agent_profiles"]["present_count"], 0)
            self.assertFalse(report["mutations_performed"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "USER SENTINEL\n")

    def test_doctor_reports_project_agents_routing_conflict_without_editing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            agents = project / "AGENTS.md"
            agents.write_text("BEGIN agency-chief-of-staff routing\n", encoding="utf-8")
            report = agency_doctor.agents_rule_report(project)
            self.assertTrue(report["exists"])
            self.assertTrue(report["conflict"])
            self.assertEqual(
                agents.read_text(encoding="utf-8"),
                "BEGIN agency-chief-of-staff routing\n",
            )

    def test_conflict_and_unavailable_native_surface_are_not_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            skills = base / "skills"
            project.mkdir()
            (project / "AGENTS.md").write_text(
                "BEGIN agency-chief-of-staff routing\n", encoding="utf-8"
            )
            for name in install_skill.MANAGED_INSTALL_NAMES:
                install_skill.copy_runtime(ROOT, skills / name, name)
                install_skill.seal_runtime_tree(skills / name)
            native = {
                "codex": None,
                "agents_namespace": {"status": "unavailable", "value": None},
                "task_thread": {"status": "unavailable", "create_verified": False},
                "model_catalog": {"status": "unavailable", "models": []},
                "error": "unavailable",
            }
            with mock.patch.object(agency_doctor, "native_report", return_value=native):
                report = agency_doctor.doctor(project, skills, "codex", 1)
            self.assertEqual(report["status"], "attention-required")
            self.assertFalse(report["checks"]["project_agents_conflict_free"])
            self.assertFalse(report["checks"]["native_thread_read_surface"])
            self.assertFalse(report["checks"]["native_model_catalog_live"])

    def test_doctor_detects_permission_drift_even_when_hashes_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            skills = base / "skills"
            project.mkdir()
            for name in install_skill.MANAGED_INSTALL_NAMES:
                install_skill.copy_runtime(ROOT, skills / name, name)
                install_skill.seal_runtime_tree(skills / name)
            canonical = skills / install_skill.CANONICAL_SKILL_NAME
            (canonical / "scripts" / "agency_task.py").chmod(0o644)
            report = agency_doctor.bundle_report(
                skills, install_skill.CANONICAL_SKILL_NAME
            )
            self.assertEqual(report["state"], "different")
            self.assertFalse(report["permissions_current"])
            self.assertTrue(
                any("agency_task.py" in item for item in report["permission_mismatches"])
            )


if __name__ == "__main__":
    unittest.main()
