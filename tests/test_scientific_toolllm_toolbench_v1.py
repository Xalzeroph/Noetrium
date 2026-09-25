from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.evidence.data.projection.api import (
    SemanticProjectionEntry,
    SemanticProjectionSnapshot,
    SemanticSourceReference,
)
from noetrium_platform.evidence.data.query.runtime import SemanticRetrievalEngine
from research.reproductions.toolllm_toolbench import (
    TOOLLLM_TOOLBENCH_AUDITED_COMMIT,
    TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY,
    retrieve_capability_view,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _CapabilityCatalog:
    def __init__(self, descriptors: tuple[CapabilityDescriptor, ...]) -> None:
        self._descriptors = {descriptor.capability_id: descriptor for descriptor in descriptors}

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        return self._descriptors[capability_id]

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        raise AssertionError("ToolLLM retrieval scaffold must not invoke capabilities")


def _descriptor(capability_id: str, token: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        interface_version="1",
        request_schema=f"schema://{token}/request",
        result_schema=f"schema://{token}/result",
    )


def _projection(descriptors: tuple[CapabilityDescriptor, ...]) -> SemanticProjectionSnapshot:
    weather, calendar = descriptors
    return SemanticProjectionSnapshot(
        "toolllm.api-retriever",
        "paper-era-v1",
        _digest("tool-catalog-cut"),
        _digest("retriever-model-cut"),
        (
            SemanticProjectionEntry(
                SemanticSourceReference("capability-catalog", weather.capability_id, weather.digest()),
                (1.0, 0.0),
            ),
            SemanticProjectionEntry(
                SemanticSourceReference("capability-catalog", calendar.capability_id, calendar.digest()),
                (0.0, 1.0),
            ),
        ),
    )


def test_toolllm_paper_era_fidelity_is_pinned() -> None:
    fidelity = TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY
    assert TOOLLLM_TOOLBENCH_AUDITED_COMMIT == "b2384c2a7f9c3e444a5e579596968ad88cd3201a"
    assert fidelity.default_retrieved_api_count == 5
    assert fidelity.retrieval_similarity == "cosine"
    assert fidelity.authoritative_api_materialization is True
    assert fidelity.llm_function_schema_materialization is True
    assert fidelity.finish_function_injected is True
    assert fidelity.search_policy == "DFSDT"


def test_toolllm_retrieval_uses_semantic_refs_then_authoritative_capability_descriptors() -> None:
    descriptors = (
        _descriptor("weather.current", "weather"),
        _descriptor("calendar.create", "calendar"),
    )
    snapshot = _projection(descriptors)
    view = retrieve_capability_view(
        snapshot=snapshot,
        query_vector=(0.95, 0.05),
        query_embedding_model_digest=snapshot.embedding_model_digest,
        capability_port=_CapabilityCatalog(descriptors),
        query_port=SemanticRetrievalEngine(),
        limit=1,
    )

    assert [descriptor.capability_id for descriptor in view.descriptors] == ["weather.current"]
    assert view.projection_digest == snapshot.projection_digest
    assert view.source_cut_digest == snapshot.source_cut_digest
    assert view.embedding_model_digest == snapshot.embedding_model_digest
    assert len(view.view_digest) == 64


def test_toolllm_retrieval_fails_closed_on_embedding_model_drift() -> None:
    descriptors = (
        _descriptor("weather.current", "weather"),
        _descriptor("calendar.create", "calendar"),
    )
    snapshot = _projection(descriptors)

    with pytest.raises(ValueError, match="embedding model does not match pinned projection"):
        retrieve_capability_view(
            snapshot=snapshot,
            query_vector=(1.0, 0.0),
            query_embedding_model_digest=_digest("different-retriever-model"),
            capability_port=_CapabilityCatalog(descriptors),
            query_port=SemanticRetrievalEngine(),
            limit=1,
        )


def test_toolllm_capability_materialization_fails_closed_on_schema_drift() -> None:
    descriptors = (
        _descriptor("weather.current", "weather"),
        _descriptor("calendar.create", "calendar"),
    )
    snapshot = _projection(descriptors)
    drifted = CapabilityDescriptor(
        capability_id="weather.current",
        interface_version="2",
        request_schema="schema://weather-v2/request",
        result_schema="schema://weather-v2/result",
    )
    catalog = _CapabilityCatalog((drifted, descriptors[1]))

    with pytest.raises(ValueError, match="descriptor drifted"):
        retrieve_capability_view(
            snapshot=snapshot,
            query_vector=(1.0, 0.0),
            query_embedding_model_digest=snapshot.embedding_model_digest,
            capability_port=catalog,
            query_port=SemanticRetrievalEngine(),
            limit=1,
        )
