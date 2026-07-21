from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, knowledge_candidate

sys.path.insert(0, str(ROOT / "scripts"))
import deposit_knowledge as deposit_module  # noqa: E402
from deposit_knowledge import (  # noqa: E402
    candidate_fragment,
    deposit_knowledge,
    plan_deposits,
    validate_knowledge_candidates,
)


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

    def test_fragment_uses_compact_id_heading_and_statement_body(self) -> None:
        candidate = knowledge_candidate(
            "testing-native-execution-proof-boundary",
            statement=(
                "A Native execution result needs mechanical identity readback and "
                "independent artifact verification."
            ),
        )
        fragment = candidate_fragment(candidate)
        self.assertTrue(fragment.startswith("## Testing Native Execution Proof Boundary\n\n"))
        self.assertIn("\nA Native execution result needs mechanical identity readback", fragment)
        self.assertNotIn("## A Native execution result", fragment)

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

    def test_chinese_statement_reuses_matching_chinese_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "docs/testing/生命周期测试.md"
            target.parent.mkdir(parents=True)
            target.write_text("# 生命周期测试规范\n", encoding="utf-8")
            candidate = knowledge_candidate(
                "knowledge-lifecycle-cn-001",
                statement="生命周期测试应先运行聚焦用例，再运行完整套件。",
                target="auto",
            )
            report = deposit_knowledge(
                project,
                self.write_candidates(project, [candidate]),
                apply=True,
            )
            self.assertEqual(report["actions"][0]["target"], "docs/testing/生命周期测试.md")
            self.assertEqual(len(list((project / "docs").rglob("*.md"))), 1)

    def test_multi_document_write_rolls_back_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            first = project / "docs/testing/first.md"
            first.parent.mkdir(parents=True)
            first.write_text("# Original\n", encoding="utf-8")
            candidates = [
                knowledge_candidate(
                    "knowledge-first-001",
                    statement="First verified testing rule.",
                    target="docs/testing/first.md",
                ),
                knowledge_candidate(
                    "knowledge-second-001",
                    statement="Second verified testing rule.",
                    target="docs/testing/second.md",
                ),
            ]
            actions = plan_deposits(project, validate_knowledge_candidates(candidates))
            real_write = deposit_module.atomic_write_text
            failed = False

            def fail_second(path: Path, content: str) -> None:
                nonlocal failed
                if path.name == "second.md" and not failed:
                    failed = True
                    raise OSError("simulated write failure")
                real_write(path, content)

            with mock.patch.object(deposit_module, "atomic_write_text", side_effect=fail_second):
                with self.assertRaisesRegex(RuntimeError, "write failed"):
                    deposit_module.apply_deposits(project, actions)
            self.assertEqual(first.read_text(encoding="utf-8"), "# Original\n")
            self.assertFalse((project / "docs/testing/second.md").exists())

    def test_report_write_failure_rolls_back_deposited_documents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            target = project / "docs/testing/unit-tests.md"
            target.parent.mkdir(parents=True)
            target.write_text("# Unit Tests\n", encoding="utf-8")
            candidates = self.write_candidates(project, [knowledge_candidate()])
            report_path = project / ".agency/archive/knowledge-report.json"
            before = target.read_text(encoding="utf-8")

            with mock.patch.object(
                deposit_module,
                "atomic_write_json",
                side_effect=OSError("report disk full"),
            ):
                with self.assertRaisesRegex(RuntimeError, "write failed"):
                    deposit_knowledge(
                        project,
                        candidates,
                        apply=True,
                        report_path=report_path,
                    )

            self.assertEqual(target.read_text(encoding="utf-8"), before)
            self.assertFalse(report_path.exists())

    def test_candidate_file_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            project = Path(raw)
            external = Path(outside) / "candidates.json"
            external.write_text(
                json.dumps([knowledge_candidate()], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            link = project / "knowledge-candidates.json"
            link.symlink_to(external)
            with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
                deposit_knowledge(project, link, apply=False)

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
