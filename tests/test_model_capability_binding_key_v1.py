from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
)
from noetrium_platform.capabilities.model.providers.binding import (
    resolve_qualified_model_requirement,
)
from noetrium_platform.capabilities.model.serving.api import (
    ModelEndpointReplicaSet,
    QualifiedModelEndpointBinding,
    RoleModelAssignment,
    RoleModelManifest,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "shared-model",
        "org/shared-model",
        "rev-1",
        "vllm",
        "1",
        "bf16",
        None,
        8192,
        "tokenizer-rev-1",
    )


def _binding(
    capability_id: str,
    input_schema_id: str,
    output_schema_id: str,
    *,
    deployment_id: str,
) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="scientist",
        capability_id=capability_id,
        input_schema_id=input_schema_id,
        output_schema_id=output_schema_id,
        deployment_id=deployment_id,
        deployment_generation=("1" if deployment_id == "gen" else "2") * 64,
        base_url="http://127.0.0.1:8000",
        model=_model(),
        model_stack_digest="3" * 64,
        qualification_certificate_digest="4" * 64,
        runtime_qualification_digest="5" * 64,
        host_identity_digest="6" * 64,
        prompt_generation="prompt-v1" if capability_id == "generation" else None,
        max_admitted_concurrency=1,
        runtime_canary_evidence_digests=("7" * 64,),
        tokenizer_sha256="8" * 64 if capability_id == "generation" else None,
        chat_template_sha256=None,
        verified_capabilities=(capability_id,),
    )


def test_same_role_can_freeze_distinct_capability_protocols_without_aliasing() -> None:
    manifest=RoleModelManifest((
        RoleModelAssignment(
            "scientist",
            "generation",
            "model.generation.request.v1",
            "model.generation.response.v1",
            "gen",
        ),
        RoleModelAssignment(
            "scientist",
            "embedding",
            "model.embedding.input.v1",
            "model.embedding.output.v1",
            "embed",
        ),
    ))
    assert manifest.deployment_for(
        "scientist",
        "generation",
        "model.generation.request.v1",
        "model.generation.response.v1",
    ) == "gen"
    assert manifest.deployment_for(
        "scientist",
        "embedding",
        "model.embedding.input.v1",
        "model.embedding.output.v1",
    ) == "embed"
    with pytest.raises(KeyError):
        manifest.deployment_for(
            "scientist",
            "embedding",
            "model.generation.request.v1",
            "model.embedding.output.v1",
        )


def test_replica_set_fails_closed_on_capability_protocol_drift() -> None:
    generation=_binding(
        "generation",
        "model.generation.request.v1",
        "model.generation.response.v1",
        deployment_id="gen",
    )
    embedding=_binding(
        "embedding",
        "model.embedding.input.v1",
        "model.embedding.output.v1",
        deployment_id="embed",
    )
    with pytest.raises(ValueError,match="capability protocol"):
        ModelEndpointReplicaSet((generation,embedding))


def test_requirement_resolution_queries_exact_protocol_key() -> None:
    requirement=ModelCapabilityRequirement(
        role="scientist",
        capability_id="embedding",
        input_schema_id="model.embedding.input.v1",
        output_schema_id="model.embedding.output.v1",
        required_capabilities=("embedding",),
    )
    binding=_binding(
        requirement.capability_id,
        requirement.input_schema_id,
        requirement.output_schema_id,
        deployment_id="embed",
    )

    class Authority:
        def binding_for(self, **kwargs):
            assert kwargs == {
                "role":"scientist",
                "capability_id":"embedding",
                "input_schema_id":"model.embedding.input.v1",
                "output_schema_id":"model.embedding.output.v1",
                "prompt_generation":None,
            }
            return binding

    resolved,diagnostics=resolve_qualified_model_requirement(
        ModelProviderProfile("qualified",("embedding",)),
        Authority(),
        requirement,
    )
    assert diagnostics == ()
    assert resolved is binding
