from contextlib import closing
from noetrium_platform.evidence.data.state.api import AggregateValue, AtomicMutation, StateBootstrapConflict, StateCorruptionError, StateVersionConflict
from noetrium_platform.evidence.data.state.runtime import SQLiteAtomicStateStore
import sqlite3
import tempfile
import unittest
from pathlib import Path
import hashlib

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactQuery, ArtifactRecord, ArtifactRegistryConflict, ArtifactRegistryCorruptionError
from noetrium_platform.evidence.artifact._sqlite_connection import rollback_artifact_writer
from noetrium_platform.evidence.artifact.catalog.providers import SQLiteArtifactRegistry
from noetrium_platform.evidence.data._sqlite_transaction import rollback_data_writer
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetQuery, DatasetRegistryConflict, DatasetRegistryCorruptionError, DatasetVersion
from noetrium_platform.evidence.data.dataset.providers import SQLiteDatasetRegistry
from noetrium_platform.evidence.data.fact.api import DurableFact, DurableFactConflict, DurableFactCorruptionError, FactCriticality
from noetrium_platform.evidence.data.fact.providers import SQLiteDurableFactStore
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE



class _RollbackFailureConnection:
    in_transaction = True

    def rollback(self) -> None:
        raise PermissionError("rollback blocked")


class SQLiteFailureCausalityV207Tests(unittest.TestCase):
    def test_data_rollback_failure_is_attached_to_primary_failure(self):
        primary = RuntimeError("primary data failure")
        rollback_data_writer(_RollbackFailureConnection(), primary)
        notes = getattr(primary, "__notes__", ())
        self.assertTrue(any("data sqlite rollback failed: PermissionError" in note for note in notes))

    def test_artifact_rollback_failure_is_attached_to_primary_failure(self):
        primary = RuntimeError("primary artifact failure")
        rollback_artifact_writer(_RollbackFailureConnection(), primary)
        notes = getattr(primary, "__notes__", ())
        self.assertTrue(any("artifact sqlite rollback failed: PermissionError" in note for note in notes))


