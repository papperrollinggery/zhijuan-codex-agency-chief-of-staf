from __future__ import annotations

import tempfile
import unittest
import json
import copy
import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_test_support import ROOT, create_fixture_task, live_catalog, read_json, task_plan, work_item

sys.path.insert(0, str(ROOT / "scripts"))
import bind_execution_session as bind_execution_session_module  # noqa: E402
import prepare_execution_launch as prepare_execution_launch_module  # noqa: E402
from bind_execution_session import (  # noqa: E402
    MECHANICAL_ATTESTATION,
    bind_execution_session,
    validate_bound_execution_session,
)
from agency_task import atomic_write_json, create_task, utc_now  # noqa: E402
from prepare_execution_launch import (  # noqa: E402
    MAX_EXECUTION_THREAD_TITLE_LENGTH,
    execution_packet,
    execution_thread_title,
    prepare_execution_launch,
)
from prepare_team_runtime import prepare_team_runtime  # noqa: E402
from protocol_contract import (  # noqa: E402
    match_execution_session_transport,
    parse_execution_session_packet,
)
from update_task_progress import update_progress  # noqa: E402

try:
    import jsonschema
except ImportError:  # pragma: no cover - package gate has a structural fallback
    jsonschema = None


NATIVE_TASK_ID = "019f7a4e-f1be-7771-9f67-38fcde417f48"


def trusted_readback(project: Path, task_id: str) -> dict[str, object]:
    request = read_json(project / f".agency/tasks/active/{task_id}/task-plan.json")["execution_model_request"]
    return {
        "native_task_id": NATIVE_TASK_ID,
        "provider": "openai",
        "actual_model_id": request["resolved_model_id"] or "gpt-6-astra",
        "actual_reasoning_effort": request["reasoning_request"],
        "cwd": str(project.resolve()),
        "isolated_worktree": False,
        "worktree_path": None,
        "status": "active-unarchived",
        "host_thread_readback": True,
        "prompt_bound": True,
        "prompt_transport": "raw",
        "source_thread_id": None,
        "source_thread_readback": False,
        "source_user_root_readback": False,
        "catalog_bound": True,
        "state_store_identity": {
            "device": 1,
            "inode": 2,
            "identity_guarded": True,
            "wal_aware": True,
            "readonly_transaction": True,
        },
        "state_source": "appServer",
        "prompt_sha256": hashlib.sha256(
            execution_packet(project.resolve(), task_id, request).encode("utf-8")
        ).hexdigest(),
        "rollout_sha256": "a" * 64,
        "model_turns_observed": 1,
        "observed_at": utc_now(),
    }


def launch_managed_snapshot(project: Path, task_dir: Path) -> dict[str, bytes | None]:
    root = project.resolve()
    paths = (
        task_dir / "task-plan.json",
        task_dir / "TASK_EXECUTION_CHECKLIST.md",
        task_dir / "TEAM_PLAN.json",
        task_dir / "TEAM_PLAN.md",
        task_dir / "EXECUTION_LAUNCH_PROMPT.md",
        task_dir / "execution-session.json",
        task_dir / "progress.jsonl",
        task_dir / "PROGRESS.md",
        project / ".agency/task-index.json",
    )
    return {
        str(path.resolve(strict=False).relative_to(root)): (
            path.read_bytes() if path.exists() else None
        )
        for path in paths
    }


