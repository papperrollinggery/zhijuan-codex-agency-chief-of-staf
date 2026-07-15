from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from configure_native_routing import (  # noqa: E402
    MARKER,
    MODE_HINT,
    PROBE_CONFIG_OVERRIDES,
    RoutingError,
    STATE_FILENAME,
    TOOL_NAMESPACE,
    USAGE_HINT,
    apply_setup_transaction,
    compatibility_report,
    current_matches,
    discover_compatibility_binaries,
    disable_edits,
    enable_edits,
    managed_state_matches,
    managed_values,
    previous_matches,
    prepare_codex_home,
    prepare_setup,
    probe_environment,
    read_state,
    report_status,
    require_compatible_clients,
    require_write_status,
    require_state_config,
    restore_previous_config,
    restore_managed_config,
    routing_operation_lock,
    select_control_binary,
    state_with_phase,
    supports_native_policy,
    values,
    write_state,
)


class FakeConfigApp:
    def __init__(
        self,
        config: dict[str, object],
        status: str,
        apply_edits: bool,
        *,
        include_version: bool = True,
        concurrent_before_write: bool = False,
    ) -> None:
        self.config = config
        self.status = status
        self.apply_edits = apply_edits
        self.include_version = include_version
        self.concurrent_before_write = concurrent_before_write
        self.version = 0

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        if method == "config/read":
            layer = {
                "name": {"type": "user", "profile": None},
                "config": self.config,
            }
            if self.include_version:
                layer["version"] = str(self.version)
            return {
                "layers": [
                    layer
                ],
                "config": self.config,
            }
        if method != "config/batchWrite":
            raise AssertionError(method)
        if self.concurrent_before_write:
            self.concurrent_before_write = False
            self.version += 1
        if params.get("expectedVersion") != str(self.version):
            return {"status": "conflict", "version": str(self.version)}
        self.version += 1
        if self.apply_edits:
            features = self.config.setdefault("features", {})
            for edit in params["edits"]:
                if edit["keyPath"] == "features.multi_agent_v2":
                    if edit["value"] is None:
                        features.pop("multi_agent_v2", None)
                    else:
                        features["multi_agent_v2"] = edit["value"]
                    continue
                feature = features.setdefault("multi_agent_v2", {})
                key = str(edit["keyPath"]).rsplit(".", 1)[-1]
                if edit["value"] is None:
                    feature.pop(key, None)
                else:
                    feature[key] = edit["value"]
        return {"status": self.status, "version": str(self.version)}


