from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.catalog.api import ArtifactRetention
from noetrium_platform.evidence.artifact.lineage.relation.api import (
    ArtifactLineageCorruptionError,
    ArtifactLineageCycle,
    ArtifactLineageEdge,
)
from noetrium_platform.evidence.artifact.lineage.relation.providers import SQLiteArtifactLineageStore
from noetrium_platform.evidence.artifact.reference.api import (
    ArtifactReferenceConflict,
    ArtifactReferenceCorruptionError,
)
from noetrium_platform.evidence.artifact.reference.providers import SQLiteArtifactReferenceStore
from noetrium_platform.evidence.artifact.retention.api import (
    ArtifactRetentionConflict,
    ArtifactRetentionCorruptionError,
)
from noetrium_platform.evidence.artifact.retention.providers import SQLiteArtifactRetentionStore
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


def _content(artifact_id: str, char: str) -> ArtifactContentIdentity:
    return ArtifactContentIdentity(artifact_id, char * 64)


def test_lineage_is_append_only_restarts_and_rejects_cycles(tmp_path: Path) -> None:
    path = tmp_path / "lineage.sqlite3"
    first = SQLiteArtifactLineageStore(path)
    ab = ArtifactLineageEdge(_content("artifact:a", "a"), _content("artifact:b", "b"), "derived_from", (_content("evidence:ab", "d"),))
    bc = ArtifactLineageEdge(_content("artifact:b", "b"), _content("artifact:c", "c"), "derived_from", (_content("evidence:bc", "e"),))
    assert first.add(ab) == ab
    assert first.add(bc) == bc

    reopened = SQLiteArtifactLineageStore(path)
    assert reopened.parents(_content("artifact:b", "b")) == (ab,)
    assert reopened.children(_content("artifact:b", "b")) == (bc,)
    assert reopened.add(ab) == ab
    with pytest.raises(ArtifactLineageCycle):
        reopened.add(ArtifactLineageEdge(_content("artifact:c", "c"), _content("artifact:a", "a"), "derived_from"))


def test_lineage_reader_connection_is_sqlite_read_only(tmp_path: Path) -> None:
    path = tmp_path / "lineage.sqlite3"
    store = SQLiteArtifactLineageStore(path)
    store.add(ArtifactLineageEdge(_content("artifact:a", "a"), _content("artifact:b", "b"), "derived_from"))
    with closing(store._connect_reader()) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM artifact_lineage_edges")


def test_lineage_detects_stored_edge_tamper(tmp_path: Path) -> None:
    path = tmp_path / "lineage.sqlite3"
    edge = ArtifactLineageEdge(_content("artifact:a", "a"), _content("artifact:b", "b"), "derived_from")
    SQLiteArtifactLineageStore(path).add(edge)
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_lineage_edges SET relation_type=? WHERE edge_id=?",
            ("tampered", edge.edge_id),
        )
        db.commit()
    with pytest.raises(ArtifactLineageCorruptionError):
        SQLiteArtifactLineageStore(path).children(_content("artifact:a", "a"))


def test_lineage_rejects_non_string_persisted_evidence_refs(tmp_path: Path) -> None:
    path = tmp_path / "lineage.sqlite3"
    edge = ArtifactLineageEdge(_content("artifact:a", "a"), _content("artifact:b", "b"), "derived_from", (_content("evidence:one", "d"),))
    SQLiteArtifactLineageStore(path).add(edge)
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_lineage_edges SET evidence_refs_json='[123]' WHERE edge_id=?",
            (edge.edge_id,),
        )
        db.commit()
    with pytest.raises(ArtifactLineageCorruptionError):
        SQLiteArtifactLineageStore(path).children(_content("artifact:a", "a"))


def test_lineage_rejects_blob_relation_even_with_matching_edge_identity(tmp_path: Path) -> None:
    path = tmp_path / "lineage.sqlite3"
    edge = ArtifactLineageEdge(_content("artifact:a", "a"), _content("artifact:b", "b"), "derived_from")
    store = SQLiteArtifactLineageStore(path)
    store.add(edge)
    coerced = ArtifactLineageEdge(
        edge.parent,
        edge.child,
        str(b"derived_from"),
        edge.evidence_refs,
    )
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_lineage_edges SET relation_type=?,edge_id=? WHERE edge_id=?",
            (sqlite3.Binary(b"derived_from"), coerced.edge_id, edge.edge_id),
        )
        db.commit()
    with pytest.raises(ArtifactLineageCorruptionError):
        store.children(_content("artifact:a", "a"))


