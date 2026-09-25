from __future__ import annotations

from research.reproductions.generative_agents_memory import (
    GENERATIVE_AGENTS_RETRIEVAL_FIDELITY,
    GenerativeMemoryNode,
    GenerativeRetrievalWeights,
    retrieve_top,
    score_memories,
)


def test_generative_agents_retrieval_fidelity_is_pinned() -> None:
    fidelity = GENERATIVE_AGENTS_RETRIEVAL_FIDELITY
    assert fidelity.audited_commit == "fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4"
    assert fidelity.default_retrieval_count == 30
    assert (
        fidelity.global_recency_weight,
        fidelity.global_relevance_weight,
        fidelity.global_importance_weight,
    ) == (0.5, 3.0, 2.0)
    assert fidelity.relevance_metric == "cosine_similarity"
    assert fidelity.update_last_accessed_on_retrieval is True


def test_method_scoring_combines_normalized_recency_relevance_importance() -> None:
    nodes = (
        GenerativeMemoryNode("a", (1.0, 0.0), 1.0, 1),
        GenerativeMemoryNode("b", (0.0, 1.0), 10.0, 2),
        GenerativeMemoryNode("c", (0.8, 0.2), 5.0, 3),
    )
    scores = score_memories(
        nodes,
        focal_embedding=(1.0, 0.0),
        weights=GenerativeRetrievalWeights(recency=1.0, relevance=1.0, importance=1.0, recency_decay=0.9),
    )
    by_id = {row.node.node_id: row for row in scores}
    assert by_id["a"].recency == 1.0
    assert by_id["a"].relevance == 1.0
    assert by_id["a"].importance == 0.0
    assert by_id["b"].relevance == 0.0
    assert by_id["b"].importance == 1.0
    assert scores[0].node.node_id in {"a", "c"}


def test_retrieval_limit_is_method_semantics_not_storage_policy() -> None:
    nodes = tuple(
        GenerativeMemoryNode(str(index), (1.0, float(index + 1)), float(index), index + 1)
        for index in range(6)
    )
    top = retrieve_top(nodes, focal_embedding=(1.0, 1.0), limit=2)
    assert len(top) == 2
    assert len(nodes) == 6


def test_constant_component_scores_normalize_to_midpoint() -> None:
    nodes = (
        GenerativeMemoryNode("a", (1.0, 0.0), 5.0, 1),
        GenerativeMemoryNode("b", (1.0, 0.0), 5.0, 1),
    )
    scores = score_memories(nodes, focal_embedding=(1.0, 0.0))
    assert all(row.recency == 0.5 for row in scores)
    assert all(row.relevance == 0.5 for row in scores)
    assert all(row.importance == 0.5 for row in scores)
