from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.evidence.data.projection.api import (
    SemanticProjectionEntry,
    SemanticProjectionSnapshot,
    SemanticSourceReference,
)
from noetrium_platform.evidence.data.query.api import SemanticSimilarityMetric
from noetrium_platform.evidence.data.query.composition import (
    SemanticSimilarityCapabilityBinding,
    semantic_similarity_capability_payload,
)
from noetrium_platform.evidence.data.query.runtime import SemanticRetrievalEngine
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot() -> SemanticProjectionSnapshot:
    return SemanticProjectionSnapshot(
        "capability-catalog.semantic",
        "paper-cut-v1",
        _digest("capability-source-cut"),
        _digest("retriever-model"),
        (
            SemanticProjectionEntry(
                SemanticSourceReference(
                    "capability-catalog",
                    "weather.current",
                    _digest("weather"),
                ),
                (1.0, 0.0),
            ),
            SemanticProjectionEntry(
                SemanticSourceReference(
                    "capability-catalog",
                    "calendar.create",
                    _digest("calendar"),
                ),
                (0.0, 1.0),
            ),
        ),
    )


def test_semantic_similarity_capability_binds_query_to_immutable_projection_cut() -> None:
    snapshot = _snapshot()
    binding = SemanticSimilarityCapabilityBinding(
        snapshot,
        SemanticRetrievalEngine(),
    )
    descriptor = binding.describe("data.semantic-similarity")
    assert descriptor.effect_class is EffectClass.PURE
    assert descriptor.deterministic is True

    payload = semantic_similarity_capability_payload(
        snapshot=snapshot,
        vector=(0.95, 0.05),
        metric=SemanticSimilarityMetric.COSINE_SIMILARITY,
        limit=1,
    )
    result = binding.invoke(
        CapabilityRequest(
            "data.semantic-similarity",
            payload,
            ExecutionContext("run", "trace", "span", task_id="task:1"),
        )
    )
    assert result.payload["projection_digest"] == snapshot.projection_digest
    assert result.payload["source_cut_digest"] == snapshot.source_cut_digest
    assert result.payload["embedding_model_digest"] == snapshot.embedding_model_digest
    assert result.payload["candidate_count"] == 2
    assert result.payload["matches"] == (
        {
            "source_id": "capability-catalog",
            "record_id": "weather.current",
            "content_digest": _digest("weather"),
            "score": pytest.approx(result.payload["matches"][0]["score"]),
            "rank": 1,
        },
    )
    assert result.request_digest is not None


def test_semantic_similarity_capability_rejects_projection_drift() -> None:
    snapshot = _snapshot()
    binding = SemanticSimilarityCapabilityBinding(
        snapshot,
        SemanticRetrievalEngine(),
    )
    payload = semantic_similarity_capability_payload(
        snapshot=snapshot,
        vector=(1.0, 0.0),
    )
    payload["projection_digest"] = _digest("other-projection")

    with pytest.raises(ValueError, match="projection identity drift"):
        binding.invoke(
            CapabilityRequest(
                "data.semantic-similarity",
                payload,
                ExecutionContext("run", "trace", "span", task_id="task:1"),
            )
        )


def test_semantic_similarity_capability_rejects_embedding_model_drift() -> None:
    snapshot = _snapshot()
    binding = SemanticSimilarityCapabilityBinding(
        snapshot,
        SemanticRetrievalEngine(),
    )
    payload = semantic_similarity_capability_payload(
        snapshot=snapshot,
        vector=(1.0, 0.0),
    )
    payload["embedding_model_digest"] = _digest("other-model")

    with pytest.raises(ValueError, match="embedding model identity drift"):
        binding.invoke(
            CapabilityRequest(
                "data.semantic-similarity",
                payload,
                ExecutionContext("run", "trace", "span", task_id="task:1"),
            )
        )
