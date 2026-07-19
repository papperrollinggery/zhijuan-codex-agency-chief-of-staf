from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, knowledge_candidate

sys.path.insert(0, str(ROOT / "scripts"))
from deposit_knowledge import deposit_knowledge, validate_knowledge_candidates  # noqa: E402


class KnowledgeDepositTests(unittest.TestCase):
    def write_candidates(self, project: Path, candidates: list[dict[str, object]]) -> Path:
        path = project / "knowledge-candidates.json"
        path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_existing_matching_document_is_updated_without_creating_duplicate_doc(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "docs/testing/unit-tests.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Unit Tests\n", encoding="utf-8")
            candidates = self.write_candidates(project, [knowledge_candidate()])
            first = deposit_knowledge(project, candidates, apply=True)
            second = deposit_knowledge(project, candidates, apply=True)
            self.assertEqual(first["deposited_count"], 1)
            self.assertEqual(second["deposited_count"], 0)
            self.assertEqual(second["actions"][0]["action"], "duplicate")
            self.assertEqual(len(list((project / "docs").rglob("*.md"))), 1)
            self.assertEqual(target.read_text(encoding="utf-8").count("Knowledge ID"), 1)

    def test_no_matching_document_creates_docs_knowledge_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            candidate = knowledge_candidate(
                "knowledge-decision-001",
                statement="Keep Root execution routing separate from subagent routing.",
                category="decision",
                target="auto",
            )
            report = deposit_knowledge(
                project,
                self.write_candidates(project, [candidate]),
                apply=True,
            )
            target = Path(raw) / report["actions"][0]["target"]
            self.assertTrue(target.is_file())
            self.assertTrue(str(target.relative_to(project)).startswith("docs/knowledge/"))

    def test_limited_candidate_is_not_written_as_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            report = deposit_knowledge(
                project,
                self.write_candidates(
                    project,
                    [knowledge_candidate("knowledge-limited-001", confidence="limited")],
                ),
                apply=True,
            )
            self.assertEqual(report["limited_candidates_skipped"], 1)
            self.assertEqual(report["deposited_count"], 0)

    def test_temporary_thread_id_and_secret_are_rejected(self) -> None:
        temporary = knowledge_candidate(
            "knowledge-temp-001",
            statement="Thread ID: 019f7a4e-f1be-7771-9f67-38fcde417f48",
        )
        secret = knowledge_candidate(
            "knowledge-secret-001",
            statement="api_key=sk-this-is-not-durable",
        )
        for candidate in (temporary, secret):
            with self.assertRaises(ValueError):
                validate_knowledge_candidates([candidate])


if __name__ == "__main__":
    unittest.main()
