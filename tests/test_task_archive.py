from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import (
    ROOT,
    completed_task,
    knowledge_candidate,
    read_json,
    task_plan,
)

sys.path.insert(0, str(ROOT / "scripts"))
from archive_task import archive_task, closure_path_for  # noqa: E402
import archive_task as archive_task_module  # noqa: E402
from agency_task import atomic_write_json, create_task  # noqa: E402
from validate_task_archive import validate_archive_directory, validate_archive_readiness  # noqa: E402


class TaskArchiveTests(unittest.TestCase):
    def test_archive_defaults_to_completion_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            (task_dir / "closure.json").write_text(
                json.dumps(closure, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                closure_path_for(project, "task-archive-001", None),
                task_dir / "closure.json",
            )

    def test_incomplete_task_cannot_archive_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["status"] = "verifying"
            (task_dir / "task-plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_archive_readiness(project, task_dir, closure)

    def test_completed_archive_creates_manifest_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                candidates=[knowledge_candidate()],
                apply=True,
            )
            destination = Path(result["destination"])
            self.assertEqual(validate_archive_directory(destination)["status"], "valid")
            manifest = read_json(destination / "archive-manifest.json")
            self.assertEqual(manifest["final_status"], "archived")
            index = read_json(project / ".agency/task-index.json")
            self.assertNotIn("task-archive-001", index["active_task_ids"])
            self.assertIn("task-archive-001", index["archived_task_ids"])

    def test_archive_and_create_share_one_index_transaction_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            new_id = "task-archive-race-new-001"
            archive_paused = threading.Event()
            release_archive = threading.Event()
            create_finished = threading.Event()
            failures: list[BaseException] = []
            real_write_index = archive_task_module.write_index

            def pausing_archive_write(path: Path, index: dict[str, object]) -> None:
                archive_paused.set()
                if not release_archive.wait(timeout=5):
                    raise TimeoutError("archive race test release timed out")
                real_write_index(path, index)

            def run_archive() -> None:
                try:
                    archive_task(
                        project,
                        task_id="task-archive-001",
                        closure=closure,
                        apply=True,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)

            def run_create() -> None:
                try:
                    create_task(project, task_plan(task_id=new_id))
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)
                finally:
                    create_finished.set()

            with mock.patch.object(
                archive_task_module,
                "write_index",
                side_effect=pausing_archive_write,
            ):
                archive_worker = threading.Thread(
                    target=run_archive, name="task-archiver"
                )
                archive_worker.start()
                self.assertTrue(archive_paused.wait(timeout=5))
                create_worker = threading.Thread(target=run_create, name="task-creator")
                create_worker.start()
                self.assertFalse(
                    create_finished.wait(timeout=0.2),
                    "create escaped the archive's index transaction lock",
                )
                release_archive.set()
                archive_worker.join(timeout=5)
                create_worker.join(timeout=5)
                self.assertFalse(archive_worker.is_alive())
                self.assertFalse(create_worker.is_alive())

            self.assertEqual(failures, [])
            index = read_json(project / ".agency/task-index.json")
            self.assertEqual(index["tasks"]["task-archive-001"]["status"], "archived")
            self.assertEqual(index["tasks"][new_id]["status"], "plan_ready")
            self.assertIn("task-archive-001", index["archived_task_ids"])
            self.assertIn(new_id, index["active_task_ids"])

    def test_completed_archive_ignores_stale_nonterminal_status_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["status_reason"] = "Previously blocked before successful verification."
            atomic_write_json(task_dir / "task-plan.json", plan)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                apply=True,
            )
            manifest = read_json(Path(result["destination"]) / "archive-manifest.json")
            self.assertIsNone(manifest["disposition_reason"])
            self.assertEqual(validate_archive_directory(Path(result["destination"]))["status"], "valid")

    def test_cancelled_archive_accepts_explicit_reason_without_completion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, _ = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["status"] = "cancelled"
            plan["status_reason"] = "User explicitly cancelled the task."
            plan.pop("acceptance_evidence", None)
            atomic_write_json(task_dir / "task-plan.json", plan)
            index = read_json(project / ".agency/task-index.json")
            index["tasks"]["task-archive-001"]["status"] = "cancelled"
            atomic_write_json(project / ".agency/task-index.json", index)
            closure = {
                "schema_version": "1.0",
                "review": {"status": "not_required", "evidence_refs": []},
                "execution_cleanup": {
                    "status": "not_applicable",
                    "evidence_refs": [],
                    "blocker": None,
                },
                "validation_results": [],
                "artifacts": [],
            }
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                disposition="cancelled",
                apply=True,
            )
            self.assertEqual(result["status"], "archived")
            manifest = read_json(Path(result["destination"]) / "archive-manifest.json")
            self.assertEqual(manifest["archive_disposition"], "cancelled")
            self.assertEqual(manifest["final_status"], "cancelled")

    def test_cancelled_archive_preserves_real_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, _ = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["status"] = "cancelled"
            plan["status_reason"] = "User cancelled after an external dependency blocked work."
            plan["work_items"][0]["status"] = "blocked"
            plan["work_items"][0]["blockers"] = ["External API access unavailable"]
            plan.pop("acceptance_evidence", None)
            atomic_write_json(task_dir / "task-plan.json", plan)
            index = read_json(project / ".agency/task-index.json")
            index["tasks"]["task-archive-001"]["status"] = "cancelled"
            atomic_write_json(project / ".agency/task-index.json", index)
            closure = {
                "schema_version": "1.0",
                "review": {"status": "not_required", "evidence_refs": []},
                "execution_cleanup": {
                    "status": "not_applicable",
                    "evidence_refs": [],
                    "blocker": None,
                },
                "validation_results": [],
                "artifacts": [],
            }
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                disposition="cancelled",
                apply=True,
            )
            manifest = read_json(Path(result["destination"]) / "archive-manifest.json")
            self.assertEqual(
                manifest["unresolved_blockers"],
                [{"work_id": "W-01", "blockers": ["External API access unavailable"]}],
            )

    def test_manifest_status_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                apply=True,
            )
            destination = Path(result["destination"])
            manifest = read_json(destination / "archive-manifest.json")
            manifest["archive_disposition"] = "cancelled"
            manifest["source_status"] = "executing"
            manifest["final_status"] = "superseded"
            atomic_write_json(destination / "archive-manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                validate_archive_directory(destination)

    def test_artifact_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            artifact = project / "artifact.txt"
            artifact.unlink()
            external = Path(outside) / "external.txt"
            external.write_text("external\n", encoding="utf-8")
            artifact.symlink_to(external)
            with self.assertRaisesRegex(ValueError, "symlink"):
                validate_archive_readiness(project, task_dir, closure)

    def test_archive_directory_symlink_argument_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                apply=True,
            )
            alias = project / "archive-alias"
            alias.symlink_to(Path(result["destination"]), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                validate_archive_directory(alias)

    def test_deposit_preflight_failure_leaves_task_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            (project / "README.md").write_text("# Public\n", encoding="utf-8")
            candidate = knowledge_candidate(target="README.md")
            with self.assertRaisesRegex(ValueError, "restricted knowledge"):
                archive_task(
                    project,
                    task_id="task-archive-001",
                    closure=closure,
                    candidates=[candidate],
                    apply=True,
                    deposit=True,
                )
            self.assertTrue(task_dir.is_dir())
            index = read_json(project / ".agency/task-index.json")
            self.assertIn("task-archive-001", index["active_task_ids"])

    def test_archive_preparation_failure_leaves_active_task_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan_before = read_json(task_dir / "task-plan.json")
            progress_path = task_dir / "progress.jsonl"
            progress_before = (
                progress_path.read_text(encoding="utf-8")
                if progress_path.exists()
                else None
            )
            external = Path(outside) / "manifest.json"
            external.write_text("{}\n", encoding="utf-8")
            (task_dir / "archive-manifest.json").symlink_to(external)

            with self.assertRaisesRegex(ValueError, "symlink"):
                archive_task(
                    project,
                    task_id="task-archive-001",
                    closure=closure,
                    apply=True,
                )

            self.assertTrue(task_dir.is_dir())
            self.assertEqual(read_json(task_dir / "task-plan.json"), plan_before)
            self.assertEqual(
                progress_path.read_text(encoding="utf-8")
                if progress_path.exists()
                else None,
                progress_before,
            )
            self.assertFalse((task_dir / "ARCHIVE_REPORT.md").exists())
            index = read_json(project / ".agency/task-index.json")
            self.assertIn("task-archive-001", index["active_task_ids"])

    def test_archive_index_failure_restores_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan_before = read_json(task_dir / "task-plan.json")
            index_before = read_json(project / ".agency/task-index.json")
            with mock.patch.object(
                archive_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    archive_task(
                        project,
                        task_id="task-archive-001",
                        closure=closure,
                        apply=True,
                    )
            self.assertTrue(task_dir.is_dir())
            self.assertEqual(read_json(task_dir / "task-plan.json"), plan_before)
            self.assertEqual(read_json(project / ".agency/task-index.json"), index_before)
            archive_root = project / ".agency/tasks/archive"
            self.assertFalse(
                any(
                    path.name == "task-archive-001"
                    for path in archive_root.rglob("task-archive-001")
                )
            )

    def test_successful_deposit_report_is_bound_into_archive_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            result = archive_task(
                project,
                task_id="task-archive-001",
                closure=closure,
                candidates=[knowledge_candidate()],
                apply=True,
                deposit=True,
            )
            destination = Path(result["destination"])
            manifest = read_json(destination / "archive-manifest.json")
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertIn("knowledge-deposit-report.json", paths)
            self.assertEqual(validate_archive_directory(destination)["status"], "valid")
            self.assertTrue((project / "docs/testing/unit-tests.md").is_file())

    def test_knowledge_candidate_must_bind_to_current_task_and_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            wrong_task = knowledge_candidate()
            wrong_task["source_task_id"] = "task-other-001"
            with self.assertRaisesRegex(ValueError, "not bound"):
                archive_task(
                    project,
                    task_id="task-archive-001",
                    closure=closure,
                    candidates=[wrong_task],
                    apply=False,
                )
            unknown_evidence = knowledge_candidate()
            unknown_evidence["evidence_refs"] = ["unverified assertion"]
            with self.assertRaisesRegex(ValueError, "outside the closure"):
                archive_task(
                    project,
                    task_id="task-archive-001",
                    closure=closure,
                    candidates=[unknown_evidence],
                    apply=False,
                )

    def test_post_archive_deposit_failure_is_reported_and_manifested(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            _, closure = completed_task(project)
            with mock.patch("archive_task.deposit_knowledge", side_effect=OSError("disk full")):
                result = archive_task(
                    project,
                    task_id="task-archive-001",
                    closure=closure,
                    candidates=[knowledge_candidate()],
                    apply=True,
                    deposit=True,
                )
            self.assertEqual(result["status"], "archived_with_blocker")
            self.assertTrue(result["post_archive_blockers"])
            destination = Path(result["destination"])
            report = read_json(destination / "knowledge-deposit-report.json")
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(validate_archive_directory(destination)["status"], "valid")

    def test_reviewer_position_requires_handled_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project, reviewer=True)
            closure["review"] = {"status": "not_required", "evidence_refs": []}
            with self.assertRaisesRegex(ValueError, "Reviewer"):
                validate_archive_readiness(project, task_dir, closure)

    def test_high_risk_task_requires_review_without_reviewer_position(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            plan = read_json(task_dir / "task-plan.json")
            plan["work_items"][0]["risk"] = "critical"
            (task_dir / "task-plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Reviewer"):
                validate_archive_readiness(project, task_dir, closure)

    def test_native_closed_cleanup_requires_readback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            (task_dir / "execution-session.json").write_text(
                json.dumps({"native_task_id": "task-real"}) + "\n",
                encoding="utf-8",
            )
            closure["execution_cleanup"] = {
                "status": "closed",
                "evidence_refs": [],
                "blocker": None,
            }
            with self.assertRaisesRegex(ValueError, "readback evidence"):
                validate_archive_readiness(project, task_dir, closure)

    def test_closed_cleanup_rejects_stale_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_dir, closure = completed_task(project)
            closure["execution_cleanup"] = {
                "status": "closed",
                "evidence_refs": ["native task readback closed"],
                "blocker": "stale cleanup blocker",
            }
            with self.assertRaisesRegex(ValueError, "only valid for cleanup_blocked"):
                validate_archive_readiness(project, task_dir, closure)


if __name__ == "__main__":
    unittest.main()
