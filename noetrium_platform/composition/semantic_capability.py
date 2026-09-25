from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.evidence.data.projection.api import (
    SemanticProjectionSnapshot,
    SemanticSourceReference,
)
from noetrium_platform.evidence.data.query.api import (
    SemanticSimilarityMetric,
    SemanticSimilarityQuery,
    SemanticSimilarityQueryPort,
    SemanticSimilarityResult,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonInput,
    JsonValue,
    require_sha256,
)

_REQUEST_SCHEMA = "noetrium.data.semantic-similarity-capability.request.v1"
_RESULT_SCHEMA = "noetrium.data.semantic-similarity-capability.result.v1"


def semantic_similarity_capability_payload(
    *,
    snapshot: SemanticProjectionSnapshot,
    vector: Sequence[float],
    metric: SemanticSimilarityMetric = SemanticSimilarityMetric.COSINE_SIMILARITY,
    limit: int = 10,
    candidates: Sequence[SemanticSourceReference] = (),
) -> dict[str, JsonInput]:
    if not isinstance(snapshot, SemanticProjectionSnapshot):
        raise TypeError("semantic capability payload requires SemanticProjectionSnapshot")
    if not isinstance(metric, SemanticSimilarityMetric):
        raise TypeError("semantic capability metric must be SemanticSimilarityMetric")
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
        raise TypeError("semantic capability vector must be a numeric sequence")
    if not isinstance(candidates, Sequence) or isinstance(
        candidates, (str, bytes, bytearray)
    ):
        raise TypeError("semantic capability candidates must be a sequence")
    return {
        "projection_digest": snapshot.projection_digest,
        "source_cut_digest": snapshot.source_cut_digest,
        "embedding_model_digest": snapshot.embedding_model_digest,
        "vector": tuple(float(value) for value in vector),
        "metric": metric.value,
        "limit": limit,
        "candidates": tuple(
            {
                "source_id": reference.source_id,
                "record_id": reference.record_id,
                "content_digest": reference.content_digest,
            }
            for reference in candidates
        ),
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"semantic capability {field} must be non-empty text")
    return value


def _reference(value: object) -> SemanticSourceReference:
    if not isinstance(value, Mapping):
        raise TypeError("semantic capability candidate must be a mapping")
    return SemanticSourceReference(
        _text(value.get("source_id"), "candidate.source_id"),
        _text(value.get("record_id"), "candidate.record_id"),
        _text(value.get("content_digest"), "candidate.content_digest"),
    )


class SemanticSimilarityCapabilityBinding:
    """Expose one immutable semantic projection through the common capability ABI.

    The projection and source cut are composition-owned and fixed at binding time.
    Method code may choose a query vector, metric, candidate subset and limit, but
    cannot silently swap the underlying projection, source cut or embedding model.
    """

    def __init__(
        self,
        snapshot: SemanticProjectionSnapshot,
        query_port: SemanticSimilarityQueryPort,
        *,
        capability_id: str = "data.semantic-similarity",
    ) -> None:
        if not isinstance(snapshot, SemanticProjectionSnapshot):
            raise TypeError("semantic capability requires SemanticProjectionSnapshot")
        if not isinstance(query_port, SemanticSimilarityQueryPort):
            raise TypeError("semantic capability requires SemanticSimilarityQueryPort")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("semantic capability_id must be non-empty")
        self._snapshot = snapshot
        self._query_port = query_port
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.PURE,
            deterministic=True,
        )

    @property
    def snapshot(self) -> SemanticProjectionSnapshot:
        return self._snapshot

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("semantic capability request payload must be a mapping")

        projection_digest = _text(
            payload.get("projection_digest"),
            "projection_digest",
        )
        source_cut_digest = _text(
            payload.get("source_cut_digest"),
            "source_cut_digest",
        )
        embedding_model_digest = _text(
            payload.get("embedding_model_digest"),
            "embedding_model_digest",
        )
        require_sha256(projection_digest, "semantic capability projection_digest")
        require_sha256(source_cut_digest, "semantic capability source_cut_digest")
        require_sha256(
            embedding_model_digest,
            "semantic capability embedding_model_digest",
        )
        if projection_digest != self._snapshot.projection_digest:
            raise ValueError("semantic capability projection identity drift")
        if source_cut_digest != self._snapshot.source_cut_digest:
            raise ValueError("semantic capability source cut identity drift")
        if embedding_model_digest != self._snapshot.embedding_model_digest:
            raise ValueError("semantic capability embedding model identity drift")

        raw_vector = payload.get("vector")
        if not isinstance(raw_vector, Sequence) or isinstance(
            raw_vector, (str, bytes, bytearray)
        ):
            raise TypeError("semantic capability vector must be a sequence")
        vector = tuple(float(value) for value in raw_vector)

        metric_value = _text(payload.get("metric"), "metric")
        try:
            metric = SemanticSimilarityMetric(metric_value)
        except ValueError as exc:
            raise ValueError(
                f"unsupported semantic capability metric: {metric_value!r}"
            ) from exc

        limit = payload.get("limit")
        if type(limit) is not int:
            raise TypeError("semantic capability limit must be an integer")

        raw_candidates = payload.get("candidates", ())
        if not isinstance(raw_candidates, Sequence) or isinstance(
            raw_candidates, (str, bytes, bytearray)
        ):
            raise TypeError("semantic capability candidates must be a sequence")
        candidates = tuple(_reference(row) for row in raw_candidates)

        result = self._query_port.query(
            self._snapshot,
            SemanticSimilarityQuery(
                vector=vector,
                embedding_model_digest=embedding_model_digest,
                metric=metric,
                limit=limit,
                candidates=candidates,
            ),
        )
        if not isinstance(result, SemanticSimilarityResult):
            raise TypeError(
                "semantic similarity query port must return SemanticSimilarityResult"
            )
        if (
            result.projection_digest != self._snapshot.projection_digest
            or result.source_cut_digest != self._snapshot.source_cut_digest
            or result.embedding_model_digest
            != self._snapshot.embedding_model_digest
        ):
            raise ValueError("semantic capability result provenance drift")

        request_digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "projection_digest": result.projection_digest,
                "source_cut_digest": result.source_cut_digest,
                "embedding_model_digest": result.embedding_model_digest,
                "metric": result.metric.value,
                "candidate_count": result.candidate_count,
                "matches": tuple(
                    {
                        "source_id": match.reference.source_id,
                        "record_id": match.reference.record_id,
                        "content_digest": match.reference.content_digest,
                        "score": float(match.score),
                        "rank": match.rank,
                    }
                    for match in result.matches
                ),
            },
            diagnostics={
                "projection_id": self._snapshot.projection_id,
                "projection_version": self._snapshot.projection_version,
                "projection_dimension": self._snapshot.dimension,
            },
            request_digest=request_digest,
        )


__all__ = [
    "SemanticSimilarityCapabilityBinding",
    "semantic_similarity_capability_payload",
]