class NativeRoutingConfigTests(unittest.TestCase):
    def test_compatibility_discovery_deduplicates_target_path_and_desktop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target" / "codex"
            extra = root / "extra" / "codex"
            desktop = root / "desktop-codex"
            for binary in (target, extra, desktop):
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                binary.chmod(0o700)
            with patch.dict(
                os.environ,
                {"PATH": os.pathsep.join((str(target.parent), str(extra.parent)))},
            ), patch(
                "configure_native_routing.DESKTOP_CODEX_CANDIDATES",
                (desktop,),
            ):
                observed = discover_compatibility_binaries(target.resolve(), [])
            self.assertEqual(
                observed,
                [target.resolve(), extra.resolve(), desktop.resolve()],
            )

    def test_compatibility_discovery_rejects_ambiguous_empty_path_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            implicit = root / "codex"
            implicit.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            implicit.chmod(0o700)
            with patch.dict(os.environ, {"PATH": os.pathsep}, clear=True):
                with self.assertRaisesRegex(RoutingError, "empty segment"):
                    discover_compatibility_binaries(
                        Path("/tmp/explicit-codex"), [], path_cwd=root
                    )

    def test_compatibility_requires_exact_semantic_config_readback(self) -> None:
        class FakeProbeApp:
            config: dict[str, object] = {
                "features": {
                    "multi_agent_v2": {
                        "hide_spawn_agent_metadata": False,
                        "tool_namespace": "agents",
                        "multi_agent_mode_hint_text": "probe-mode",
                        "usage_hint_text": "probe-usage",
                    }
                }
            }
            last_kwargs: dict[str, object] = {}

            def __init__(self, _binary: Path, **kwargs: object) -> None:
                type(self).last_kwargs = kwargs
                self.codex_home = kwargs["codex_home"]

            def __enter__(self) -> "FakeProbeApp":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def request(
                self, method: str, _params: dict[str, object]
            ) -> dict[str, object]:
                self.assert_method(method)
                return {"config": type(self).config}

            @staticmethod
            def assert_method(method: str) -> None:
                if method != "config/read":
                    raise AssertionError(method)

        with patch("configure_native_routing.CodexAppServer", FakeProbeApp):
            compatible, detail = supports_native_policy(Path("/tmp/codex"))
        self.assertTrue(compatible)
        self.assertEqual(detail, "supported and read back")
        self.assertEqual(
            FakeProbeApp.last_kwargs["config_overrides"], PROBE_CONFIG_OVERRIDES
        )
        environment = FakeProbeApp.last_kwargs["process_environment"]
        self.assertIsInstance(environment, dict)
        self.assertNotIn("OPENAI_API_KEY", environment)

        FakeProbeApp.config = {
            "features": {
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": False,
                    "tool_namespace": "ignored-by-client",
                    "multi_agent_mode_hint_text": "probe-mode",
                    "usage_hint_text": "probe-usage",
                }
            }
        }
        with patch("configure_native_routing.CodexAppServer", FakeProbeApp):
            compatible, detail = supports_native_policy(Path("/tmp/codex"))
        self.assertFalse(compatible)
        self.assertIn("semantic readback mismatch: namespace", detail)

    def test_recovery_selects_compatible_control_client(self) -> None:
        old = Path("/tmp/old-codex")
        current = Path("/tmp/current-codex")
        report = [
            {
                "path": str(old),
                "version": "old",
                "compatible": False,
                "detail": "unknown field",
            },
            {
                "path": str(current),
                "version": "current",
                "compatible": True,
                "detail": "supported",
            },
        ]
        self.assertEqual(
            select_control_binary(old, report, recovery_operation=True), current
        )
        self.assertEqual(
            select_control_binary(old, report, recovery_operation=False), old
        )
        with self.assertRaisesRegex(RoutingError, "at least one compatible"):
            select_control_binary(old, report[:1], recovery_operation=True)

    def test_compatibility_report_and_gate_fail_closed(self) -> None:
        first = Path("/tmp/codex-one")
        second = Path("/tmp/codex-two")
        with patch(
            "configure_native_routing.supports_native_policy",
            side_effect=[(True, "supported"), (False, "unknown field")],
        ), patch(
            "configure_native_routing.probe_binary_version",
            side_effect=["codex 1", "codex 2"],
        ):
            report = compatibility_report([first, second])
        self.assertTrue(report[0]["compatible"])
        self.assertFalse(report[1]["compatible"])
        with self.assertRaisesRegex(RoutingError, "shared Codex config unreadable"):
            require_compatible_clients(report, allow_incompatible=False)
        require_compatible_clients(report, allow_incompatible=True)

    def test_compatibility_probe_environment_drops_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HOME": "/tmp/home",
                "PATH": "/usr/bin:/bin",
                "OPENAI_API_KEY": "secret",
                "ANTHROPIC_API_KEY": "secret",
                "GH_TOKEN": "secret",
            },
            clear=True,
        ):
            environment = probe_environment(Path("/tmp/probe-home"))
        self.assertEqual(environment["CODEX_HOME"], "/tmp/probe-home")
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("GH_TOKEN", environment)

    def test_operation_lock_serializes_mutations_and_persists_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first_inode = home.stat().st_ino
            with routing_operation_lock(home, exclusive=True):
                with self.assertRaisesRegex(RoutingError, "operation is in progress"):
                    with routing_operation_lock(home, exclusive=True):
                        self.fail("a second writer acquired the routing lock")
                with self.assertRaisesRegex(RoutingError, "operation is in progress"):
                    with routing_operation_lock(home, exclusive=False):
                        self.fail("a status reader observed a mutation in progress")
            with routing_operation_lock(home, exclusive=True):
                self.assertEqual(home.stat().st_ino, first_inode)
            self.assertEqual(list(home.iterdir()), [])

    def test_codex_home_is_never_created_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-home"
            with self.assertRaisesRegex(RoutingError, "not created without --apply"):
                prepare_codex_home(missing, allow_create=False)
            self.assertFalse(missing.exists())
            created = prepare_codex_home(missing, allow_create=True)
            self.assertEqual(created, missing.resolve())
            self.assertEqual(created.stat().st_mode & 0o777, 0o700)

    def test_scalar_feature_is_replaced_and_restored_as_scalar(self) -> None:
        config = {"features": {"multi_agent_v2": True}}
        state, edits, rollback = prepare_setup(
            config, None, Path("/tmp/codex/config.toml"), False
        )
        self.assertEqual(edits[0]["keyPath"], "features.multi_agent_v2")
        self.assertTrue(edits[0]["value"]["enabled"])
        self.assertEqual(edits[0]["value"]["tool_namespace"], TOOL_NAMESPACE)
        self.assertEqual(rollback[0]["value"], True)
        self.assertEqual(disable_edits(state)[0]["value"], True)
        managed_config = {"features": {"multi_agent_v2": dict(edits[0]["value"])}}
        self.assertTrue(managed_state_matches(managed_config, state))
        managed_config["features"]["multi_agent_v2"]["enabled"] = False
        self.assertFalse(managed_state_matches(managed_config, state))
        managed_config["features"]["multi_agent_v2"]["enabled"] = True
        managed_config["features"]["multi_agent_v2"]["unrelated"] = "concurrent"
        self.assertFalse(managed_state_matches(managed_config, state))

    def test_table_setup_owns_only_four_fields(self) -> None:
        config = {
            "features": {
                "multi_agent_v2": {"enabled": True, "unrelated": "preserve"}
            }
        }
        state, edits, _ = prepare_setup(
            config, None, Path("/tmp/codex/config.toml"), False
        )
        self.assertEqual(len(edits), 4)
        self.assertNotIn("unrelated", " ".join(edit["keyPath"] for edit in edits))
        self.assertEqual(state["managed"], managed_values())

    def test_user_authored_hint_requires_explicit_replace(self) -> None:
        config = {
            "features": {
                "multi_agent_v2": {"multi_agent_mode_hint_text": "user policy"}
            }
        }
        with self.assertRaisesRegex(RoutingError, "user-authored mode"):
            prepare_setup(config, None, Path("/tmp/codex/config.toml"), False)
        state, edits, _ = prepare_setup(
            config, None, Path("/tmp/codex/config.toml"), True
        )
        self.assertEqual(state["previous"]["mode"]["value"], "user policy")
        self.assertEqual(len(edits), 4)

        for key, value in (
            ("hide_spawn_agent_metadata", True),
            ("tool_namespace", "custom"),
            ("usage_hint_text", "user usage"),
            ("multi_agent_mode_hint_text", MODE_HINT + "tampered"),
            ("usage_hint_text", MARKER + "\nstale or forged usage"),
            ("usage_hint_text", USAGE_HINT + "tampered"),
        ):
            with self.subTest(key=key):
                config = {"features": {"multi_agent_v2": {key: value}}}
                with self.assertRaisesRegex(RoutingError, "user-authored"):
                    prepare_setup(
                        config, None, Path("/tmp/codex/config.toml"), False
                    )
                prepare_setup(config, None, Path("/tmp/codex/config.toml"), True)

    def test_status_keeps_policy_and_runtime_evidence_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_path = home / "config.toml"
            state, _, _ = prepare_setup(
                {"features": {"multi_agent_v2": {}}},
                None,
                config_path,
                False,
            )
            active = state_with_phase(state, "active", "previous")
            managed = state["managed"]
            config = {
                "features": {
                    "multi_agent_v2": {
                        "hide_spawn_agent_metadata": managed["metadata"],
                        "tool_namespace": managed["namespace"],
                        "multi_agent_mode_hint_text": managed["mode"],
                        "usage_hint_text": managed["usage"],
                    }
                }
            }
            app = FakeConfigApp(config, "ok", True)
            app.codex_home = home
            app.config_path = config_path
            write_state(home / STATE_FILENAME, active)
            binary = Path("/tmp/current-codex")
            clients = [
                {
                    "path": str(binary),
                    "version": "current",
                    "compatible": True,
                    "detail": "supported",
                }
            ]
            output = io.StringIO()
            with redirect_stdout(output):
                status = report_status(
                    binary=binary,
                    clients=clients,
                    app=app,
                    cwd=home,
                    require_effective=True,
                    as_json=True,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertTrue(payload["policy_installed"])
            self.assertTrue(payload["policy_effective"])
            self.assertFalse(payload["route_acceptance_verified"])
            self.assertFalse(payload["runtime_identity_verified"])

            incompatible = clients + [
                {
                    "path": "/tmp/old-codex",
                    "version": "old",
                    "compatible": False,
                    "detail": "unknown field",
                }
            ]
            with redirect_stdout(io.StringIO()):
                status = report_status(
                    binary=binary,
                    clients=incompatible,
                    app=app,
                    cwd=home,
                    require_effective=True,
                    as_json=True,
                )
            self.assertEqual(status, 1)

    def test_state_round_trip_is_private_and_detects_managed_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = {
                "schema": 2,
                "managed_by": "agency-chief-of-staff",
                "phase": "active",
                "recovery_target": "previous",
                "config_file": str(Path(tmp) / "config.toml"),
                "managed": managed_values(),
                "previous": {
                    key: {"present": False, "value": None}
                    for key in ("metadata", "namespace", "mode", "usage")
                },
                "scalar_origin": None,
            }
            write_state(path, state)
            observed = read_state(path)
            self.assertEqual(observed, state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            effective = {
                "features": {
                    "multi_agent_v2": {
                        "hide_spawn_agent_metadata": False,
                        "tool_namespace": "agents",
                        "multi_agent_mode_hint_text": MODE_HINT,
                        "usage_hint_text": managed_values()["usage"],
                    }
                }
            }
            self.assertTrue(current_matches(values(effective), managed_values()))

    def test_state_read_rejects_symlink_public_or_malformed_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = {
                "schema": 2,
                "managed_by": "agency-chief-of-staff",
                "phase": "active",
                "recovery_target": "previous",
                "config_file": str(root / "config.toml"),
                "managed": managed_values(),
                "previous": {
                    key: {"present": False, "value": None}
                    for key in ("metadata", "namespace", "mode", "usage")
                },
                "scalar_origin": None,
            }
            state = root / "state.json"
            write_state(state, valid)
            link = root / "state-link.json"
            link.symlink_to(state)
            with self.assertRaisesRegex(RoutingError, "non-symlink"):
                read_state(link)

            state.chmod(0o644)
            with self.assertRaisesRegex(RoutingError, "private"):
                read_state(state)
            state.chmod(0o600)

            malformed = dict(valid)
            malformed["managed"] = dict(managed_values(), namespace="external")
            write_state(state, valid)
            state.write_text(json.dumps(malformed), encoding="utf-8")
            state.chmod(0o600)
            with self.assertRaisesRegex(RoutingError, "managed values"):
                read_state(state)

    def test_journal_precedes_activation_and_reconstructs_both_targets(self) -> None:
        config = {
            "features": {
                "multi_agent_v2": {
                    "enabled": True,
                    "hide_spawn_agent_metadata": True,
                }
            }
        }
        state, edits, _ = prepare_setup(
            config, None, Path("/tmp/codex/config.toml"), True
        )
        self.assertEqual(state["phase"], "pending-enable")
        self.assertEqual(state["recovery_target"], "previous")
        self.assertEqual(enable_edits(state), edits)
        self.assertTrue(previous_matches(config, state))
        active = state_with_phase(state, "active", "previous")
        self.assertEqual(active["phase"], "active")
        self.assertEqual(state["phase"], "pending-enable")

    def test_write_status_and_non_active_journal_fail_closed(self) -> None:
        require_write_status({"status": "ok"}, "test")
        require_write_status({"status": "okOverridden"}, "test")
        with self.assertRaisesRegex(RoutingError, "unexpected config status"):
            require_write_status({"status": "failed"}, "test")
        state, _, _ = prepare_setup(
            {"features": {"multi_agent_v2": {}}},
            None,
            Path("/tmp/codex/config.toml"),
            False,
        )
        with self.assertRaisesRegex(RoutingError, "requires --recover"):
            prepare_setup(
                {"features": {"multi_agent_v2": {}}},
                state,
                Path("/tmp/codex/config.toml"),
                False,
            )

    def test_journal_is_bound_to_the_active_codex_config(self) -> None:
        state, _, _ = prepare_setup(
            {"features": {"multi_agent_v2": {}}},
            None,
            Path("/tmp/one/config.toml"),
            False,
        )
        require_state_config(state, Path("/tmp/one/config.toml"))
        with self.assertRaisesRegex(RoutingError, "different Codex config"):
            require_state_config(state, Path("/tmp/two/config.toml"))

    def test_unconfirmed_setup_never_rolls_back_and_retains_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"features": {"multi_agent_v2": {}}}
            state, edits, _ = prepare_setup(
                config, None, root / "config.toml", False
            )
            journal = root / "routing.json"
            app = FakeConfigApp(config, "failed", False)
            with self.assertRaisesRegex(RoutingError, "no rollback was attempted"):
                apply_setup_transaction(app, root, journal, state, edits, "0")
            self.assertEqual(app.version, 1)
            self.assertEqual(read_state(journal)["phase"], "recovery-needed")

    def test_mutations_fail_closed_without_user_layer_cas_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"features": {"multi_agent_v2": {}}}
            state, edits, _ = prepare_setup(
                config, None, root / "config.toml", False
            )
            journal = root / "routing.json"
            app = FakeConfigApp(
                config, "ok", True, include_version=False
            )
            with self.assertRaisesRegex(RoutingError, "without CAS"):
                apply_setup_transaction(app, root, journal, state, edits, None)
            self.assertFalse(journal.exists())
            self.assertEqual(app.version, 0)

            managed = {
                "features": {
                    "multi_agent_v2": {
                        "hide_spawn_agent_metadata": state["managed"]["metadata"],
                        "tool_namespace": state["managed"]["namespace"],
                        "multi_agent_mode_hint_text": state["managed"]["mode"],
                        "usage_hint_text": state["managed"]["usage"],
                    }
                }
            }
            restore_app = FakeConfigApp(
                managed, "ok", True, include_version=False
            )
            with self.assertRaisesRegex(RoutingError, "without CAS"):
                restore_previous_config(restore_app, root, state)
            self.assertEqual(restore_app.version, 0)

    def test_cas_rejects_concurrent_user_layer_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"features": {"multi_agent_v2": {}}}
            state, edits, _ = prepare_setup(
                config, None, root / "config.toml", False
            )
            journal = root / "routing.json"
            app = FakeConfigApp(
                config, "ok", True, concurrent_before_write=True
            )
            with self.assertRaisesRegex(RoutingError, "no rollback was attempted"):
                apply_setup_transaction(app, root, journal, state, edits, "0")
            self.assertEqual(app.version, 1)
            self.assertEqual(config, {"features": {"multi_agent_v2": {}}})
            self.assertEqual(read_state(journal)["phase"], "recovery-needed")

    def test_restore_checks_batch_status_and_user_layer_readback(self) -> None:
        config = {"features": {"multi_agent_v2": {}}}
        state, _, _ = prepare_setup(
            config, None, Path("/tmp/codex/config.toml"), False
        )
        managed_config = {
            "features": {
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": False,
                    "tool_namespace": TOOL_NAMESPACE,
                    "multi_agent_mode_hint_text": MODE_HINT,
                    "usage_hint_text": managed_values()["usage"],
                }
            }
        }
        failed = FakeConfigApp(managed_config, "failed", False)
        with self.assertRaisesRegex(RoutingError, "unexpected config status"):
            restore_previous_config(failed, Path("/tmp"), state)

        stale = FakeConfigApp(managed_config, "ok", False)
        with self.assertRaisesRegex(RoutingError, "readback mismatch"):
            restore_previous_config(stale, Path("/tmp"), state)

        restored = FakeConfigApp(managed_config, "ok", True)
        self.assertTrue(restore_previous_config(restored, Path("/tmp"), state))

    def test_restore_never_overwrites_concurrent_user_changes(self) -> None:
        original = {"features": {"multi_agent_v2": {}}}
        state, _, _ = prepare_setup(
            original, None, Path("/tmp/codex/config.toml"), False
        )
        concurrent_config = {
            "features": {
                "multi_agent_v2": {
                    "hide_spawn_agent_metadata": True,
                    "tool_namespace": "user-custom",
                    "multi_agent_mode_hint_text": "concurrent mode",
                    "usage_hint_text": "concurrent usage",
                }
            }
        }
        app = FakeConfigApp(concurrent_config, "ok", True)
        before = json.loads(json.dumps(concurrent_config))
        with self.assertRaisesRegex(RoutingError, "concurrent user-layer"):
            restore_previous_config(app, Path("/tmp"), state)
        self.assertEqual(app.version, 0)
        self.assertEqual(concurrent_config, before)

        with self.assertRaisesRegex(RoutingError, "concurrent user-layer"):
            restore_managed_config(app, Path("/tmp"), state)
        self.assertEqual(app.version, 0)
        self.assertEqual(concurrent_config, before)

    def test_scalar_restore_rejects_enabled_or_extra_field_changes(self) -> None:
        for mutation in ("enabled", "extra"):
            with self.subTest(mutation=mutation):
                original = {"features": {"multi_agent_v2": True}}
                state, edits, _ = prepare_setup(
                    original, None, Path("/tmp/codex/config.toml"), False
                )
                managed = {"features": {"multi_agent_v2": dict(edits[0]["value"])}}
                if mutation == "enabled":
                    managed["features"]["multi_agent_v2"]["enabled"] = False
                else:
                    managed["features"]["multi_agent_v2"]["unrelated"] = "user"
                before = json.loads(json.dumps(managed))
                app = FakeConfigApp(managed, "ok", True)
                with self.assertRaisesRegex(RoutingError, "concurrent user-layer"):
                    restore_previous_config(app, Path("/tmp"), state)
                self.assertEqual(app.version, 0)
                self.assertEqual(managed, before)


if __name__ == "__main__":
    unittest.main()