class ExecutionSessionTests(unittest.TestCase):
    def test_explicit_choices_round_trip_plan_packet_session_and_binding(self) -> None:
        for model_id, display, effort in (
            ("gpt-6-astra", "GPT-6 Astra", "high"),
            ("gpt-5.6-terra", "GPT-5.6 Terra", "medium"),
            ("gpt-5.6-sol", "GPT-5.6 Sol", "ultra"),
            ("gpt-5.6-luna", "gpt-5.6-luna", "low"),
        ):
            with self.subTest(model=model_id), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                plan = task_plan(items=[work_item("W-01", work_type="research")])
                request = plan["execution_model_request"]
                request.update(display_request=display, reasoning_request=effort)
                created = create_task(project, plan)
                task_id, task_dir = created["task_id"], Path(created["task_dir"])
                initial_prompt = (task_dir / "EXECUTION_LAUNCH_PROMPT.md").read_text()
                self.assertIn(display, initial_prompt)
                self.assertIn(effort, initial_prompt)
                catalog = live_catalog()
                catalog["models"] = [{"id": model_id, "display_name": display, "provider": "openai", "supported_reasoning": [effort]}]
                result = prepare_execution_launch(project, task_id=task_id, catalog=catalog, catalog_mechanically_verified=True)
                self.assertEqual(result["status"], "manual_launch_ready")
                parsed = parse_execution_session_packet((task_dir / "EXECUTION_LAUNCH_PROMPT.md").read_text().rstrip("\n"))
                self.assertEqual((parsed["执行模型请求"], parsed["推理强度请求"]), (display, effort))
                with mock.patch.object(bind_execution_session_module, "_mechanical_readback", return_value=trusted_readback(project, task_id)):
                    bind_execution_session(project, task_id=task_id, native_task_id=NATIVE_TASK_ID, apply=True)
                session = read_json(task_dir / "execution-session.json")
                bound_plan = read_json(task_dir / "task-plan.json")
                validate_bound_execution_session(session, bound_plan, project)
                self.assertEqual(session["native_readback"]["actual_model_id"], model_id)
                self.assertEqual(session["reasoning_request"], effort)
                if jsonschema:
                    jsonschema.validate(bound_plan, read_json(ROOT / "assets/task-execution-plan.schema.json"))
                    jsonschema.validate(session, read_json(ROOT / "assets/execution-session.schema.json"))
                for key, value in (("display_request", "Another Model"), ("reasoning_request", "xhigh")):
                    mutated = copy.deepcopy(bound_plan)
                    mutated["execution_model_request"][key] = value
                    with self.assertRaisesRegex(ValueError, "inconsistent"):
                        validate_bound_execution_session(session, mutated, project)

    def test_changed_request_cannot_bind_stale_ready_session(self) -> None:
        for key, value in (("display_request", "GPT-5.6 Sol"), ("reasoning_request", "high"), ("resolved_model_id", "another-model")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as raw:
                project = Path(raw).resolve()
                task_id, task_dir = create_fixture_task(project, items=[work_item("W-01", work_type="research")])
                prepare_execution_launch(project, task_id=task_id, catalog=live_catalog(), catalog_mechanically_verified=True)
                plan = read_json(task_dir / "task-plan.json")
                plan["execution_model_request"][key] = value
                atomic_write_json(task_dir / "task-plan.json", plan)
                before = launch_managed_snapshot(project, task_dir)
                with mock.patch.object(bind_execution_session_module, "_mechanical_readback") as reader:
                    with self.assertRaisesRegex(ValueError, "no longer matches"):
                        bind_execution_session(project, task_id=task_id, native_task_id=NATIVE_TASK_ID, apply=True)
                reader.assert_not_called()
                self.assertEqual(before, launch_managed_snapshot(project, task_dir))

    def test_execution_packet_is_distinct_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            packet = execution_packet(project, "task-session-001")
            parsed = parse_execution_session_packet(packet.rstrip("\n"))
            self.assertEqual(
                packet.splitlines()[:2],
                [
                    "AGENCY_EXECUTION_SESSION: true",
                    "执行 Skill：$agency-chief-of-staff",
                ],
            )
            self.assertEqual(parsed["执行模型请求"], "GPT-6 Astra")
            self.assertEqual(parsed["推理强度请求"], "max")
            self.assertEqual(parsed["编排深度"], "0")
            self.assertEqual(parsed["执行 Skill"], "$agency-chief-of-staff")
            self.assertNotIn("AGENCY_WORKER: true", packet)
            with self.assertRaisesRegex(ValueError, "explicitly invoke"):
                parse_execution_session_packet(
                    packet.replace(
                        "$agency-chief-of-staff",
                        "$zhijuan-codex-agency-chief-of-staf",
                        1,
                    ).rstrip("\n")
                )
            with self.assertRaises(ValueError):
                parse_execution_session_packet("\n" + packet.rstrip("\n"))

    def test_pre_canonical_skill_raw_packet_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            packet = execution_packet(Path(raw), "task-session-old-raw-001")
            old_packet = packet.replace(
                "执行 Skill：$agency-chief-of-staff\n", "", 1
            )

            with self.assertRaises(ValueError):
                parse_execution_session_packet(old_packet.rstrip("\n"))
            self.assertIsNone(
                match_execution_session_transport(old_packet, packet)
            )

    def test_pre_canonical_skill_envelope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            packet = execution_packet(Path(raw), "task-session-old-envelope-001")
            old_packet = packet.replace(
                "执行 Skill：$agency-chief-of-staff\n", "", 1
            )
            source = "019f7a4e-f1be-7771-9f67-38fcde417f49"
            old_envelope = (
                "<codex_delegation>\n"
                f"  <source_thread_id>{source}</source_thread_id>\n"
                f"  <input>{old_packet}</input>\n"
                "</codex_delegation>"
            )

            self.assertIsNone(
                match_execution_session_transport(old_envelope, packet)
            )

    def test_execution_prompt_match_accepts_exact_codex_delegation_transport(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            packet = execution_packet(Path(raw), "task-session-001")
            source = "019f7a4e-f1be-7771-9f67-38fcde417f49"
            envelope = (
                "<codex_delegation>\n"
                f"  <source_thread_id>{source}</source_thread_id>\n"
                f"  <input>{packet}</input>\n"
                "</codex_delegation>"
            )
            self.assertEqual(
                match_execution_session_transport(envelope, packet),
                {
                    "prompt_transport": "codex_delegation",
                    "source_thread_id": source,
                },
            )

    def test_unavailable_native_surface_generates_manual_launch_without_claiming_thread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-manual-001")
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": False},
                catalog_mechanically_verified=True,
            )
            self.assertEqual(result["status"], "manual_launch_ready")
            self.assertEqual(result["lifecycle_status"], "execution_ready")
            self.assertFalse(result["new_conversation_created"])
            session = read_json(task_dir / "execution-session.json")
            self.assertEqual(result["requested_thread_title"], "Agency · Lifecycle test task")
            self.assertEqual(session["requested_thread_title"], result["requested_thread_title"])
            self.assertIsNone(session["native_task_id"])
            self.assertEqual(
                session["orchestration_depth"], 0
            )
            self.assertIn(
                "Execution session prepared",
                (task_dir / "progress.jsonl").read_text(encoding="utf-8"),
            )
            self.assertIn("execution_ready", (task_dir / "PROGRESS.md").read_text(encoding="utf-8"))

    def test_required_native_surface_fails_closed_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(project, "task-native-required-001")
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": False},
                require_native=True,
                catalog_mechanically_verified=True,
            )
            session = read_json(task_dir / "execution-session.json")
            self.assertEqual(result["status"], "TOOL_BLOCKED")
            self.assertEqual(result["lifecycle_status"], "plan_ready")
            self.assertFalse(result["new_conversation_created"])
            self.assertEqual(session["session_status"], "TOOL_BLOCKED")
            self.assertIsNone(session["native_task_id"])
            self.assertIsNone(session["native_readback"])
            self.assertEqual(
                session["requested_thread_title"], "Agency · Lifecycle test task"
            )

    def test_execution_thread_title_is_deterministic_compact_and_single_line(self) -> None:
        title = execution_thread_title(
            {
                "title": "  Cross-module\n migration   with a deliberately long descriptive title "
                * 3
            }
        )
        self.assertTrue(title.startswith("Agency · Cross-module migration"))
        self.assertNotIn("\n", title)
        self.assertNotIn("  ", title)
        self.assertLessEqual(len(title), MAX_EXECUTION_THREAD_TITLE_LENGTH)

    def test_reprepare_execution_ready_replaces_pre_canonical_skill_packet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project, "task-reprepare-old-packet-001"
            )
            kwargs = {
                "task_id": task_id,
                "catalog": live_catalog(),
                "native_capabilities": {"task_thread_create": False},
                "catalog_mechanically_verified": True,
            }
            first = prepare_execution_launch(project, **kwargs)
            self.assertEqual(first["lifecycle_status"], "execution_ready")
            launch_path = task_dir / "EXECUTION_LAUNCH_PROMPT.md"
            old_packet = launch_path.read_text(encoding="utf-8").replace(
                "执行 Skill：$agency-chief-of-staff\n", "", 1
            )
            launch_path.write_text(old_packet, encoding="utf-8")

            second = prepare_execution_launch(project, **kwargs)

            self.assertEqual(second["status"], "manual_launch_ready")
            self.assertEqual(second["lifecycle_status"], "execution_ready")
            regenerated = launch_path.read_text(encoding="utf-8")
            self.assertEqual(
                regenerated.splitlines()[:2],
                [
                    "AGENCY_EXECUTION_SESSION: true",
                    "执行 Skill：$agency-chief-of-staff",
                ],
            )
            parse_execution_session_packet(regenerated.rstrip("\n"))

    def test_launch_and_progress_share_the_task_state_transaction_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(
                project, "task-launch-progress-race-001"
            )
            launch_paused = threading.Event()
            release_launch = threading.Event()
            progress_finished = threading.Event()
            failures: list[BaseException] = []
            real_atomic_write_json = prepare_execution_launch_module.atomic_write_json

            def pausing_plan_write(path: Path, value: object) -> None:
                if (
                    threading.current_thread().name == "launch-writer"
                    and Path(path).name == "task-plan.json"
                    and not launch_paused.is_set()
                ):
                    launch_paused.set()
                    if not release_launch.wait(timeout=5):
                        raise TimeoutError("launch race test release timed out")
                real_atomic_write_json(path, value)

            def run_launch() -> None:
                try:
                    prepare_execution_launch(
                        project,
                        task_id=task_id,
                        catalog=live_catalog(),
                        native_capabilities={"task_thread_create": False},
                        catalog_mechanically_verified=True,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)

            def run_progress() -> None:
                try:
                    update_progress(
                        project,
                        task_id=task_id,
                        event_type="work_started",
                        work_id="W-01",
                        actor="execution-root",
                        summary="Implementation started after launch handoff",
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)
                finally:
                    progress_finished.set()

            with mock.patch.object(
                prepare_execution_launch_module,
                "atomic_write_json",
                side_effect=pausing_plan_write,
            ):
                launch_worker = threading.Thread(
                    target=run_launch, name="launch-writer"
                )
                launch_worker.start()
                self.assertTrue(launch_paused.wait(timeout=5))
                progress_worker = threading.Thread(
                    target=run_progress, name="progress-writer"
                )
                progress_worker.start()
                self.assertFalse(
                    progress_finished.wait(timeout=0.2),
                    "progress escaped the launch task-state transaction lock",
                )
                release_launch.set()
                launch_worker.join(timeout=5)
                progress_worker.join(timeout=5)
                self.assertFalse(launch_worker.is_alive())
                self.assertFalse(progress_worker.is_alive())

            self.assertEqual(failures, [])
            plan = read_json(task_dir / "task-plan.json")
            self.assertEqual(plan["status"], "execution_ready")
            self.assertEqual(plan["work_items"][0]["status"], "in_progress")
            progress_text = (task_dir / "progress.jsonl").read_text(encoding="utf-8")
            self.assertIn("Implementation started after launch handoff", progress_text)

    def test_launch_session_write_failure_restores_every_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(
                project, "task-launch-session-failure-001"
            )
            before = launch_managed_snapshot(project, task_dir)
            real_atomic_write_json = prepare_execution_launch_module.atomic_write_json

            def fail_session(path: Path, value: object) -> None:
                if Path(path).name == "execution-session.json":
                    raise OSError("session write failed")
                real_atomic_write_json(path, value)

            with mock.patch.object(
                prepare_execution_launch_module,
                "atomic_write_json",
                side_effect=fail_session,
            ):
                with self.assertRaisesRegex(OSError, "session write failed"):
                    prepare_execution_launch(
                        project,
                        task_id=task_id,
                        catalog=live_catalog(),
                        native_capabilities={"task_thread_create": False},
                        catalog_mechanically_verified=True,
                    )
            self.assertEqual(launch_managed_snapshot(project, task_dir), before)

    def test_launch_transition_failure_restores_every_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(
                project, "task-launch-transition-failure-001"
            )
            before = launch_managed_snapshot(project, task_dir)
            with mock.patch.object(
                prepare_execution_launch_module,
                "transition_task",
                side_effect=OSError("launch transition failed"),
            ):
                with self.assertRaisesRegex(OSError, "launch transition failed"):
                    prepare_execution_launch(
                        project,
                        task_id=task_id,
                        catalog=live_catalog(),
                        native_capabilities={"task_thread_create": False},
                        catalog_mechanically_verified=True,
                    )
            self.assertEqual(launch_managed_snapshot(project, task_dir), before)

    def test_launch_progress_failure_restores_every_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, task_dir = create_fixture_task(
                project, "task-launch-progress-failure-001"
            )
            before = launch_managed_snapshot(project, task_dir)
            with mock.patch.object(
                prepare_execution_launch_module,
                "update_progress",
                side_effect=OSError("launch progress failed"),
            ):
                with self.assertRaisesRegex(OSError, "launch progress failed"):
                    prepare_execution_launch(
                        project,
                        task_id=task_id,
                        catalog=live_catalog(),
                        native_capabilities={"task_thread_create": False},
                        catalog_mechanically_verified=True,
                    )
            self.assertEqual(launch_managed_snapshot(project, task_dir), before)

    def test_relaunch_and_native_bind_share_the_task_state_transaction_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-launch-bind-race-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            launch_paused = threading.Event()
            release_launch = threading.Event()
            bind_finished = threading.Event()
            failures: list[BaseException] = []
            real_atomic_write_json = prepare_execution_launch_module.atomic_write_json

            def pausing_plan_write(path: Path, value: object) -> None:
                if (
                    threading.current_thread().name == "relaunch-writer"
                    and Path(path).name == "task-plan.json"
                    and not launch_paused.is_set()
                ):
                    launch_paused.set()
                    if not release_launch.wait(timeout=5):
                        raise TimeoutError("relaunch race test release timed out")
                real_atomic_write_json(path, value)

            def run_relaunch() -> None:
                try:
                    prepare_execution_launch(
                        project,
                        task_id=task_id,
                        catalog=live_catalog(),
                        native_capabilities={"task_thread_create": True},
                        catalog_mechanically_verified=True,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)

            def run_bind() -> None:
                try:
                    bind_execution_session(
                        project,
                        task_id=task_id,
                        native_task_id=NATIVE_TASK_ID,
                        apply=True,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    failures.append(exc)
                finally:
                    bind_finished.set()

            with mock.patch.object(
                prepare_execution_launch_module,
                "atomic_write_json",
                side_effect=pausing_plan_write,
            ), mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=trusted_readback(project, task_id),
            ):
                launch_worker = threading.Thread(
                    target=run_relaunch, name="relaunch-writer"
                )
                launch_worker.start()
                self.assertTrue(launch_paused.wait(timeout=5))
                bind_worker = threading.Thread(target=run_bind, name="native-binder")
                bind_worker.start()
                self.assertFalse(
                    bind_finished.wait(timeout=0.2),
                    "Native bind escaped the launch task-state transaction lock",
                )
                release_launch.set()
                launch_worker.join(timeout=5)
                bind_worker.join(timeout=5)
                self.assertFalse(launch_worker.is_alive())
                self.assertFalse(bind_worker.is_alive())

            self.assertEqual(failures, [])
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "executing")
            session = read_json(task_dir / "execution-session.json")
            self.assertEqual(session["native_task_id"], NATIVE_TASK_ID)
            self.assertEqual(session["native_readback_attestation"], MECHANICAL_ATTESTATION)

    def test_native_write_launch_requires_verified_isolated_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            project = base / "project"
            worktree = base / "worktree"
            project.mkdir()
            worktree.mkdir()
            task_id, _ = create_fixture_task(project, "task-native-001")
            readback = {
                "native_task_id": "019f7a4e-f1be-7771-9f67-38fcde417f48",
                "provider": "openai",
                "actual_model_id": "gpt-6-astra",
                "actual_reasoning_effort": "max",
                "cwd": str(worktree),
                "worktree_path": str(worktree),
                "isolated_worktree": True,
                "status": "running",
            }
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={
                    "task_thread_create": True,
                    "isolated_worktree": True,
                },
                native_readback=readback,
                catalog_mechanically_verified=True,
            )
            self.assertEqual(result["status"], "native_launch_ready")
            self.assertEqual(result["lifecycle_status"], "execution_ready")
            self.assertFalse(result["new_conversation_created"])
            consistency = result["native_readback_consistency"]
            self.assertEqual(consistency["status"], "fields_consistent_unverified")
            self.assertTrue(consistency["worktree_fields_consistent"])
            self.assertNotIn("verified", consistency)
            session = read_json(
                project / ".agency/tasks/active/task-native-001/execution-session.json"
            )
            self.assertIsNone(session["native_task_id"])
            self.assertIsNone(session["native_readback"])
            self.assertIsNone(session["native_readback_attestation"])

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_schema_rejects_caller_attestation_and_semantics_reject_forgery(self) -> None:
        schema = json.loads(
            (ROOT / "assets/execution-session.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-session-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            plan = read_json(task_dir / "task-plan.json")
            plan["execution_model_request"]["resolved_model_id"] = "gpt-6-astra"
            plan["execution_model_request"]["resolution_status"] = "resolved"
            plan["status"] = "executing"
            forged = {
                "schema_version": "1.0",
                "task_id": task_id,
                "orchestration_depth": 0,
                "project_root": str(project),
                "task_plan": f".agency/tasks/active/{task_id}/task-plan.json",
                "team_plan": f".agency/tasks/active/{task_id}/TEAM_PLAN.json",
                "progress_file": f".agency/tasks/active/{task_id}/PROGRESS.md",
                "display_model_request": "GPT-6 Astra",
                "reasoning_request": "max",
                "resolved_model_id": "gpt-6-astra",
                "model_resolution_status": "resolved",
                "launch_policy": "prefer_native",
                "session_status": "executing",
                "native_task_id": NATIVE_TASK_ID,
                "native_readback": trusted_readback(project, task_id),
                "native_readback_attestation": "caller-supplied-unverified",
                "created_at": "2026-07-19T00:00:00Z",
                "bound_at": None,
            }
            forged["bound_at"] = forged["native_readback"]["observed_at"]
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.Draft202012Validator(schema).validate(forged)

            forged["native_readback_attestation"] = MECHANICAL_ATTESTATION
            jsonschema.Draft202012Validator(schema).validate(forged)
            validate_bound_execution_session(forged, plan, project)

            partial_transport = copy.deepcopy(forged)
            partial_transport["native_readback"].pop("source_thread_id")
            jsonschema.Draft202012Validator(schema).validate(partial_transport)
            with self.assertRaisesRegex(ValueError, "transport_fields"):
                validate_bound_execution_session(partial_transport, plan, project)

            mutations = {
                "nested task": ("native_readback", "native_task_id", "029f7a4e-f1be-7771-9f67-38fcde417f48"),
                "model": ("native_readback", "actual_model_id", "different-model"),
                "effort": ("native_readback", "actual_reasoning_effort", "xhigh"),
                "provider": ("native_readback", "provider", "external"),
                "cwd": ("native_readback", "cwd", "/tmp/other-project"),
                "self source": (
                    "native_readback",
                    "source_thread_id",
                    NATIVE_TASK_ID,
                ),
            }
            for label, (container, field, value) in mutations.items():
                inconsistent = copy.deepcopy(forged)
                inconsistent[container][field] = value
                if label == "self source":
                    inconsistent[container]["prompt_transport"] = "codex_delegation"
                    inconsistent[container]["source_thread_readback"] = True
                    inconsistent[container]["source_user_root_readback"] = True
                with self.subTest(label=label):
                    with self.assertRaisesRegex(ValueError, "inconsistent"):
                        validate_bound_execution_session(inconsistent, plan, project)

    def test_binding_uses_internal_mechanical_readback_and_enters_executing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-bind-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            observation = trusted_readback(project, task_id)
            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=observation,
            ) as mechanical:
                result = bind_execution_session(
                    project,
                    task_id=task_id,
                    native_task_id=NATIVE_TASK_ID,
                    apply=True,
                )
            self.assertEqual(mechanical.call_count, 1)
            self.assertEqual(result["status"], "bound")
            self.assertTrue(result["new_conversation_created"])
            self.assertEqual(read_json(task_dir / "task-plan.json")["status"], "executing")
            session = read_json(task_dir / "execution-session.json")
            self.assertEqual(session["native_task_id"], NATIVE_TASK_ID)
            self.assertEqual(session["native_readback"], observation)
            self.assertEqual(session["native_readback_attestation"], MECHANICAL_ATTESTATION)
            self.assertIn("mechanically read back", (task_dir / "progress.jsonl").read_text())

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_bound_current_packet_missing_transport_readback_is_backfilled(self) -> None:
        schema = json.loads(
            (ROOT / "assets/execution-session.schema.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-bind-legacy-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            observation = trusted_readback(project, task_id)
            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=observation,
            ):
                bind_execution_session(
                    project,
                    task_id=task_id,
                    native_task_id=NATIVE_TASK_ID,
                    apply=True,
                )
            session_path = task_dir / "execution-session.json"
            legacy_session = read_json(session_path)
            # This emulates only an already-bound current packet whose stored
            # readback predates transport fields. It is not an old launch prompt.
            for field in bind_execution_session_module.TRANSPORT_READBACK_FIELDS:
                legacy_session["native_readback"].pop(field)
            atomic_write_json(session_path, legacy_session)
            plan = read_json(task_dir / "task-plan.json")
            jsonschema.Draft202012Validator(schema).validate(legacy_session)
            validate_bound_execution_session(legacy_session, plan, project)

            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=observation,
            ):
                dry_run = bind_execution_session(
                    project,
                    task_id=task_id,
                    native_task_id=NATIVE_TASK_ID,
                    apply=False,
                )
                self.assertEqual(
                    dry_run["status"], "would-backfill-legacy-transport-readback"
                )
                self.assertNotIn(
                    "prompt_transport", read_json(session_path)["native_readback"]
                )
                applied = bind_execution_session(
                    project,
                    task_id=task_id,
                    native_task_id=NATIVE_TASK_ID,
                    apply=True,
                )
            self.assertEqual(applied["status"], "backfilled-legacy-transport-readback")
            stored = read_json(session_path)
            self.assertEqual(stored["native_readback"]["prompt_transport"], "raw")
            self.assertFalse(stored["native_readback"]["source_user_root_readback"])
            jsonschema.Draft202012Validator(schema).validate(stored)
            validate_bound_execution_session(stored, plan, project)

    def test_binding_transition_failure_restores_session_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-bind-rollback-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={"task_thread_create": True},
                catalog_mechanically_verified=True,
            )
            session_before = (task_dir / "execution-session.json").read_text()
            plan_before = (task_dir / "task-plan.json").read_text()
            with mock.patch.object(
                bind_execution_session_module,
                "_mechanical_readback",
                return_value=trusted_readback(project, task_id),
            ), mock.patch.object(
                bind_execution_session_module,
                "transition_task",
                side_effect=OSError("transition failed"),
            ):
                with self.assertRaisesRegex(OSError, "transition failed"):
                    bind_execution_session(
                        project,
                        task_id=task_id,
                        native_task_id=NATIVE_TASK_ID,
                        apply=True,
                    )
            self.assertEqual((task_dir / "execution-session.json").read_text(), session_before)
            self.assertEqual((task_dir / "task-plan.json").read_text(), plan_before)

    def test_mechanical_reader_joins_host_state_catalog_packet_and_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            task_id, task_dir = create_fixture_task(
                project,
                "task-mechanical-001",
                items=[work_item("W-01", work_type="research", read_scope=["src/"])],
            )
            plan = read_json(task_dir / "task-plan.json")
            plan["execution_model_request"]["resolved_model_id"] = "gpt-6-astra"
            plan["execution_model_request"]["resolution_status"] = "resolved"
            packet = execution_packet(project, task_id)
            source_thread_id = "019f7a4e-f1be-7771-9f67-38fcde417f49"
            transported_packet = (
                "<codex_delegation>\n"
                f"  <source_thread_id>{source_thread_id}</source_thread_id>\n"
                f"  <input>{packet}</input>\n"
                "</codex_delegation>"
            )
            rollout = project / "rollout.jsonl"
            rollout.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": NATIVE_TASK_ID,
                                    "model_provider": "openai",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {
                                    "turn_id": "turn-1",
                                    "model": "gpt-6-astra",
                                    "effort": "max",
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            database = sqlite3.connect(":memory:")
            database.execute(
                """
                CREATE TABLE threads (
                    id TEXT, rollout_path TEXT, source TEXT, model_provider TEXT,
                    model TEXT, reasoning_effort TEXT, cwd TEXT, archived INTEGER,
                    first_user_message TEXT, agent_role TEXT, created_at_ms INTEGER,
                    thread_source TEXT
                )
                """
            )
            database.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    NATIVE_TASK_ID,
                    str(rollout),
                    "appServer",
                    "openai",
                    "gpt-6-astra",
                    "max",
                    str(project),
                    0,
                    transported_packet,
                    None,
                    1_784_592_001_000,
                    "subagent",
                ),
            )
            source_row_values = (
                source_thread_id,
                str(rollout),
                "appServer",
                "openai",
                "gpt-6-astra",
                "max",
                str(project),
                0,
                "source task",
                None,
                1_784_592_000_000,
                "user",
            )
            database.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                source_row_values,
            )
            database.commit()

            class FakeApp:
                codex_home = project
                source_available = True
                omit_source_parent = False

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def request(self, method, params):
                    self.assert_request(method, params)
                    if params["threadId"] == source_thread_id and not self.source_available:
                        return {"thread": None}
                    thread = {
                        "id": params["threadId"],
                        "parentThreadId": None,
                        "preview": (
                            transported_packet
                            if params["threadId"] == NATIVE_TASK_ID
                            else "source task"
                        ),
                    }
                    if params["threadId"] == source_thread_id and self.omit_source_parent:
                        thread.pop("parentThreadId")
                    return {"thread": thread}

                @staticmethod
                def assert_request(method, params):
                    if method != "thread/read" or params.get("threadId") not in {
                        NATIVE_TASK_ID,
                        source_thread_id,
                    }:
                        raise AssertionError("unexpected App Server request")

            @contextmanager
            def state_connection(*_args, **_kwargs):
                yield database, {
                    "device": 1,
                    "inode": 2,
                    "identity_guarded": True,
                    "wal_aware": True,
                    "readonly_transaction": True,
                }

            session = {
                "created_at": "2026-07-21T00:00:00Z",
                "resolved_model_id": "gpt-6-astra",
                "reasoning_request": "max",
            }
            model = {
                "model": "gpt-6-astra",
                "modelProvider": "openai",
                "available": True,
                "supportedReasoningEfforts": [{"reasoningEffort": "max"}],
            }
            fake_app = FakeApp()
            with mock.patch.object(
                bind_execution_session_module, "resolve_executable", return_value=Path("/bin/true")
            ), mock.patch.object(
                bind_execution_session_module, "CodexAppServer", return_value=fake_app
            ), mock.patch.object(
                bind_execution_session_module, "collect_model_items", return_value=[model]
            ), mock.patch.object(
                bind_execution_session_module,
                "canonical_state_connection",
                side_effect=state_connection,
            ):
                observed = bind_execution_session_module._mechanical_readback(
                    project,
                    plan,
                    session,
                    NATIVE_TASK_ID,
                    codex_bin="codex",
                    codex_home=None,
                    state_db=None,
                    timeout_seconds=20,
                )
                database.execute(
                    "UPDATE threads SET first_user_message = ? WHERE id = ?",
                    (
                        "Maintain the protocol documentation only.\n\n"
                        "Example:\nAGENCY_EXECUTION_SESSION: true\n"
                        "执行 Skill：$agency-chief-of-staff",
                        source_thread_id,
                    ),
                )
                database.commit()
                mentioned_protocol = bind_execution_session_module._mechanical_readback(
                    project,
                    plan,
                    session,
                    NATIVE_TASK_ID,
                    codex_bin="codex",
                    codex_home=None,
                    state_db=None,
                    timeout_seconds=20,
                )
                database.execute("DELETE FROM threads WHERE id = ?", (source_thread_id,))
                database.commit()
                with self.assertRaisesRegex(ValueError, "absent from canonical"):
                    bind_execution_session_module._mechanical_readback(
                        project,
                        plan,
                        session,
                        NATIVE_TASK_ID,
                        codex_bin="codex",
                        codex_home=None,
                        state_db=None,
                        timeout_seconds=20,
                    )
                database.execute(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    source_row_values,
                )
                database.commit()
                database.execute(
                    "UPDATE threads SET thread_source = 'subagent' WHERE id = ?",
                    (source_thread_id,),
                )
                database.commit()
                with self.assertRaisesRegex(ValueError, "not a canonical user root"):
                    bind_execution_session_module._mechanical_readback(
                        project,
                        plan,
                        session,
                        NATIVE_TASK_ID,
                        codex_bin="codex",
                        codex_home=None,
                        state_db=None,
                        timeout_seconds=20,
                    )
                database.execute(
                    "UPDATE threads SET thread_source = 'user' WHERE id = ?",
                    (source_thread_id,),
                )
                database.commit()
                worker_packet = "\n".join(
                    (
                        "AGENCY_WORKER: true",
                        "委派目标：读取 README",
                        "读取范围：README.md",
                        "写入范围：无",
                        "期望产物：WORKER_RESULT，均填实际读回值",
                        "验证要求：读取当前 README 并回传",
                        "停止条件：返回唯一终态；不启动、不派发。",
                    )
                )
                database.execute(
                    "UPDATE threads SET first_user_message = ? WHERE id = ?",
                    (worker_packet, source_thread_id),
                )
                database.commit()
                with self.assertRaisesRegex(ValueError, "reserved protocol session"):
                    bind_execution_session_module._mechanical_readback(
                        project,
                        plan,
                        session,
                        NATIVE_TASK_ID,
                        codex_bin="codex",
                        codex_home=None,
                        state_db=None,
                        timeout_seconds=20,
                    )
                database.execute(
                    "UPDATE threads SET first_user_message = 'source task' WHERE id = ?",
                    (source_thread_id,),
                )
                database.commit()
                fake_app.omit_source_parent = True
                with self.assertRaisesRegex(ValueError, "not a user-owned root"):
                    bind_execution_session_module._mechanical_readback(
                        project,
                        plan,
                        session,
                        NATIVE_TASK_ID,
                        codex_bin="codex",
                        codex_home=None,
                        state_db=None,
                        timeout_seconds=20,
                    )
                fake_app.omit_source_parent = False
                fake_app.source_available = False
                with self.assertRaisesRegex(ValueError, "did not read back the transport source"):
                    bind_execution_session_module._mechanical_readback(
                        project,
                        plan,
                        session,
                        NATIVE_TASK_ID,
                        codex_bin="codex",
                        codex_home=None,
                        state_db=None,
                        timeout_seconds=20,
                    )
            database.close()
            self.assertEqual(observed["native_task_id"], NATIVE_TASK_ID)
            self.assertEqual(observed["actual_model_id"], "gpt-6-astra")
            self.assertEqual(observed["actual_reasoning_effort"], "max")
            self.assertEqual(observed["status"], "active-unarchived")
            self.assertEqual(observed["model_turns_observed"], 1)
            self.assertEqual(observed["prompt_transport"], "codex_delegation")
            self.assertEqual(observed["source_thread_id"], source_thread_id)
            self.assertTrue(observed["source_thread_readback"])
            self.assertTrue(observed["source_user_root_readback"])
            self.assertEqual(mentioned_protocol["source_thread_id"], source_thread_id)

    def test_native_model_mismatch_fails_without_executing_transition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            task_id, _ = create_fixture_task(project, "task-mismatch-001")
            result = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_readback={
                    "native_task_id": "019f7a4e-f1be-7771-9f67-38fcde417f48",
                    "provider": "openai",
                    "actual_model_id": "different-model",
                    "actual_reasoning_effort": "max",
                    "cwd": str(project),
                    "worktree_path": str(project),
                    "isolated_worktree": True,
                    "status": "running",
                },
                catalog_mechanically_verified=True,
            )
            self.assertEqual(result["status"], "readback_mismatch")
            self.assertEqual(result["lifecycle_status"], "plan_ready")
            self.assertFalse(result["new_conversation_created"])

    def test_selected_only_profiles_do_not_touch_agents_md(self) -> None:
        items = [
            work_item("W-01", work_type="architecture", read_scope=["api/", "domain/"]),
            work_item(
                "W-02",
                dependencies=["W-01"],
                write_scope=["api/handler.py", "domain/model.py"],
                risk="medium",
            ),
        ]
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "AGENTS.md").write_text("USER SENTINEL\n", encoding="utf-8")
            task_id, task_dir = create_fixture_task(
                project,
                "task-profiles-001",
                items=items,
                title="Cross-module migration",
            )
            launch = prepare_execution_launch(
                project,
                task_id=task_id,
                catalog=live_catalog(),
                native_capabilities={},
                catalog_mechanically_verified=True,
            )
            result = prepare_team_runtime(
                project,
                task_dir / "TEAM_PLAN.json",
                apply=True,
            )
            installed = {path.stem for path in (project / ".codex/agents").glob("*.toml")}
            self.assertEqual(installed, set(launch["selected_profiles"]))
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), "USER SENTINEL\n")
            self.assertFalse(result["agents_md_touched"])


if __name__ == "__main__":
    unittest.main()
