from __future__ import annotations

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityInvocation,
    ModelCapabilityRequirement,
    ModelProviderProfile,
    MultimodalPart,
    MultimodalRequest,
    MultimodalResponse,
    ProjectModelBinding,
    ProjectModelCapabilityClientPort,
    ProjectModelRequest,
    ProjectModelResponse,
)
from tests._functional_model_capability_support import FunctionalModelCapabilityProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.substrate.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        study_id="study-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "test-model",
        "test/model",
        "rev-1",
        "test-engine",
        "1",
        "bf16",
        None,
        8192,
    )


def _binding(requirement: ModelCapabilityRequirement) -> ProjectModelBinding:
    profile = ModelProviderProfile(
        "test-model",
        (requirement.capability_id,),
    )
    generation = requirement.is_generation
    return ProjectModelBinding(
        requirement_digest=requirement.digest(),
        provider_id=profile.provider_id,
        provider_profile_digest=profile.digest(),
        role=requirement.role,
        model=_model(),
        deployment_id="deployment-1",
        deployment_generation="2" * 64,
        model_stack_digest="3" * 64,
        qualification_certificate_digest="4" * 64,
        runtime_qualification_digest="5" * 64,
        host_identity_digest="6" * 64,
        prompt_generation_id=requirement.prompt_generation_id,
        prompt_id=requirement.prompt_id,
        prompt_digest=requirement.prompt_digest,
        capabilities=profile.capabilities,
        runtime_canary_evidence_digests=("8" * 64,),
        request_tokenization_digest="9" * 64 if generation else None,
        capability_id=requirement.capability_id,
        input_schema_id=requirement.input_schema_id,
        output_schema_id=requirement.output_schema_id,
    )


def test_public_generation_uses_typed_capability_invocation() -> None:
    requirement = ModelCapabilityRequirement(
        role="agent",
        prompt_generation_id="generation-1",
        prompt_id="agent-prompt",
        prompt_digest="7" * 64,
        required_capabilities=("generation",),
    )
    body = {"messages": ({"role": "user", "content": "hello"},)}
    envelope = ModelRequestEnvelope(
        "model-request.v1",
        "request-1",
        _context(),
        requirement.role,
        _model(),
        requirement.prompt_generation_id,
        requirement.prompt_id,
        requirement.prompt_digest,
        ArtifactBlobRef("a" * 64, 16, "application/json"),
    )
    payload = ProjectModelRequest(requirement.digest(), envelope, body)
    provider = FunctionalModelCapabilityProvider(
        "generation",
        _binding,
        lambda request: ProjectModelResponse(
            request.request_digest,
            _binding(requirement).digest(),
            "b" * 64,
            "ok",
        ),
    )
    client = provider.bind_capability(requirement)
    assert isinstance(client, ProjectModelCapabilityClientPort)
    invocation = ModelCapabilityInvocation.from_requirement(
        requirement,
        "request-1",
        payload,
        context=_context(),
    )
    response = client.invoke(invocation)
    assert response.output.text == "ok"
    assert response.binding_digest == client.binding.digest()


def test_public_multimodal_keeps_media_content_addressed() -> None:
    requirement = ModelCapabilityRequirement(
        role="perception",
        capability_id="multimodal-inference",
        input_schema_id="model.multimodal.request.v1",
        output_schema_id="model.multimodal.response.v1",
        required_capabilities=("multimodal-inference",),
    )
    request = MultimodalRequest(
        parts=(
            MultimodalPart(
                "state",
                ArtifactBlobRef("c" * 64, 3, "application/octet-stream"),
                modality_id="paper/latent-state",
            ),
        ),
        instruction="plan",
    )
    output = MultimodalResponse(
        model_revision="rev-1",
        text="ok",
    )
    client = FunctionalModelCapabilityProvider(
        "multimodal-inference",
        _binding,
        lambda payload: output,
    ).bind_capability(requirement)
    response = client.invoke(
        ModelCapabilityInvocation.from_requirement(
            requirement,
            "request-mm-1",
            request,
            context=_context(),
        )
    )
    assert response.output.text == "ok"
    assert request.parts[0].content.content_sha256 == "c" * 64
    assert request.parts[0].content.media_type == "application/octet-stream"
