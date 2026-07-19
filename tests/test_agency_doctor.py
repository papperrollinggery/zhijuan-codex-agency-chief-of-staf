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
            for name in install_skill.INSTALL_NAMES:
                install_skill.copy_runtime(ROOT, skills / name, name)
            native = {
                "codex": "/usr/bin/codex",
                "agents_namespace": {"status": "read", "value": "agents"},
                "task_thread": {"status": "read-surface-available", "create_verified": False},
                "model_catalog": {"status": "live-read", "requested_sol_matches": []},
                "error": None,
            }
            with mock.patch.object(agency_doctor, "native_report", return_value=native):
                report = agency_doctor.doctor(project, skills, "codex", 1)
            self.assertEqual(report["status"], "healthy")
            self.assertTrue(report["checks"]["canonical_implicit_true"])
            self.assertTrue(report["checks"]["legacy_implicit_false"])
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


if __name__ == "__main__":
    unittest.main()
