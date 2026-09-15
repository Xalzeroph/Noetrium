from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.composition.semantic_retrieval import (
    SemanticProjectionEntry,
    SemanticProjectionSnapshot,
    SemanticRetrievalEngine,
    SemanticSimilarityMetric,
    SemanticSimilarityQuery,
    SemanticSourceReference,
)
from research.reproductions.generative_agents_memory import (
    GenerativeMemoryNode,
    score_memories,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot() -> SemanticProjectionSnapshot:
    return SemanticProjectionSnapshot(
        "agent-memory.semantic",
        "prototype-v1",
        _digest("source-cut:7"),
        _digest("embedding-model:revision"),
        (
            SemanticProjectionEntry(SemanticSourceReference("memory", "a", _digest("alpha")), (1.0, 0.0)),
            SemanticProjectionEntry(SemanticSourceReference("memory", "b", _digest("beta")), (0.0, 1.0)),
            SemanticProjectionEntry(SemanticSourceReference("memory", "c", _digest("gamma")), (0.8, 0.2)),
        ),
    )


def test_semantic_projection_contains_refs_vectors_and_provenance_not_source_text() -> None:
    snapshot = _snapshot()
    assert snapshot.dimension == 2
    assert snapshot.source_cut_digest == _digest("source-cut:7")
    assert snapshot.embedding_model_digest == _digest("embedding-model:revision")
    assert all(not hasattr(entry, "content") for entry in snapshot.entries)
    assert snapshot == _snapshot()
    assert snapshot.projection_digest == _snapshot().projection_digest


def test_cosine_projection_supplies_generative_agents_relevance_component() -> None:
    snapshot = _snapshot()
    engine = SemanticRetrievalEngine()
    result = engine.query(
        snapshot,
        SemanticSimilarityQuery((1.0, 0.0), SemanticSimilarityMetric.COSINE_SIMILARITY, limit=3),
    )
    raw = {match.reference.record_id: match.score for match in result.matches}
    method = score_memories(
        (
            GenerativeMemoryNode("a", (1.0, 0.0), 1.0, 1),
            GenerativeMemoryNode("b", (0.0, 1.0), 1.0, 2),
            GenerativeMemoryNode("c", (0.8, 0.2), 1.0, 3),
        ),
        focal_embedding=(1.0, 0.0),
    )
    relevance = {row.node.node_id: row.relevance for row in method}
    low, high = min(raw.values()), max(raw.values())
    expected = {key: (value - low) / (high - low) for key, value in raw.items()}
    assert relevance == pytest.approx(expected)


def test_squared_l2_projection_matches_classic_memgpt_archival_neighbor_semantics() -> None:
    snapshot = _snapshot()
    result = SemanticRetrievalEngine().query(
        snapshot,
        SemanticSimilarityQuery((0.82, 0.18), SemanticSimilarityMetric.SQUARED_L2_DISTANCE, limit=3),
    )
    assert [row.reference.record_id for row in result.matches] == ["c", "a", "b"]
    assert [row.rank for row in result.matches] == [1, 2, 3]
    assert result.candidate_count == 3
    assert result.source_cut_digest == snapshot.source_cut_digest


def test_squared_l2_ties_use_canonical_source_reference_order() -> None:
    snapshot = _snapshot()
    result = SemanticRetrievalEngine().query(
        snapshot,
        SemanticSimilarityQuery((0.9, 0.1), SemanticSimilarityMetric.SQUARED_L2_DISTANCE, limit=3),
    )
    assert [row.reference.record_id for row in result.matches] == ["a", "c", "b"]


def test_candidate_queries_fail_closed_on_projection_drift() -> None:
    snapshot = _snapshot()
    absent = SemanticSourceReference("memory", "missing", _digest("missing"))
    with pytest.raises(ValueError, match="absent from the pinned projection"):
        SemanticRetrievalEngine().query(
            snapshot,
            SemanticSimilarityQuery(
                (1.0, 0.0),
                candidates=(snapshot.entries[0].reference, absent),
            ),
        )


def test_cosine_rejects_zero_vectors_but_l2_remains_defined() -> None:
    zero_snapshot = SemanticProjectionSnapshot(
        "zero.semantic",
        "prototype-v1",
        _digest("cut"),
        _digest("model"),
        (SemanticProjectionEntry(SemanticSourceReference("memory", "zero", _digest("zero")), (0.0, 0.0)),),
    )
    engine = SemanticRetrievalEngine()
    with pytest.raises(ValueError, match="zero vectors"):
        engine.query(zero_snapshot, SemanticSimilarityQuery((1.0, 0.0)))
    l2 = engine.query(
        zero_snapshot,
        SemanticSimilarityQuery((1.0, 0.0), SemanticSimilarityMetric.SQUARED_L2_DISTANCE),
    )
    assert l2.matches[0].score == 1.0
