from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from inspect_codex_models import (  # noqa: E402
    build_resolver_catalog,
    canonical_state_database,
    collect_model_items,
    parse_bindings,
    provider_evidence_for_bindings,
    read_root_provider,
    state_database_connection,
)
from resolve_role_route import (  # noqa: E402
    choose_catalog_model,
    validate_catalog_provenance,
    validate_catalog_models,
)


class StubAppServer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.calls.append({"method": method, "params": dict(params)})
        if "cursor" not in params:
            return {
                "data": [
                    {
                        "model": "host-efficient",
                        "defaultReasoningEffort": "medium",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": "medium"},
                            {"reasoningEffort": "high"},
                        ],
                    }
                ],
                "nextCursor": "next-page",
            }
        return {
            "data": [
                {
                    "model": "host-judgment",
                    "defaultReasoningEffort": "high",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "high"},
                        {"reasoningEffort": "xhigh"},
                    ],
                }
            ],
            "nextCursor": None,
        }


class CodexModelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = collect_model_items(StubAppServer())

    def test_catalog_is_consumed_by_existing_role_resolver(self) -> None:
        catalog = build_resolver_catalog(
            self.items,
            parse_bindings(
                ["efficient=host-efficient", "judgment=host-judgment"]
            ),
            root_provider="openai",
            source_id="current-test-model-list",
            provenance_source="active-host-catalog",
            requested_thread_id="11111111-1111-1111-1111-111111111111",
            canonical_state_store_bound=True,
            model_provider_evidence="root-state-inferred",
        )
        provenance = validate_catalog_provenance(catalog, "direct", "openai")
        validated = validate_catalog_models(catalog)
        efficient = choose_catalog_model(
            catalog, "codebase-researcher", "efficient", "medium", "direct", "openai"
        )
        judgment = choose_catalog_model(
            catalog, "reviewer", "judgment", "high", "direct", "openai"
        )
        self.assertEqual(provenance["source"], "active-host-catalog")
        self.assertEqual(len(validated), 2)
        self.assertEqual(efficient["id"], "host-efficient")
        self.assertEqual(judgment["id"], "host-judgment")

    def test_model_list_pagination_is_preserved(self) -> None:
        app = StubAppServer()
        items = collect_model_items(app)
        self.assertEqual(
            [item["model"] for item in items],
            ["host-efficient", "host-judgment"],
        )
        self.assertEqual(app.calls[1]["params"]["cursor"], "next-page")

    def test_provider_evidence_is_derived_from_live_bound_items(self) -> None:
        bindings = {
            "host-efficient": "efficient",
            "host-judgment": "judgment",
        }
        self.assertEqual(
            provider_evidence_for_bindings(
                self.items,
                bindings,
                root_provider="openai",
                fallback="root-state-inferred",
            ),
            "root-state-inferred",
        )
        advertised = [dict(item, modelProvider="openai") for item in self.items]
        self.assertEqual(
            provider_evidence_for_bindings(
                advertised,
                bindings,
                root_provider="openai",
                fallback="root-state-inferred",
            ),
            "catalog-advertised",
        )

    def test_missing_model_and_provider_mismatch_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "absent from current"):
            build_resolver_catalog(
                self.items,
                {"not-listed": "efficient"},
                root_provider="openai",
                source_id="current-test-model-list",
                provenance_source="active-host-catalog",
                requested_thread_id="11111111-1111-1111-1111-111111111111",
                canonical_state_store_bound=True,
                model_provider_evidence="root-state-inferred",
            )
        mismatched = [dict(self.items[0], modelProvider="other")]
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_resolver_catalog(
                mismatched,
                {"host-efficient": "efficient"},
                root_provider="openai",
                source_id="current-test-model-list",
                provenance_source="active-host-catalog",
                requested_thread_id="11111111-1111-1111-1111-111111111111",
                canonical_state_store_bound=True,
                model_provider_evidence="root-state-inferred",
            )

    def test_bindings_reject_unknown_classes_and_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported model class"):
            parse_bindings(["premium=host-efficient"])
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_bindings(
                ["efficient=host-efficient", "balanced=host-efficient"]
            )
        with self.assertRaisesRegex(ValueError, "class is bound more than once"):
            parse_bindings(
                ["efficient=host-efficient", "efficient=host-judgment"]
            )

    def test_root_provider_is_read_from_the_requested_persisted_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "state.sqlite"
            database = sqlite3.connect(database_path)
            try:
                database.execute("CREATE TABLE threads (id TEXT, model_provider TEXT)")
                database.execute(
                    "INSERT INTO threads VALUES (?, ?)",
                    ("11111111-1111-1111-1111-111111111111", "openai"),
                )
                database.commit()
            finally:
                database.close()
            self.assertEqual(
                read_root_provider(
                    database_path, "11111111-1111-1111-1111-111111111111"
                ),
                "openai",
            )

    def test_state_readback_observes_uncheckpointed_wal_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "state.sqlite"
            writer = sqlite3.connect(database_path)
            try:
                self.assertEqual(writer.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
                writer.execute("PRAGMA wal_autocheckpoint = 0")
                writer.execute("CREATE TABLE threads (id TEXT, model_provider TEXT)")
                writer.execute(
                    "INSERT INTO threads VALUES (?, ?)",
                    ("11111111-1111-1111-1111-111111111111", "old-provider"),
                )
                writer.commit()
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                writer.execute(
                    "UPDATE threads SET model_provider = ? WHERE id = ?",
                    ("openai", "11111111-1111-1111-1111-111111111111"),
                )
                writer.commit()
                self.assertTrue(Path(str(database_path) + "-wal").exists())
                self.assertEqual(
                    read_root_provider(
                        database_path, "11111111-1111-1111-1111-111111111111"
                    ),
                    "openai",
                )
            finally:
                writer.close()

    def test_state_readback_rejects_identity_replacement_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = Path(tmp) / "state.sqlite"
            database = sqlite3.connect(database_path)
            database.execute("CREATE TABLE threads (id TEXT)")
            database.commit()
            database.close()
            original = database_path.stat()
            database_path.rename(Path(tmp) / "original.sqlite")
            replacement = sqlite3.connect(database_path)
            replacement.execute("CREATE TABLE threads (id TEXT)")
            replacement.commit()
            replacement.close()
            with self.assertRaisesRegex(ValueError, "changed between canonical validation"):
                with state_database_connection(
                    database_path,
                    expected_identity=(original.st_dev, original.st_ino),
                ):
                    self.fail("replacement database must not be yielded")

    def test_state_binding_requires_canonical_codex_home_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            canonical = home / "state_5.sqlite"
            canonical.write_bytes(b"state")
            self.assertEqual(
                canonical_state_database(canonical, home), canonical.resolve()
            )
            other = home / "other.sqlite"
            other.write_bytes(b"state")
            with self.assertRaisesRegex(ValueError, "codexHome/state_5.sqlite"):
                canonical_state_database(other, home)

            canonical.unlink()
            sqlite_dir = home / "sqlite"
            sqlite_dir.mkdir()
            nested = sqlite_dir / "state_5.sqlite"
            nested.write_bytes(b"state")
            canonical.symlink_to(nested)
            self.assertEqual(
                canonical_state_database(canonical, home), nested.resolve()
            )

            canonical.unlink()
            alternate = home / "alternate.sqlite"
            alternate.write_bytes(b"state")
            canonical.symlink_to(alternate)
            with self.assertRaisesRegex(ValueError, "symlink target"):
                canonical_state_database(canonical, home)

    def test_hidden_and_external_models_are_not_core_bindings(self) -> None:
        hidden = [dict(self.items[0], hidden=True)]
        with self.assertRaisesRegex(ValueError, "hidden"):
            build_resolver_catalog(
                hidden,
                {"host-efficient": "efficient"},
                root_provider="openai",
                source_id="current-test-model-list",
                provenance_source="active-host-catalog",
                requested_thread_id="11111111-1111-1111-1111-111111111111",
                canonical_state_store_bound=True,
                model_provider_evidence="root-state-inferred",
            )
        external = [dict(self.items[0], model="claude-example")]
        with self.assertRaisesRegex(ValueError, "external Claude"):
            build_resolver_catalog(
                external,
                {"claude-example": "efficient"},
                root_provider="openai",
                source_id="current-test-model-list",
                provenance_source="active-host-catalog",
                requested_thread_id="11111111-1111-1111-1111-111111111111",
                canonical_state_store_bound=True,
                model_provider_evidence="root-state-inferred",
            )


if __name__ == "__main__":
    unittest.main()