def test_reference_cas_is_restart_safe_and_rejects_stale_generation(tmp_path: Path) -> None:
    path = tmp_path / "reference.sqlite3"
    store = SQLiteArtifactReferenceStore(path)
    created = store.compare_and_set(
        "latest-model", PLATFORM_SCOPE, expected_generation=0, artifact_id="artifact:v1"
    )
    assert created.generation == 1

    reopened = SQLiteArtifactReferenceStore(path)
    assert reopened.resolve("latest-model", PLATFORM_SCOPE) == created
    assert reopened.compare_and_set(
        "latest-model", PLATFORM_SCOPE, expected_generation=1, artifact_id="artifact:v1"
    ) == created
    updated = reopened.compare_and_set(
        "latest-model", PLATFORM_SCOPE, expected_generation=1, artifact_id="artifact:v2"
    )
    assert updated.generation == 2
    with pytest.raises(ArtifactReferenceConflict):
        reopened.compare_and_set(
            "latest-model", PLATFORM_SCOPE, expected_generation=1, artifact_id="artifact:v3"
        )


def test_reference_reader_connection_is_sqlite_read_only(tmp_path: Path) -> None:
    path = tmp_path / "reference.sqlite3"
    store = SQLiteArtifactReferenceStore(path)
    store.compare_and_set("latest", PLATFORM_SCOPE, expected_generation=0, artifact_id="artifact:v1")
    with closing(store._connect_reader()) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM artifact_references")


def test_reference_alias_identity_is_scoped(tmp_path: Path) -> None:
    path = tmp_path / "reference.sqlite3"
    store = SQLiteArtifactReferenceStore(path)
    scope_a = ScopeIdentity(ScopeKind.PROJECT, "project-a")
    scope_b = ScopeIdentity(ScopeKind.PROJECT, "project-b")

    a = store.compare_and_set("latest", scope_a, expected_generation=0, artifact_id="artifact:a")
    b = store.compare_and_set("latest", scope_b, expected_generation=0, artifact_id="artifact:b")

    assert a.reference_id == b.reference_id == "latest"
    assert a.scope == scope_a
    assert b.scope == scope_b
    assert store.resolve("latest", scope_a).artifact_id == "artifact:a"
    assert store.resolve("latest", scope_b).artifact_id == "artifact:b"


def test_reference_detects_row_tamper_before_cas(tmp_path: Path) -> None:
    path = tmp_path / "reference.sqlite3"
    store = SQLiteArtifactReferenceStore(path)
    store.compare_and_set("latest", PLATFORM_SCOPE, expected_generation=0, artifact_id="artifact:v1")
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE artifact_references SET artifact_id='artifact:tampered' WHERE reference_id='latest'")
        db.commit()
    corrupted = SQLiteArtifactReferenceStore(path)
    with pytest.raises(ArtifactReferenceCorruptionError):
        corrupted.resolve("latest", PLATFORM_SCOPE)
    with pytest.raises(ArtifactReferenceCorruptionError):
        corrupted.compare_and_set(
            "latest", PLATFORM_SCOPE, expected_generation=1, artifact_id="artifact:v2"
        )


def test_reference_rejects_real_generation_instead_of_truncating(tmp_path: Path) -> None:
    path = tmp_path / "reference.sqlite3"
    store = SQLiteArtifactReferenceStore(path)
    store.compare_and_set(
        "latest", PLATFORM_SCOPE, expected_generation=0, artifact_id="artifact:v1"
    )
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_references SET generation=1.5 WHERE reference_id='latest'"
        )
        db.commit()
    with pytest.raises(ArtifactReferenceCorruptionError):
        store.resolve("latest", PLATFORM_SCOPE)


def test_retention_cas_is_single_mutable_policy_authority(tmp_path: Path) -> None:
    path = tmp_path / "retention.sqlite3"
    store = SQLiteArtifactRetentionStore(path)
    created = store.compare_and_set(
        "artifact:a",
        expected_generation=0,
        retention=ArtifactRetention.RUN,
        pinned=False,
        reason_refs=("run:1",),
    )
    assert created.generation == 1

    reopened = SQLiteArtifactRetentionStore(path)
    assert reopened.get("artifact:a") == created
    assert reopened.compare_and_set(
        "artifact:a",
        expected_generation=1,
        retention=ArtifactRetention.RUN,
        pinned=False,
        reason_refs=("run:1",),
    ) == created
    updated = reopened.compare_and_set(
        "artifact:a",
        expected_generation=1,
        retention=ArtifactRetention.PERMANENT,
        pinned=True,
        reason_refs=("release:1",),
    )
    assert updated.generation == 2
    with pytest.raises(ArtifactRetentionConflict):
        reopened.compare_and_set(
            "artifact:a",
            expected_generation=1,
            retention=ArtifactRetention.PROJECT,
            pinned=False,
        )


