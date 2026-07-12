from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_skill.py"
sys.path.insert(0, str(ROOT / "scripts"))
import install_skill  # noqa: E402


class InstallSkillTests(unittest.TestCase):
    def run_installer(
        self, *args: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(INSTALLER), *args],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def targets(self, target_root: Path) -> dict[str, Path]:
        return {
            name: target_root / name for name in install_skill.INSTALL_NAMES
        }

    def expected(self, name: str) -> dict[str, str]:
        return install_skill.rendered_runtime_manifest(ROOT, name)

    def expected_pair(self) -> dict[str, dict[str, str]]:
        return {name: self.expected(name) for name in install_skill.INSTALL_NAMES}

    def expected_revision(self) -> str:
        return install_skill.package_source_revision_sha256(self.expected_pair())

    def actual(self, target: Path, name: str) -> dict[str, str]:
        return install_skill.installed_manifest(target, self.expected(name))

    def seed_old_pair(self, target_root: Path) -> dict[str, Path]:
        targets = self.targets(target_root)
        for name, target in targets.items():
            target.mkdir(parents=True)
            (target / "sentinel.txt").write_text(f"old-{name}", encoding="utf-8")
        return targets

    def test_pair_install_writes_canonical_and_generated_legacy_without_agents_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "project"
            target_root = base / "skills"
            project.mkdir()
            project_agents = project / "AGENTS.md"
            project_agents.write_text("USER SENTINEL\n", encoding="utf-8")

            result = self.run_installer(
                "--target-root", str(target_root), "--json", cwd=project
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "installed")
            self.assertEqual(
                payload["package_source_revision_sha256"], self.expected_revision()
            )
            self.assertEqual(
                payload["transaction_lock_scope"], "cooperating-installers-only"
            )
            self.assertEqual(payload["transaction_lock_kind"], "os-advisory-flock")
            self.assertTrue(payload["cleanup_complete"])
            self.assertEqual(payload["cleanup_guidance"], [])
            self.assertFalse(payload["agents_md_written"])
            self.assertFalse(payload["agents_md_dependency"])
            self.assertEqual(project_agents.read_text(encoding="utf-8"), "USER SENTINEL\n")

            for name, installed in self.targets(target_root).items():
                self.assertEqual(
                    self.actual(installed, name), self.expected(name)
                )
                self.assertFalse((installed / "AGENTS.md").exists())
                self.assertFalse(list(installed.rglob("AGENTS.override.md")))

            canonical = target_root / install_skill.CANONICAL_SKILL_NAME / "SKILL.md"
            legacy = target_root / install_skill.LEGACY_SKILL_NAME / "SKILL.md"
            self.assertIn(
                f"name: {install_skill.CANONICAL_SKILL_NAME}",
                canonical.read_text(encoding="utf-8"),
            )
            legacy_text = legacy.read_text(encoding="utf-8")
            self.assertIn(f"name: {install_skill.LEGACY_SKILL_NAME}", legacy_text)
            self.assertIn("入口：legacy", legacy_text)
            self.assertNotIn("入口：canonical", legacy_text)
            self.assertIn(
                install_skill.LEGACY_ACTIVATION_SENTENCE, legacy_text
            )
            self.assertNotIn(
                install_skill.CANONICAL_ACTIVATION_SENTENCE, legacy_text
            )
            self.assertIn(
                install_skill.LEGACY_PRELOAD_ANNOUNCEMENT, legacy_text
            )
            self.assertNotIn(
                install_skill.CANONICAL_PRELOAD_ANNOUNCEMENT, legacy_text
            )
            self.assertIn(
                install_skill.CANONICAL_PRELOAD_ANNOUNCEMENT,
                canonical.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "read only this bundle's SKILL.md in full",
                legacy_text,
            )
            legacy_yaml = (
                target_root
                / install_skill.LEGACY_SKILL_NAME
                / "agents"
                / "openai.yaml"
            ).read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", legacy_yaml)

    def test_dry_run_is_non_mutating_and_pair_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            dry = self.run_installer(
                "--target-root", str(target_root), "--dry-run", "--json"
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            dry_payload = json.loads(dry.stdout)
            self.assertEqual(dry_payload["status"], "would-install")
            self.assertEqual(
                dry_payload["package_source_revision_sha256"], self.expected_revision()
            )
            self.assertFalse(target_root.exists())

            first = self.run_installer("--target-root", str(target_root), "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            first_payload = json.loads(first.stdout)
            self.assertEqual(
                first_payload["package_source_revision_sha256"], self.expected_revision()
            )
            second = self.run_installer(
                "--target-root", str(target_root), "--dry-run", "--json"
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            second_payload = json.loads(second.stdout)
            self.assertEqual(second_payload["status"], "already-installed")
            self.assertTrue(second_payload["cleanup_complete"])
            self.assertEqual(second_payload["residual_paths"], [])
            self.assertEqual(second_payload["cleanup_guidance"], [])
            self.assertEqual(
                second_payload["package_source_revision_sha256"],
                first_payload["package_source_revision_sha256"],
            )

    def test_package_source_revision_is_pair_content_addressed_and_order_independent(
        self,
    ) -> None:
        manifests = self.expected_pair()
        revision = install_skill.package_source_revision_sha256(manifests)
        reordered = {
            name: dict(reversed(list(manifests[name].items())))
            for name in reversed(install_skill.INSTALL_NAMES)
        }
        self.assertEqual(
            install_skill.package_source_revision_sha256(reordered), revision
        )

        for name in install_skill.INSTALL_NAMES:
            with self.subTest(changed_bundle=name):
                drifted = {
                    bundle_name: dict(manifest)
                    for bundle_name, manifest in manifests.items()
                }
                first_path = next(iter(drifted[name]))
                original = drifted[name][first_path]
                drifted[name][first_path] = (
                    "0" * 64 if original != "0" * 64 else "1" * 64
                )
                self.assertNotEqual(
                    install_skill.package_source_revision_sha256(drifted), revision
                )

    def test_active_install_lock_returns_structured_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            with install_skill.install_lock(target_root):
                result = self.run_installer(
                    "--target-root", str(target_root), "--json"
                )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "conflict")
            self.assertIn("another install may be active", payload["message"])
            self.assertNotIn("package_source_revision_sha256", payload)
            lock = target_root / (
                f".{install_skill.CANONICAL_SKILL_NAME}.install.lock"
            )
            self.assertTrue(lock.is_file())

    def test_crashed_lock_holder_does_not_leave_a_stale_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            code = (
                "import os,sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
                "import install_skill; "
                f"ctx=install_skill.install_lock(Path({str(target_root)!r})); "
                "ctx.__enter__(); os._exit(0)"
            )
            crashed = subprocess.run([sys.executable, "-c", code], check=False)
            self.assertEqual(crashed.returncode, 0)

            result = self.run_installer(
                "--target-root", str(target_root), "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "installed")

    def test_lock_rejects_symlinks_and_overbroad_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target_root = base / "skills"
            target_root.mkdir()
            lock = target_root / (
                f".{install_skill.CANONICAL_SKILL_NAME}.install.lock"
            )
            external = base / "external.txt"
            external.write_text("keep", encoding="utf-8")
            lock.symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, "opened safely"):
                with install_skill.install_lock(target_root):
                    self.fail("unsafe symlink lock was acquired")
            self.assertEqual(external.read_text(encoding="utf-8"), "keep")

            lock.unlink()
            lock.write_text("stale\n", encoding="utf-8")
            lock.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "permissions are too broad"):
                with install_skill.install_lock(target_root):
                    self.fail("overbroad lock was acquired")

    def test_source_target_overlap_is_rejected_before_lock_creation(self) -> None:
        cases = (
            (ROOT, ROOT),
            (ROOT, ROOT / "nested-target-root"),
            (ROOT, ROOT.parent),
        )
        for source, target_root in cases:
            with self.subTest(target_root=target_root):
                targets = self.targets(target_root)
                with self.assertRaisesRegex(ValueError, "overlapping"):
                    install_skill.validate_install_paths(source, target_root, targets)

        output = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(INSTALLER), "--target-root", str(ROOT.parent), "--json"],
            ),
            mock.patch.object(
                install_skill,
                "install_lock",
                side_effect=AssertionError("lock must not be reached"),
            ),
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            install_skill.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("overlapping", json.loads(output.getvalue())["message"])

    def test_force_replaces_both_stale_targets_and_cleans_transaction_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            self.seed_old_pair(target_root)
            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "replaced")
            for name, target in self.targets(target_root).items():
                self.assertEqual(self.actual(target, name), self.expected(name))
                self.assertFalse((target / "sentinel.txt").exists())
            self.assertFalse(list(target_root.glob(".*.staging-*")))
            self.assertFalse(list(target_root.glob(".*.backup-*")))
            self.assertFalse(list(target_root.glob(".*.failed-*")))
            lock = target_root / (
                f".{install_skill.CANONICAL_SKILL_NAME}.install.lock"
            )
            self.assertTrue(lock.is_file())
            self.assertEqual(os.stat(lock).st_mode & 0o777, 0o600)

    def test_sealed_tree_contamination_is_never_current_and_force_repairs(self) -> None:
        contaminations = (
            "fifo",
            "socket",
            "empty-directory",
            "world-writable-file",
            "world-writable-directory",
            "hardlink",
        )
        for contamination in contaminations:
            with self.subTest(contamination=contamination), tempfile.TemporaryDirectory(
                prefix="aci.", dir="/tmp"
            ) as tmp:
                base = Path(tmp)
                target_root = base / "skills"
                initial = self.run_installer(
                    "--target-root", str(target_root), "--json"
                )
                self.assertEqual(initial.returncode, 0, initial.stderr)
                canonical = target_root / install_skill.CANONICAL_SKILL_NAME

                if contamination == "fifo":
                    os.mkfifo(canonical / "unexpected.pipe")
                elif contamination == "socket":
                    socket_path = canonical / "unexpected.socket"
                    handle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    try:
                        handle.bind(str(socket_path))
                    finally:
                        handle.close()
                elif contamination == "empty-directory":
                    (canonical / "unexpected-empty").mkdir()
                elif contamination == "world-writable-file":
                    (canonical / "SKILL.md").chmod(0o666)
                elif contamination == "world-writable-directory":
                    (canonical / "references").chmod(0o777)
                elif contamination == "hardlink":
                    os.link(canonical / "SKILL.md", base / "external-hardlink")

                dry = self.run_installer(
                    "--target-root",
                    str(target_root),
                    "--dry-run",
                    "--json",
                )
                self.assertEqual(dry.returncode, 1, dry.stderr)
                dry_payload = json.loads(dry.stdout)
                self.assertEqual(dry_payload["status"], "conflict")
                self.assertEqual(
                    dry_payload["states"][install_skill.CANONICAL_SKILL_NAME],
                    "different",
                )

                live = self.run_installer(
                    "--target-root", str(target_root), "--json"
                )
                self.assertEqual(live.returncode, 1, live.stderr)
                self.assertEqual(json.loads(live.stdout)["status"], "conflict")

                repaired = self.run_installer(
                    "--target-root",
                    str(target_root),
                    "--force",
                    "--json",
                )
                self.assertEqual(repaired.returncode, 0, repaired.stderr)
                repaired_payload = json.loads(repaired.stdout)
                self.assertEqual(repaired_payload["status"], "replaced")
                self.assertEqual(
                    repaired_payload["tree_integrity_policy"],
                    install_skill.SEALED_TREE_POLICY,
                )
                self.assertTrue(repaired_payload["tree_integrity_verified"])
                for name, target in self.targets(target_root).items():
                    self.assertEqual(self.actual(target, name), self.expected(name))

    def test_force_replaces_special_root_and_cleans_its_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aci.", dir="/tmp") as tmp:
            target_root = Path(tmp) / "skills"
            target_root.mkdir()
            targets = self.targets(target_root)
            os.mkfifo(targets[install_skill.CANONICAL_SKILL_NAME])
            legacy = targets[install_skill.LEGACY_SKILL_NAME]
            legacy.mkdir()
            (legacy / "stale.txt").write_text("stale", encoding="utf-8")

            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "replaced")
            self.assertTrue(payload["cleanup_complete"])
            self.assertEqual(payload["residual_paths"], [])
            for name, target in targets.items():
                self.assertEqual(self.actual(target, name), self.expected(name))

    def test_all_transaction_artifact_types_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            target_root.mkdir()
            suffix = "0" * 32
            artifacts = (
                target_root
                / f".{install_skill.CANONICAL_SKILL_NAME}.backup-{suffix}",
                target_root
                / f".{install_skill.CANONICAL_SKILL_NAME}.staging-fixture",
                target_root
                / f".{install_skill.CANONICAL_SKILL_NAME}.failed-{suffix}",
            )
            for artifact in artifacts:
                artifact.mkdir()

            result = self.run_installer(
                "--target-root", str(target_root), "--dry-run", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["cleanup_complete"])
            self.assertEqual(
                {warning["artifact_kind"] for warning in payload["cleanup_warnings"]},
                {"backup", "staging", "failed"},
            )
            self.assertEqual(
                set(payload["residual_paths"]), {str(p.resolve()) for p in artifacts}
            )
            self.assertEqual(len(payload["cleanup_guidance"]), 3)

    def test_malformed_transaction_reserved_paths_still_block_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            installed = self.run_installer(
                "--target-root", str(target_root), "--json"
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            artifacts = tuple(
                target_root / f".{name}.{kind}-{suffix}"
                for name, suffix in (
                    (install_skill.CANONICAL_SKILL_NAME, "not-a-uuid"),
                    (install_skill.LEGACY_SKILL_NAME, ""),
                )
                for kind in ("backup", "staging", "failed")
            )
            for artifact in artifacts:
                artifact.mkdir()

            dry = self.run_installer(
                "--target-root", str(target_root), "--dry-run", "--json"
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            payload = json.loads(dry.stdout)
            self.assertEqual(payload["status"], "already-installed")
            self.assertTrue(payload["tree_integrity_verified"])
            self.assertFalse(payload["cleanup_complete"])
            self.assertEqual(
                set(payload["residual_paths"]),
                {str(path.resolve()) for path in artifacts},
            )
            self.assertEqual(len(payload["cleanup_warnings"]), len(artifacts))
            self.assertEqual(len(payload["cleanup_guidance"]), len(artifacts))

    def test_staging_cleanup_failure_is_structured_and_not_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            real_copy_runtime = install_skill.copy_runtime
            real_rmtree = install_skill.shutil.rmtree

            def fail_after_copy(
                source: Path, target: Path, skill_name: str
            ) -> None:
                real_copy_runtime(source, target, skill_name)
                raise RuntimeError("injected staging failure")

            def fail_staging_cleanup(
                path: object, *args: object, **kwargs: object
            ) -> None:
                candidate = Path(path)  # type: ignore[arg-type]
                if ".staging-" in candidate.name:
                    raise OSError("injected staging cleanup failure")
                real_rmtree(candidate, *args, **kwargs)

            output = io.StringIO()
            with (
                mock.patch.object(
                    install_skill, "copy_runtime", side_effect=fail_after_copy
                ),
                mock.patch.object(
                    install_skill.shutil,
                    "rmtree",
                    side_effect=fail_staging_cleanup,
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        str(INSTALLER),
                        "--target-root",
                        str(target_root),
                        "--force",
                        "--json",
                    ],
                ),
                redirect_stdout(output),
                self.assertRaises(SystemExit) as raised,
            ):
                install_skill.main()

            self.assertEqual(raised.exception.code, 1)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "conflict")
            self.assertIn("staging cleanup failed", payload["message"])
            self.assertFalse(payload["cleanup_complete"])
            self.assertEqual(
                {warning["artifact_kind"] for warning in payload["cleanup_warnings"]},
                {"staging"},
            )
            self.assertEqual(len(payload["residual_paths"]), 1)
            self.assertEqual(len(payload["cleanup_guidance"]), 1)
            for name, target in targets.items():
                self.assertEqual(
                    (target / "sentinel.txt").read_text(encoding="utf-8"),
                    f"old-{name}",
                )

    def test_conflict_in_one_target_does_not_mutate_current_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            installed = self.run_installer("--target-root", str(target_root))
            self.assertEqual(installed.returncode, 0, installed.stderr)
            canonical = target_root / install_skill.CANONICAL_SKILL_NAME
            legacy = target_root / install_skill.LEGACY_SKILL_NAME
            canonical_before = self.actual(
                canonical, install_skill.CANONICAL_SKILL_NAME
            )
            (legacy / "stale.txt").write_text("stale", encoding="utf-8")

            result = self.run_installer(
                "--target-root", str(target_root), "--json"
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "conflict")
            self.assertEqual(
                payload["package_source_revision_sha256"], self.expected_revision()
            )
            self.assertEqual(
                self.actual(canonical, install_skill.CANONICAL_SKILL_NAME),
                canonical_before,
            )
            self.assertTrue((legacy / "stale.txt").exists())

    def test_preflight_snapshot_rejects_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            observed = {
                name: install_skill.installed_tree_snapshot(target)
                for name, target in targets.items()
            }
            legacy = targets[install_skill.LEGACY_SKILL_NAME]
            (legacy / "concurrent.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed after preflight"):
                install_skill.verify_preflight_snapshot(targets, observed)
            self.assertTrue((legacy / "concurrent.txt").exists())

    def test_current_peer_drift_during_staging_rejects_before_any_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.targets(target_root)
            canonical = targets[install_skill.CANONICAL_SKILL_NAME]
            canonical.mkdir(parents=True)
            install_skill.copy_runtime(
                ROOT, canonical, install_skill.CANONICAL_SKILL_NAME
            )
            observed = {
                name: install_skill.installed_tree_snapshot(target)
                for name, target in targets.items()
            }
            expected = {
                name: install_skill.rendered_runtime_manifest(ROOT, name)
                for name in install_skill.INSTALL_NAMES
            }
            real_copy_runtime = install_skill.copy_runtime

            def copy_then_drift_peer(
                source: Path, target: Path, skill_name: str
            ) -> None:
                real_copy_runtime(source, target, skill_name)
                (canonical / "concurrent.txt").write_text(
                    "changed during staging", encoding="utf-8"
                )

            with mock.patch.object(
                install_skill, "copy_runtime", side_effect=copy_then_drift_peer
            ):
                with self.assertRaisesRegex(RuntimeError, "changed after preflight"):
                    install_skill.replace_many_from_staging(
                        ROOT,
                        {
                            install_skill.LEGACY_SKILL_NAME: targets[
                                install_skill.LEGACY_SKILL_NAME
                            ]
                        },
                        expected_manifests=expected,
                        transaction_targets=targets,
                        observed_manifests=observed,
                    )

            self.assertTrue((canonical / "concurrent.txt").exists())
            self.assertFalse(targets[install_skill.LEGACY_SKILL_NAME].exists())
            self.assertFalse(list(target_root.glob(".*.backup-*")))
            self.assertFalse(list(target_root.glob(".*.staging-*")))

    def test_frozen_source_manifests_reject_source_drift_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            for rel in install_skill.RUNTIME_FILES:
                destination = source / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, destination)

            target_root = base / "skills"
            targets = self.seed_old_pair(target_root)
            observed = {
                name: install_skill.installed_tree_snapshot(target)
                for name, target in targets.items()
            }
            expected = {
                name: install_skill.rendered_runtime_manifest(source, name)
                for name in install_skill.INSTALL_NAMES
            }
            real_copy_runtime = install_skill.copy_runtime
            drift_source = source / "references" / "real-threads.md"

            def copy_then_drift_source(
                source_root: Path, target: Path, skill_name: str
            ) -> None:
                real_copy_runtime(source_root, target, skill_name)
                if skill_name == install_skill.CANONICAL_SKILL_NAME:
                    drift_source.write_text(
                        drift_source.read_text(encoding="utf-8") + "\nsource drift\n",
                        encoding="utf-8",
                    )

            with mock.patch.object(
                install_skill, "copy_runtime", side_effect=copy_then_drift_source
            ):
                with self.assertRaisesRegex(RuntimeError, "staged manifest mismatch"):
                    install_skill.replace_many_from_staging(
                        source,
                        targets,
                        expected_manifests=expected,
                        transaction_targets=targets,
                        observed_manifests=observed,
                    )

            for name, target in targets.items():
                self.assertEqual(
                    (target / "sentinel.txt").read_text(encoding="utf-8"),
                    f"old-{name}",
                )
            self.assertFalse(list(target_root.glob(".*.backup-*")))
            self.assertFalse(list(target_root.glob(".*.staging-*")))

    def test_removed_agents_routing_flag_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            agents = base / "AGENTS.md"
            agents.write_text("USER SENTINEL\n", encoding="utf-8")
            result = self.run_installer(
                "--target-root", str(base / "skills"),
                "--agents-routing", "project",
                cwd=base,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(agents.read_text(encoding="utf-8"), "USER SENTINEL\n")

    def test_removed_custom_name_cannot_escape_or_create_partial_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            result = self.run_installer(
                "--target-root", str(base / "skills"), "--name", "../escape"
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((base / "escape").exists())
            self.assertFalse((base / "skills").exists())

    def test_symlink_target_preflight_does_not_mutate_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target_root = base / "skills"
            external = base / "external"
            target_root.mkdir()
            external.mkdir()
            (external / "sentinel.txt").write_text("keep", encoding="utf-8")
            canonical = target_root / install_skill.CANONICAL_SKILL_NAME
            canonical.mkdir()
            (canonical / "sentinel.txt").write_text("canonical-old", encoding="utf-8")
            (target_root / install_skill.LEGACY_SKILL_NAME).symlink_to(
                external, target_is_directory=True
            )

            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "conflict")
            self.assertEqual(
                (canonical / "sentinel.txt").read_text(encoding="utf-8"),
                "canonical-old",
            )
            self.assertEqual(
                (external / "sentinel.txt").read_text(encoding="utf-8"), "keep"
            )

    def test_force_replaces_nested_symlink_without_touching_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target_root = base / "skills"
            targets = self.seed_old_pair(target_root)
            external = base / "external.txt"
            external.write_text("DO NOT READ", encoding="utf-8")
            (targets[install_skill.LEGACY_SKILL_NAME] / "linked.txt").symlink_to(external)

            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "replaced")
            for name, target in targets.items():
                self.assertEqual(self.actual(target, name), self.expected(name))
            self.assertEqual(external.read_text(encoding="utf-8"), "DO NOT READ")

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

    def test_force_honestly_reports_removed_legacy_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            (targets[install_skill.LEGACY_SKILL_NAME] / "AGENTS.md").write_text(
                "old routing", encoding="utf-8"
            )
            result = self.run_installer(
                "--target-root", str(target_root), "--force", "--json"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["agents_md_touched"])
            self.assertFalse(payload["agents_md_written"])
            self.assertEqual(
                payload["legacy_guidance_files_removed"],
                {install_skill.LEGACY_SKILL_NAME: ["AGENTS.md"]},
            )
            self.assertEqual(payload["legacy_guidance_files_cleanup_pending"], {})
            self.assertTrue(payload["guidance_removal_complete"])
            self.assertTrue(payload["cleanup_complete"])
            self.assertEqual(payload["cleanup_warnings"], [])
            self.assertEqual(payload["residual_paths"], [])
            self.assertFalse(
                (targets[install_skill.LEGACY_SKILL_NAME] / "AGENTS.md").exists()
            )

    def test_second_backup_rename_failure_restores_both_old_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            real_rename = Path.rename

            def fail_legacy_backup(path: Path, destination: object) -> Path:
                destination_path = Path(destination)  # type: ignore[arg-type]
                if (
                    path == targets[install_skill.LEGACY_SKILL_NAME]
                    and ".backup-" in destination_path.name
                ):
                    raise OSError("injected second backup failure")
                return real_rename(path, destination_path)

            with mock.patch.object(
                Path, "rename", autospec=True, side_effect=fail_legacy_backup
            ):
                with self.assertRaisesRegex(OSError, "second backup"):
                    install_skill.replace_many_from_staging(ROOT, targets)

            for name, target in targets.items():
                self.assertEqual(
                    (target / "sentinel.txt").read_text(encoding="utf-8"),
                    f"old-{name}",
                )
            self.assertFalse(list(target_root.glob(".*.backup-*")))

    def test_second_promotion_failure_rolls_back_both_old_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            legacy_target = targets[install_skill.LEGACY_SKILL_NAME]
            real_rename = Path.rename

            def fail_legacy_promotion(path: Path, destination: object) -> Path:
                destination_path = Path(destination)  # type: ignore[arg-type]
                if path.name.startswith(f".{install_skill.LEGACY_SKILL_NAME}.staging-") and destination_path == legacy_target:
                    raise OSError("injected second promotion failure")
                return real_rename(path, destination_path)

            with mock.patch.object(
                Path, "rename", autospec=True, side_effect=fail_legacy_promotion
            ):
                with self.assertRaisesRegex(OSError, "second promotion"):
                    install_skill.replace_many_from_staging(ROOT, targets)

            for name, target in targets.items():
                self.assertEqual(
                    (target / "sentinel.txt").read_text(encoding="utf-8"),
                    f"old-{name}",
                )
            self.assertFalse(list(target_root.glob(".*.backup-*")))
            self.assertFalse(list(target_root.glob(".*.failed-*")))

    def test_backup_cleanup_failure_reports_residuals_without_rolling_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            targets = self.seed_old_pair(target_root)
            (targets[install_skill.LEGACY_SKILL_NAME] / "AGENTS.md").write_text(
                "obsolete routing", encoding="utf-8"
            )
            real_rmtree = install_skill.shutil.rmtree

            def flaky_rmtree(path: object, *args: object, **kwargs: object) -> None:
                candidate = Path(path)  # type: ignore[arg-type]
                if ".backup-" in candidate.name:
                    raise OSError("injected cleanup failure")
                real_rmtree(candidate, *args, **kwargs)

            output = io.StringIO()
            with (
                mock.patch.object(
                    install_skill.shutil, "rmtree", side_effect=flaky_rmtree
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        str(INSTALLER),
                        "--target-root",
                        str(target_root),
                        "--force",
                        "--json",
                    ],
                ),
                redirect_stdout(output),
            ):
                install_skill.main()

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "replaced")
            self.assertFalse(payload["cleanup_complete"])
            self.assertEqual(len(payload["cleanup_warnings"]), 2)
            self.assertEqual(
                {warning["skill_name"] for warning in payload["cleanup_warnings"]},
                set(install_skill.INSTALL_NAMES),
            )
            self.assertEqual(len(payload["residual_paths"]), 2)
            self.assertEqual(payload["legacy_guidance_files_removed"], {})
            self.assertEqual(
                payload["legacy_guidance_files_cleanup_pending"],
                {install_skill.LEGACY_SKILL_NAME: ["AGENTS.md"]},
            )
            self.assertFalse(payload["guidance_removal_complete"])

            plain_output = io.StringIO()
            with redirect_stdout(plain_output):
                install_skill.emit(payload, False)
            self.assertIn("cleanup warning:", plain_output.getvalue())

            for name, target in targets.items():
                self.assertEqual(self.actual(target, name), self.expected(name))
            residuals = [Path(path) for path in payload["residual_paths"]]
            self.assertTrue(all(path.exists() for path in residuals))
            self.assertEqual(
                sum(bool(list(path.rglob("AGENTS.md"))) for path in residuals), 1
            )

            follow_up = self.run_installer(
                "--target-root", str(target_root), "--json"
            )
            self.assertEqual(follow_up.returncode, 0, follow_up.stderr)
            follow_up_payload = json.loads(follow_up.stdout)
            self.assertEqual(follow_up_payload["status"], "already-installed")
            self.assertFalse(follow_up_payload["cleanup_complete"])
            self.assertEqual(
                set(follow_up_payload["residual_paths"]),
                set(payload["residual_paths"]),
            )
            self.assertEqual(
                follow_up_payload["legacy_guidance_files_cleanup_pending"],
                {install_skill.LEGACY_SKILL_NAME: ["AGENTS.md"]},
            )
            self.assertEqual(
                follow_up_payload["legacy_guidance_files_removed"], {}
            )
            self.assertFalse(follow_up_payload["guidance_removal_complete"])


if __name__ == "__main__":
    unittest.main()
