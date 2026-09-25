from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelBindingSelectionReceipt,
    ProjectModelBinding,
    ProjectModelBindingSet,
    ProjectModelResponse,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _binding(name: str, deployment: str) -> ProjectModelBinding:
    model = ImmutableModelIdentity(
        name,
        f"repo/{name}",
        f"revision-{name}",
        "vllm",
        "1.0",
        "bfloat16",
        None,
        8192,
    )
    return ProjectModelBinding(
        requirement_digest="1" * 64,
        provider_id=f"provider-{name}",
        provider_profile_digest="2" * 64,
        role="policy",
        model=model,
        deployment_id=deployment,
        deployment_generation="3" * 64,
        model_stack_digest="4" * 64,
        qualification_certificate_digest="5" * 64,
        runtime_qualification_digest="6" * 64,
        host_identity_digest="7" * 64,
        prompt_generation_id="prompt-generation",
        prompt_id="policy-prompt",
        prompt_digest="8" * 64,
        capabilities=("generation",),
        runtime_canary_evidence_digests=("9" * 64,),
        request_tokenization_digest="a" * 64,
    )


def test_binding_set_is_frozen_and_selection_is_explicit() -> None:
    primary = _binding("a", "deployment-a")
    alternate = _binding("b", "deployment-b")
    admitted = ProjectModelBindingSet((alternate, primary))
    assert admitted.requirement_digest == primary.requirement_digest
    assert admitted.role == "policy"
    assert admitted.binding_digests == tuple(sorted(admitted.binding_digests))

    receipt = admitted.selection_receipt(
        request_digest="b" * 64,
        binding=alternate,
    )
    assert isinstance(receipt, ModelBindingSelectionReceipt)
    assert receipt.selected_binding_digest == alternate.digest()
    assert receipt.binding_set_digest == admitted.binding_set_digest
    assert receipt.attempt_index == 1


def test_binding_set_rejects_undeclared_model_drift() -> None:
    admitted = ProjectModelBindingSet((_binding("a", "deployment-a"),))
    with pytest.raises(ValueError, match="outside the frozen admitted set"):
        admitted.selection_receipt(
            request_digest="b" * 64,
            binding=_binding("b", "deployment-b"),
        )


def test_later_selection_attempt_requires_predecessor_and_causal_evidence() -> None:
    binding = _binding("a", "deployment-a")
    admitted = ProjectModelBindingSet((binding,))
    first = admitted.selection_receipt(
        request_digest="b" * 64,
        binding=binding,
    )
    with pytest.raises(ValueError, match="causal evidence"):
        admitted.selection_receipt(
            request_digest="b" * 64,
            binding=binding,
            attempt_index=2,
            reason_code="provider-temporary-failure",
            previous_selection_receipt_digest=first.receipt_digest,
        )
    second = admitted.selection_receipt(
        request_digest="b" * 64,
        binding=binding,
        attempt_index=2,
        reason_code="provider-temporary-failure",
        previous_selection_receipt_digest=first.receipt_digest,
        evidence_refs=("effect:model-request-attempt-1",),
    )
    assert second.previous_selection_receipt_digest == first.receipt_digest


def test_project_model_response_binds_selection_to_same_request_and_binding() -> None:
    binding = _binding("a", "deployment-a")
    admitted = ProjectModelBindingSet((binding,))
    receipt = admitted.selection_receipt(
        request_digest="b" * 64,
        binding=binding,
    )
    response = ProjectModelResponse(
        request_digest="b" * 64,
        binding_digest=binding.digest(),
        response_digest="c" * 64,
        text="ok",
        selection_receipt=receipt,
    )
    assert response.selection_receipt == receipt

    with pytest.raises(ValueError, match="selection binding drift"):
        replace(response, binding_digest="d" * 64)
