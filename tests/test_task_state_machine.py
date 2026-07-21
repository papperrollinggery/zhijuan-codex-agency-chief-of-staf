from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
from agency_task import (  # noqa: E402
    LEGAL_TRANSITIONS,
    PLAN_BUNDLE_FILES,
    atomic_write_json,
    create_task,
    list_active_tasks,
    load_json,
    recover_task_creations,
    transition_task,
    validate_task_plan,
    validate_transition,
)
import agency_task as agency_task_module  # noqa: E402


class TaskStateMachineTests(unittest.TestCase):
    def test_every_declared_transition_is_accepted(self) -> None:
        for before, afters in LEGAL_TRANSITIONS.items():
            for after in afters:
                validate_transition(before, after)

    def test_forbidden_shortcuts_are_rejected(self) -> None:
        for before, after in (
            ("discussion", "archived"),
            ("plan_ready", "completed"),
            ("executing", "completed"),
        ):
            with self.assertRaisesRegex(ValueError, "illegal task transition"):
                validate_transition(before, after)

    def test_generated_task_ids_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            first = task_plan()
            second = task_plan()
            first.pop("task_id")
            second.pop("task_id")
            one = create_task(project, first)["task_id"]
            two = create_task(project, second)["task_id"]
            self.assertNotEqual(one, two)

    def test_dependency_cycle_is_rejected(self) -> None:
        items = [
            work_item("W-01", dependencies=["W-02"]),
            work_item("W-02", dependencies=["W-01"]),
        ]
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            validate_task_plan(task_plan(items=items))

    def test_new_plan_rejects_precompleted_or_preproven_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            forged: list[dict[str, object]] = []

            completed = task_plan(task_id="task-forged-completed-001")
            completed["work_items"][0]["status"] = "completed"
            forged.append(completed)

            evidence = task_plan(task_id="task-forged-evidence-001")
            evidence["work_items"][0]["evidence_refs"] = ["fake PASS"]
            forged.append(evidence)

            assigned = task_plan(task_id="task-forged-profile-001")
            assigned["work_items"][0]["profile"] = "developer"
            forged.append(assigned)

            accepted = task_plan(task_id="task-forged-acceptance-001")
            accepted["acceptance_evidence"] = {
                accepted["acceptance_criteria"][0]: ["fake evidence"]
            }
            forged.append(accepted)

            resolved = task_plan(task_id="task-forged-model-001")
            resolved["execution_model_request"]["resolved_model_id"] = "gpt-5.6-sol"
            resolved["execution_model_request"]["resolution_status"] = "resolved"
            forged.append(resolved)

            for plan in forged:
                with self.subTest(task_id=plan["task_id"]):
                    with self.assertRaisesRegex(ValueError, "new (?:plan_ready task|task plan)"):
                        create_task(project, plan)
            self.assertFalse((project / ".agency").exists())

    def test_new_plan_rejects_unknown_completion_claim_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            top_level = task_plan(task_id="task-forged-unknown-top-001")
            top_level["completion_verified"] = True
            with self.assertRaisesRegex(ValueError, "unknown fields: completion_verified"):
                create_task(project, top_level)

            work_level = task_plan(task_id="task-forged-unknown-work-001")
            work_level["work_items"][0]["verification_status"] = "PASS"
            with self.assertRaisesRegex(ValueError, "unknown fields: verification_status"):
                create_task(project, work_level)

            model_readback = task_plan(task_id="task-forged-model-readback-001")
            model_readback["model_readback"] = {"model": "gpt-5.6-sol"}
            with self.assertRaisesRegex(ValueError, "unknown fields: model_readback"):
                create_task(project, model_readback)
            self.assertFalse((project / ".agency").exists())

    def test_superseded_task_is_removed_from_active_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            old_id, _ = create_fixture_task(project, "task-old-001")
            new_id, _ = create_fixture_task(project, "task-new-001")
            result = transition_task(
                project,
                old_id,
                "superseded",
                reason="Replaced by a corrected scope",
                superseded_by=new_id,
            )
            self.assertFalse(result["active"])
            self.assertNotIn(old_id, {item["task_id"] for item in list_active_tasks(project)})

    def test_public_transition_cannot_bypass_completion_or_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-guarded-001")
            transition_task(project, task_id, "execution_ready")
            transition_task(project, task_id, "executing")
            transition_task(project, task_id, "verifying")
            with self.assertRaisesRegex(ValueError, "complete_task.py"):
                transition_task(project, task_id, "completed")
            plan = validate_task_plan(load_json(task_dir / "task-plan.json"))
            self.assertEqual(plan["status"], "verifying")

    def test_agency_root_symlink_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (project / ".agency").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                create_task(project, task_plan(task_id="task-symlink-001"))
            self.assertEqual(list(outside.iterdir()), [])

    def test_create_rolls_back_directory_when_index_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            with mock.patch.object(
                agency_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    create_task(project, task_plan(task_id="task-create-failure-001"))
            self.assertFalse(
                (project / ".agency/tasks/active/task-create-failure-001").exists()
            )
            self.assertFalse((project / ".agency/task-index.json").exists())

    def test_create_rolls_back_partial_eight_file_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            real_write = agency_task_module.atomic_write_text

            def fail_team_markdown(path: Path, text: str) -> None:
                if path.name == "TEAM_PLAN.md":
                    raise OSError("simulated bundle write failure")
                real_write(path, text)

            with mock.patch.object(
                agency_task_module,
                "atomic_write_text",
                side_effect=fail_team_markdown,
            ):
                with self.assertRaisesRegex(OSError, "simulated bundle write failure"):
                    create_task(project, task_plan(task_id="task-bundle-failure-001"))
            self.assertFalse(
                (project / ".agency/tasks/active/task-bundle-failure-001").exists()
            )
            self.assertFalse((project / ".agency/task-index.json").exists())

    def test_task_directory_is_invisible_until_complete_bundle_is_published(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id = "task-atomic-publish-001"
            first_file_written = threading.Event()
            continue_writing = threading.Event()
            outcome: list[object] = []
            real_write_bundle = agency_task_module._write_plan_bundle

            def delayed_write(project_root: Path, staging: Path, plan: dict[str, object]) -> None:
                atomic_write_json(staging / "task-plan.json", plan)
                first_file_written.set()
                if not continue_writing.wait(timeout=5):
                    raise TimeoutError("test did not release staged task writer")
                real_write_bundle(project_root, staging, plan)

            def run_create() -> None:
                try:
                    outcome.append(create_task(project, task_plan(task_id=task_id)))
                except BaseException as exc:  # pragma: no cover - asserted below
                    outcome.append(exc)

            with mock.patch.object(
                agency_task_module, "_write_plan_bundle", side_effect=delayed_write
            ):
                worker = threading.Thread(target=run_create)
                worker.start()
                self.assertTrue(first_file_written.wait(timeout=5))
                published = project / ".agency" / "tasks" / "active" / task_id
                self.assertFalse(published.exists())
                continue_writing.set()
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], dict)
            self.assertEqual(
                {path.name for path in published.iterdir()}, set(PLAN_BUNDLE_FILES)
            )

    def test_interrupted_publication_journal_recovers_index_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-recover-create-001")
            index_path = project / ".agency" / "task-index.json"
            created_at = load_json(index_path)["tasks"][task_id]["created_at"]
            index_path.unlink()
            atomic_write_json(
                project / ".agency" / f".task-create-{task_id}.json",
                {
                    "schema_version": "1.0",
                    "task_id": task_id,
                    "staging_name": f".{task_id}.staging-interrupted",
                    "created_at": created_at,
                },
            )
            self.assertEqual(recover_task_creations(project), [task_id])
            recovered = load_json(index_path)
            self.assertEqual(recovered["active_task_ids"], [task_id])
            self.assertEqual(recovered["tasks"][task_id]["status"], "plan_ready")
            self.assertEqual({path.name for path in task_dir.iterdir()}, set(PLAN_BUNDLE_FILES))
            self.assertEqual(recover_task_creations(project), [])

    def test_sigkill_after_directory_publish_recovers_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            project.mkdir()
            marker = Path(raw) / "published.marker"
            child = """
import os
import time
from pathlib import Path

import agency_task
from lifecycle_test_support import task_plan

real_write_index = agency_task.write_index
marker = Path(os.environ["AGENCY_CRASH_MARKER"])

def pause_after_publish(project, index):
    marker.write_text("published\\n", encoding="utf-8")
    time.sleep(30)
    return real_write_index(project, index)

agency_task.write_index = pause_after_publish
agency_task.create_task(
    Path(os.environ["AGENCY_CRASH_PROJECT"]),
    task_plan(task_id="task-sigkill-recovery-001"),
)
"""
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(ROOT / "scripts"), str(ROOT / "tests")]
            )
            environment["AGENCY_CRASH_MARKER"] = str(marker)
            environment["AGENCY_CRASH_PROJECT"] = str(project)
            process = subprocess.Popen(
                [sys.executable, "-c", child],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "child never reached post-publish window")
                process.kill()
                process.wait(timeout=5)
            finally:
                if process.poll() is None:  # pragma: no cover - defensive cleanup
                    process.kill()
                    process.wait(timeout=5)
            task_dir = (
                project
                / ".agency"
                / "tasks"
                / "active"
                / "task-sigkill-recovery-001"
            )
            self.assertEqual({path.name for path in task_dir.iterdir()}, set(PLAN_BUNDLE_FILES))
            self.assertFalse((project / ".agency" / "task-index.json").exists())
            self.assertEqual(
                recover_task_creations(project), ["task-sigkill-recovery-001"]
            )
            index = load_json(project / ".agency" / "task-index.json")
            self.assertEqual(index["active_task_ids"], ["task-sigkill-recovery-001"])

    def test_concurrent_duplicate_task_creation_has_one_complete_winner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id = "task-concurrent-create-001"
            barrier = threading.Barrier(2)
            results: list[object] = []

            def create_same_task() -> None:
                barrier.wait(timeout=5)
                try:
                    results.append(create_task(project, task_plan(task_id=task_id)))
                except BaseException as exc:  # pragma: no cover - asserted below
                    results.append(exc)

            workers = [threading.Thread(target=create_same_task) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
            self.assertEqual(sum(isinstance(item, ValueError) for item in results), 1)
            task_dir = project / ".agency" / "tasks" / "active" / task_id
            self.assertEqual({path.name for path in task_dir.iterdir()}, set(PLAN_BUNDLE_FILES))
            index = load_json(project / ".agency" / "task-index.json")
            self.assertEqual(index["active_task_ids"], [task_id])

    def test_transition_and_create_share_one_index_transaction_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            existing_id, _ = create_fixture_task(
                project, "task-transition-race-existing-001"
            )
            new_id = "task-transition-race-new-001"
            transition_paused = threading.Event()
            release_transition = threading.Event()
            create_finished = threading.Event()
            failures: list[BaseException] = []
            real_write_index = agency_task_module.write_index

            def pausing_write_index(path: Path, index: dict[str, object]) -> None:
                if threading.current_thread().name == "transition-writer":
                    transition_paused.set()
                    if not release_transition.wait(timeout=5):
                        raise TimeoutError("transition race test release timed out")
                real_write_index(path, index)

            def run_transition() -> None:
                try:
                    transition_task(project, existing_id, "execution_ready")
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
                agency_task_module, "write_index", side_effect=pausing_write_index
            ):
                transition_worker = threading.Thread(
                    target=run_transition, name="transition-writer"
                )
                transition_worker.start()
                self.assertTrue(transition_paused.wait(timeout=5))
                create_worker = threading.Thread(target=run_create, name="task-creator")
                create_worker.start()
                self.assertFalse(
                    create_finished.wait(timeout=0.2),
                    "create escaped the transition's index transaction lock",
                )
                release_transition.set()
                transition_worker.join(timeout=5)
                create_worker.join(timeout=5)
                self.assertFalse(transition_worker.is_alive())
                self.assertFalse(create_worker.is_alive())

            self.assertEqual(failures, [])
            index = load_json(project / ".agency/task-index.json")
            self.assertEqual(index["tasks"][existing_id]["status"], "execution_ready")
            self.assertEqual(index["tasks"][new_id]["status"], "plan_ready")
            self.assertEqual(set(index["active_task_ids"]), {existing_id, new_id})

    def test_transition_rolls_back_plan_and_checklist_when_index_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-transition-failure-001")
            checklist_before = (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(
                encoding="utf-8"
            )
            with mock.patch.object(
                agency_task_module, "write_index", side_effect=OSError("index full")
            ):
                with self.assertRaisesRegex(OSError, "index full"):
                    transition_task(project, task_id, "execution_ready")
            self.assertEqual(load_json(task_dir / "task-plan.json")["status"], "plan_ready")
            self.assertEqual(
                (task_dir / "TASK_EXECUTION_CHECKLIST.md").read_text(encoding="utf-8"),
                checklist_before,
            )
            index = load_json(project / ".agency/task-index.json")
            self.assertEqual(index["tasks"][task_id]["status"], "plan_ready")


if __name__ == "__main__":
    unittest.main()