def test_retention_reader_connection_is_sqlite_read_only(tmp_path: Path) -> None:
    path = tmp_path / "retention.sqlite3"
    store = SQLiteArtifactRetentionStore(path)
    store.compare_and_set("artifact:a", expected_generation=0, retention=ArtifactRetention.RUN, pinned=False)
    with closing(store._connect_reader()) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM artifact_retention")


def test_retention_rejects_non_string_persisted_reason_refs(tmp_path: Path) -> None:
    path = tmp_path / "retention.sqlite3"
    store = SQLiteArtifactRetentionStore(path)
    store.compare_and_set(
        "artifact:a",
        expected_generation=0,
        retention=ArtifactRetention.RUN,
        pinned=False,
        reason_refs=("run:1",),
    )
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_retention SET reason_refs_json='[123]' WHERE artifact_id='artifact:a'"
        )
        db.commit()
    with pytest.raises(ArtifactRetentionCorruptionError):
        SQLiteArtifactRetentionStore(path).get("artifact:a")


def test_retention_detects_row_tamper_before_policy_update(tmp_path: Path) -> None:
    path = tmp_path / "retention.sqlite3"
    store = SQLiteArtifactRetentionStore(path)
    store.compare_and_set(
        "artifact:a", expected_generation=0, retention=ArtifactRetention.RUN, pinned=False
    )
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE artifact_retention SET retention='release' WHERE artifact_id='artifact:a'")
        db.commit()
    corrupted = SQLiteArtifactRetentionStore(path)
    with pytest.raises(ArtifactRetentionCorruptionError):
        corrupted.get("artifact:a")
    with pytest.raises(ArtifactRetentionCorruptionError):
        corrupted.compare_and_set(
            "artifact:a",
            expected_generation=1,
            retention=ArtifactRetention.PERMANENT,
            pinned=True,
        )


def test_retention_rejects_real_generation_instead_of_truncating(tmp_path: Path) -> None:
    path = tmp_path / "retention.sqlite3"
    store = SQLiteArtifactRetentionStore(path)
    store.compare_and_set(
        "artifact:a", expected_generation=0, retention=ArtifactRetention.RUN, pinned=False
    )
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "UPDATE artifact_retention SET generation=1.5 WHERE artifact_id='artifact:a'"
        )
        db.commit()
    with pytest.raises(ArtifactRetentionCorruptionError):
        store.get("artifact:a")


def test_lineage_queries_bind_full_content_identity_not_artifact_id_only(tmp_path: Path) -> None:
    path = tmp_path / "lineage-content-identity.sqlite3"
    store = SQLiteArtifactLineageStore(path)
    parent_v1 = _content("artifact:parent", "a")
    parent_v2 = _content("artifact:parent", "b")
    child_v1 = _content("artifact:child-v1", "c")
    child_v2 = _content("artifact:child-v2", "d")
    edge_v1 = ArtifactLineageEdge(parent_v1, child_v1, "derived_from")
    edge_v2 = ArtifactLineageEdge(parent_v2, child_v2, "derived_from")
    store.add(edge_v1)
    store.add(edge_v2)
    assert store.children(parent_v1) == (edge_v1,)
    assert store.children(parent_v2) == (edge_v2,)
    assert store.parents(child_v1) == (edge_v1,)
    assert store.parents(child_v2) == (edge_v2,)


def test_lineage_contract_rejects_alias_strings_self_edges_and_unordered_evidence() -> None:
    parent = _content("artifact:a", "a")
    child = _content("artifact:b", "b")
    with pytest.raises(TypeError, match="parent must be ArtifactContentIdentity"):
        ArtifactLineageEdge("artifact:a", child, "derived_from")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="self-edge"):
        ArtifactLineageEdge(parent, _content("artifact:a", "c"), "derived_from")
    evidence_a = _content("evidence:a", "d")
    evidence_b = _content("evidence:b", "e")
    with pytest.raises(TypeError, match="evidence refs must be ArtifactContentIdentity"):
        ArtifactLineageEdge(parent, child, "derived_from", ("evidence:a",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        ArtifactLineageEdge(parent, child, "derived_from", (evidence_a, evidence_a))
    with pytest.raises(ValueError, match="canonically ordered"):
        ArtifactLineageEdge(parent, child, "derived_from", (evidence_b, evidence_a))


def test_lineage_rejects_legacy_artifact_id_only_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy-lineage.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE artifact_lineage_edges("
            "edge_id TEXT PRIMARY KEY,parent_artifact_id TEXT NOT NULL,"
            "child_artifact_id TEXT NOT NULL,relation_type TEXT NOT NULL,"
            "evidence_refs_json TEXT NOT NULL)"
        )
        db.commit()
    with pytest.raises(ArtifactLineageCorruptionError, match="unsupported artifact lineage schema"):
        SQLiteArtifactLineageStore(path)