class SQLiteAtomicStateV101Tests(unittest.TestCase):
    def _path(self, td): return Path(td) / "state.sqlite3"

    def test_state_contracts_reject_ambiguous_identity_and_versions(self):
        with self.assertRaises(ValueError):
            AggregateValue("", 0, "g0", "d0", {})
        with self.assertRaises(ValueError):
            AggregateValue("a", True, "g0", "d0", {})
        with self.assertRaises(ValueError):
            AtomicMutation("a", -1, "g0", "g1", "d1", {})
        with self.assertRaises(ValueError):
            AtomicMutation("a", 0, "g0", "", "d1", {})

    def test_commit_survives_store_restart(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._path(td)
            store=SQLiteAtomicStateStore(path,(AggregateValue("a",1,"g0","d0",{"x":0}),))
            out=store.commit_batch((AtomicMutation("a",1,"g0","g1","d1",{"x":1}),))
            self.assertEqual((out[0].version,out[0].generation),(2,"g1"))
            reopened=SQLiteAtomicStateStore(path)
            value=reopened.read("a")
            self.assertEqual((value.version,value.generation,value.payload),(2,"g1",{"x":1}))

    def test_batch_conflict_rolls_back_all_aggregates(self):
        with tempfile.TemporaryDirectory() as td:
            store=SQLiteAtomicStateStore(self._path(td),(
                AggregateValue("a",1,"g0","a0",{"x":0}),
                AggregateValue("b",1,"g0","b0",{"y":0}),
            ))
            with self.assertRaises(StateVersionConflict):
                store.commit_batch((
                    AtomicMutation("a",1,"g0","g1","a1",{"x":1}),
                    AtomicMutation("b",99,"g0","g1","b1",{"y":1}),
                ))
            self.assertEqual(store.read("a").generation,"g0")
            self.assertEqual(store.read("b").generation,"g0")

    def test_identical_bootstrap_is_idempotent_but_conflicting_bootstrap_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(td)
            initial = AggregateValue("a", 1, "g0", "d0", {"x": 0})
            SQLiteAtomicStateStore(path, (initial,))
            reopened = SQLiteAtomicStateStore(path, (initial,))
            self.assertEqual(reopened.read("a"), initial)
            with self.assertRaises(StateBootstrapConflict):
                SQLiteAtomicStateStore(
                    path,
                    (AggregateValue("a", 1, "g0", "different", {"x": 1}),),
                )


    def test_storage_checksum_detects_payload_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            path=self._path(td)
            store=SQLiteAtomicStateStore(path,(AggregateValue("a",1,"g0","d0",{"x":0}),))
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("UPDATE aggregates SET payload=? WHERE aggregate_id='a'",(b'{"x":999}',))
                conn.commit()
            with self.assertRaises(StateCorruptionError):
                store.read("a")

    def test_state_rejects_blob_generation_instead_of_coercing_it(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(td)
            store = SQLiteAtomicStateStore(
                path, (AggregateValue("a", 1, "g0", "d0", {"x": 0}),)
            )
            with closing(sqlite3.connect(path)) as conn:
                conn.execute(
                    "UPDATE aggregates SET generation=? WHERE aggregate_id='a'",
                    (sqlite3.Binary(b"g0"),),
                )
                conn.commit()
            with self.assertRaises(StateCorruptionError):
                store.read("a")

    def test_state_reader_connection_is_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(td)
            store = SQLiteAtomicStateStore(
                path, (AggregateValue("a", 1, "g0", "d0", {"x": 0}),)
            )
            with closing(store.backend.connect_reader()) as conn:
                self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("DELETE FROM aggregates")

    def test_state_rejects_non_finite_json_even_with_matching_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(td)
            store = SQLiteAtomicStateStore(
                path, (AggregateValue("a", 1, "g0", "d0", {"x": 0}),)
            )
            raw = b"NaN"
            checksum = hashlib.sha256(raw).hexdigest()
            with closing(sqlite3.connect(path)) as conn:
                conn.execute(
                    "UPDATE aggregates SET payload=?,payload_sha256=? WHERE aggregate_id='a'",
                    (raw, checksum),
                )
                conn.commit()
            with self.assertRaises(StateCorruptionError):
                store.read("a")

    def test_state_rejects_duplicate_json_keys_even_with_matching_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._path(td)
            store = SQLiteAtomicStateStore(
                path, (AggregateValue("a", 1, "g0", "d0", {"x": 0}),)
            )
            raw = b'{"x":1,"x":2}'
            checksum = hashlib.sha256(raw).hexdigest()
            with closing(sqlite3.connect(path)) as conn:
                conn.execute(
                    "UPDATE aggregates SET payload=?,payload_sha256=? WHERE aggregate_id='a'",
                    (raw, checksum),
                )
                conn.commit()
            with self.assertRaises(StateCorruptionError):
                store.read("a")


class DataArtifactDurabilityV207Tests(unittest.TestCase):
    @staticmethod
    def _sha(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _artifact(self, *, artifact_id: str = "artifact:one", digest: str | None = None) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=artifact_id,
            kind=ArtifactKind.RUNTIME,
            scope=PLATFORM_SCOPE,
            digest=digest or self._sha("artifact"),
            producer_component_id="test.component",
            metadata=(("source", "test"),),
        )

    def test_artifact_catalog_is_immutable_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            record = self._artifact()
            self.assertEqual(SQLiteArtifactRegistry(path).put(record), record)
            reopened = SQLiteArtifactRegistry(path)
            self.assertEqual(reopened.get(record.artifact_id), record)
            self.assertEqual(reopened.put(record), record)
            self.assertEqual(reopened.query(ArtifactQuery(kind=ArtifactKind.RUNTIME)), (record,))
            with self.assertRaises(ArtifactRegistryConflict):
                reopened.put(self._artifact(digest=self._sha("different")))

    def test_artifact_catalog_query_is_explicitly_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            store = SQLiteArtifactRegistry(path)
            rows = tuple(
                self._artifact(
                    artifact_id=f"artifact:{index:03d}",
                    digest=self._sha(f"artifact-{index}"),
                )
                for index in range(5)
            )
            for row in rows:
                store.put(row)
            self.assertEqual(store.query(ArtifactQuery(limit=2)), rows[:2])
            with self.assertRaises(ValueError):
                ArtifactQuery(limit=0)
            with self.assertRaises(ValueError):
                ArtifactQuery(limit=True)
            with self.assertRaises(ValueError):
                ArtifactQuery(limit=10_001)

    def test_artifact_digest_identity_requires_lowercase_sha256(self):
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            self._artifact(digest="not-a-digest")

    def test_artifact_catalog_reader_connection_is_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            store = SQLiteArtifactRegistry(path)
            store.put(self._artifact())
            with closing(store._connect_reader()) as db:
                self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM artifacts")

    def test_artifact_catalog_detects_record_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            record = self._artifact()
            SQLiteArtifactRegistry(path).put(record)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE artifacts SET producer_component_id=? WHERE artifact_id=?",
                    ("tampered.component", record.artifact_id),
                )
                db.commit()
            with self.assertRaises(ArtifactRegistryCorruptionError):
                SQLiteArtifactRegistry(path).get(record.artifact_id)

    def test_artifact_catalog_rejects_legacy_string_lineage_members(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            record = self._artifact()
            SQLiteArtifactRegistry(path).put(record)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE artifacts SET lineage_json=? WHERE artifact_id=?",
                    ('["artifact:legacy"]', record.artifact_id),
                )
                db.commit()
            with self.assertRaises(ArtifactRegistryCorruptionError):
                SQLiteArtifactRegistry(path).get(record.artifact_id)

    def test_artifact_catalog_rejects_blob_scalar_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "artifacts.sqlite3"
            record = self._artifact()
            store = SQLiteArtifactRegistry(path)
            store.put(record)
            coerced = ArtifactRecord(
                artifact_id=record.artifact_id, kind=record.kind, scope=record.scope,
                digest=record.digest, producer_component_id=str(b"blob-component"),
                metadata=record.metadata,
            )
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE artifacts SET producer_component_id=?,record_sha256=? WHERE artifact_id=?",
                    (
                        sqlite3.Binary(b"blob-component"),
                        store._record_digest(coerced),
                        record.artifact_id,
                    ),
                )
                db.commit()
            with self.assertRaises(ArtifactRegistryCorruptionError):
                store.get(record.artifact_id)

    def test_artifact_catalog_rejects_legacy_location_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy-artifacts.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE artifacts("
                    "artifact_id TEXT PRIMARY KEY,kind TEXT NOT NULL,scope_kind TEXT NOT NULL,"
                    "scope_id TEXT NOT NULL,digest TEXT NOT NULL,location TEXT NOT NULL,"
                    "producer_component_id TEXT NOT NULL,producer_operation_id TEXT,"
                    "media_type TEXT NOT NULL,lineage_json TEXT NOT NULL,"
                    "declared_retention TEXT NOT NULL,metadata_json TEXT NOT NULL,"
                    "record_sha256 TEXT NOT NULL)"
                )
                db.commit()
            with self.assertRaisesRegex(ArtifactRegistryCorruptionError, "unsupported artifact catalog schema"):
                SQLiteArtifactRegistry(path)

    def _dataset(
        self,
        *,
        version: str = "v1",
        content_sha256: str | None = None,
        schema_ref: str | None = None,
    ) -> DatasetVersion:
        return DatasetVersion(
            identity=DatasetIdentity("dataset", version),
            scope=PLATFORM_SCOPE,
            content_sha256=content_sha256 or self._sha("dataset"),
            schema_ref=schema_ref,
            parent_versions=(DatasetIdentity("source", "v1"),),
            tags=("training", "verified"),
            metadata=(("format", "jsonl"),),
        )

    def test_dataset_registry_persists_versions_and_indexes_tags(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            record = self._dataset()
            self.assertEqual(SQLiteDatasetRegistry(path).register(record), record)
            reopened = SQLiteDatasetRegistry(path)
            self.assertEqual(reopened.get(record.identity), record)
            self.assertEqual(reopened.register(record), record)
            self.assertEqual(reopened.query(DatasetQuery(tag="verified")), (record,))
            self.assertFalse(hasattr(record, "location"))
            with self.assertRaises(DatasetRegistryConflict):
                reopened.register(self._dataset(content_sha256=self._sha("different")))

    def test_dataset_registry_query_is_explicitly_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            store = SQLiteDatasetRegistry(path)
            rows = tuple(
                self._dataset(version=f"v{index:03d}")
                for index in range(5)
            )
            for row in rows:
                store.register(row)
            self.assertEqual(store.query(DatasetQuery(limit=2)), rows[:2])
            with self.assertRaises(ValueError):
                DatasetQuery(limit=0)
            with self.assertRaises(ValueError):
                DatasetQuery(limit=True)
            with self.assertRaises(ValueError):
                DatasetQuery(limit=10_001)

    def test_dataset_reader_connection_is_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            store = SQLiteDatasetRegistry(path)
            store.register(self._dataset())
            with closing(store._connect_reader()) as db:
                self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM datasets")

    def test_dataset_registry_detects_record_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            record = self._dataset()
            SQLiteDatasetRegistry(path).register(record)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE datasets SET content_sha256=? WHERE dataset_key=?",
                    ("0" * 64, record.identity.key),
                )
                db.commit()
            with self.assertRaises(DatasetRegistryCorruptionError):
                SQLiteDatasetRegistry(path).get(record.identity)

    def test_dataset_registry_rejects_non_string_collection_members(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            record = self._dataset()
            SQLiteDatasetRegistry(path).register(record)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE datasets SET tags_json='[123]' WHERE dataset_key=?",
                    (record.identity.key,),
                )
                db.commit()
            with self.assertRaises(DatasetRegistryCorruptionError):
                SQLiteDatasetRegistry(path).get(record.identity)

    def test_dataset_registry_rejects_blob_scalar_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "datasets.sqlite3"
            record = self._dataset()
            store = SQLiteDatasetRegistry(path)
            store.register(record)
            coerced = self._dataset(schema_ref=str(b"schema:blob"))
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE datasets SET schema_ref=?,record_sha256=? WHERE dataset_key=?",
                    (
                        sqlite3.Binary(b"schema:blob"),
                        store._record_digest(coerced),
                        record.identity.key,
                    ),
                )
                db.commit()
            with self.assertRaises(DatasetRegistryCorruptionError):
                store.get(record.identity)

    def test_dataset_registry_rejects_legacy_location_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy-datasets.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE datasets("
                    "dataset_key TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,version TEXT NOT NULL,"
                    "scope_kind TEXT NOT NULL,scope_id TEXT NOT NULL,digest TEXT NOT NULL,"
                    "location TEXT NOT NULL,schema_ref TEXT,parents_json TEXT NOT NULL,"
                    "tags_json TEXT NOT NULL,metadata_json TEXT NOT NULL,record_sha256 TEXT NOT NULL)"
                )
                db.commit()
            with self.assertRaisesRegex(DatasetRegistryCorruptionError, "unsupported dataset registry schema"):
                SQLiteDatasetRegistry(path)

    def test_durable_fact_validates_tail_artifact_and_state_references(self):
        with self.assertRaisesRegex(ValueError, "artifact_refs"):
            DurableFact(
                "fact", "project.fact", "v1", FactCriticality.REQUIRED, {},
                artifact_refs=("artifact:one", "artifact:two", ""),
            )
        with self.assertRaisesRegex(ValueError, "state_refs"):
            DurableFact(
                "fact", "project.fact", "v1", FactCriticality.REQUIRED, {},
                state_refs=("state:one", "state:two", ""),
            )

    @staticmethod
    def _fact(*, status: str = "ok") -> DurableFact:
        return DurableFact(
            fact_id="fact:one",
            fact_type="test.fact",
            schema_version="1",
            criticality=FactCriticality.REQUIRED,
            payload={"status": status, "count": 1},
            artifact_refs=("artifact:one",),
            state_refs=("state:one",),
        )

    def test_durable_fact_store_is_append_only_idempotent_and_reopens(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            fact = self._fact()
            first = SQLiteDurableFactStore(path)
            receipt = first.append(fact)
            self.assertEqual(receipt.sequence, 1)
            reopened = SQLiteDurableFactStore(path)
            self.assertEqual(reopened.get(fact.fact_id), fact)
            self.assertEqual(reopened.append(fact), receipt)
            self.assertEqual(reopened.count(), 1)
            with self.assertRaises(DurableFactConflict):
                reopened.append(self._fact(status="changed"))

    def test_durable_fact_reader_connection_is_sqlite_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            store = SQLiteDurableFactStore(path)
            store.append(self._fact())
            with closing(store._connect_reader()) as db:
                self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM durable_facts")

    def test_durable_fact_store_detects_payload_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            store = SQLiteDurableFactStore(path)
            fact = self._fact()
            store.append(fact)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE durable_facts SET payload_json=? WHERE fact_id=?",
                    ('{"count":1,"status":"tampered"}', fact.fact_id),
                )
                db.commit()
            with self.assertRaisesRegex(DurableFactCorruptionError, "integrity mismatch"):
                store.get(fact.fact_id)

    def test_durable_fact_store_rejects_non_string_reference_members(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            fact = self._fact()
            SQLiteDurableFactStore(path).append(fact)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE durable_facts SET artifact_refs_json='[123]' WHERE fact_id=?",
                    (fact.fact_id,),
                )
                db.commit()
            with self.assertRaises(DurableFactCorruptionError):
                SQLiteDurableFactStore(path).get(fact.fact_id)

    def test_durable_fact_rejects_blob_scalar_even_with_matching_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            fact = self._fact()
            store = SQLiteDurableFactStore(path)
            store.append(fact)
            coerced = DurableFact(
                fact_id=fact.fact_id,
                fact_type=str(b"test.fact"),
                schema_version=fact.schema_version,
                criticality=fact.criticality,
                payload=fact.payload,
                artifact_refs=fact.artifact_refs,
                state_refs=fact.state_refs,
            )
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE durable_facts SET fact_type=?,record_sha256=? WHERE fact_id=?",
                    (sqlite3.Binary(b"test.fact"), store._digest(coerced), fact.fact_id),
                )
                db.commit()
            with self.assertRaises(DurableFactCorruptionError):
                store.get(fact.fact_id)

    def test_durable_fact_rejects_non_finite_persisted_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            fact = self._fact()
            store = SQLiteDurableFactStore(path)
            store.append(fact)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE durable_facts SET payload_json=? WHERE fact_id=?",
                    ('{"score":NaN}', fact.fact_id),
                )
                db.commit()
            with self.assertRaises(DurableFactCorruptionError):
                store.get(fact.fact_id)

    def test_durable_fact_rejects_duplicate_persisted_json_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "facts.sqlite3"
            fact = self._fact()
            store = SQLiteDurableFactStore(path)
            store.append(fact)
            with closing(sqlite3.connect(path)) as db:
                db.execute(
                    "UPDATE durable_facts SET payload_json=? WHERE fact_id=?",
                    ('{"score":1,"score":2}', fact.fact_id),
                )
                db.commit()
            with self.assertRaises(DurableFactCorruptionError):
                store.get(fact.fact_id)


if __name__ == "__main__":
    unittest.main()
