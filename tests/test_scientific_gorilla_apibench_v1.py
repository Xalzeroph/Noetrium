from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    CapabilitySelectionReference,
)
from research.reproductions.gorilla_apibench import (
    GORILLA_APIBENCH_AUDITED_COMMIT,
    GORILLA_APIBENCH_REFERENCE_FIDELITY,
    GorillaRetrievalSelection,
    GorillaRetrieverMode,
    materialize_gorilla_capability_view,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _descriptor(capability_id: str, revision: str = "1") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        interface_version=revision,
        request_schema=f"schema://{capability_id}/{revision}/request",
        result_schema=f"schema://{capability_id}/{revision}/result",
    )


class _Catalog:
    def __init__(self, descriptors: tuple[CapabilityDescriptor, ...]) -> None:
        self._descriptors = {row.capability_id: row for row in descriptors}

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        return self._descriptors[capability_id]

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        raise AssertionError("Gorilla selection scaffold must not invoke capabilities")


def test_gorilla_paper_era_retrieval_fidelity_is_pinned() -> None:
    fidelity = GORILLA_APIBENCH_REFERENCE_FIDELITY
    assert GORILLA_APIBENCH_AUDITED_COMMIT == "c849d11833ce0d401df4ab5a4d854167ad861684"
    assert fidelity.retrieval_modes == ("bm25", "gpt_embedding")
    assert fidelity.default_top_k == 1
    assert fidelity.embedding_similarity == "cosine"
    assert fidelity.prompt_order == ("user_query", "retrieved_api_documentation")
    assert fidelity.retriever_aware_training is True
    assert fidelity.retrieval_policy_owned_downstream is True


def test_bm25_selected_api_materializes_the_same_generic_capability_view_without_embeddings() -> None:
    torch_hub = _descriptor("torch.hub.load")
    selection = GorillaRetrievalSelection(
        GorillaRetrieverMode.BM25,
        _digest("gorilla-api-corpus-cut"),
        (CapabilitySelectionReference(torch_hub.capability_id, torch_hub.digest()),),
    )
    view = materialize_gorilla_capability_view(
        selection,
        capability_port=_Catalog((torch_hub,)),
    )

    assert view.descriptors == (torch_hub,)
    assert view.source_cut_digest == selection.source_cut_digest
    assert view.selection_provenance_digest == selection.digest()
    assert not hasattr(view, "embedding_model_digest")
    assert not hasattr(view, "retrieval_mode")


def test_embedding_and_bm25_selection_policy_remain_distinct_downstream_but_share_view_contract() -> None:
    api = _descriptor("tensorflow.keras.Model")
    reference = CapabilitySelectionReference(api.capability_id, api.digest())
    bm25 = GorillaRetrievalSelection(
        GorillaRetrieverMode.BM25,
        _digest("same-api-corpus-cut"),
        (reference,),
    )
    embedding = GorillaRetrievalSelection(
        GorillaRetrieverMode.GPT_EMBEDDING,
        _digest("same-api-corpus-cut"),
        (reference,),
    )

    assert bm25.digest() != embedding.digest()
    assert materialize_gorilla_capability_view(
        bm25,
        capability_port=_Catalog((api,)),
    ).descriptors == materialize_gorilla_capability_view(
        embedding,
        capability_port=_Catalog((api,)),
    ).descriptors


def test_gorilla_capability_view_fails_closed_on_authoritative_schema_drift() -> None:
    selected = _descriptor("torch.hub.load", "1")
    drifted = _descriptor("torch.hub.load", "2")
    selection = GorillaRetrievalSelection(
        GorillaRetrieverMode.BM25,
        _digest("gorilla-api-corpus-cut"),
        (CapabilitySelectionReference(selected.capability_id, selected.digest()),),
    )

    with pytest.raises(ValueError, match="descriptor drifted"):
        materialize_gorilla_capability_view(
            selection,
            capability_port=_Catalog((drifted,)),
        )
