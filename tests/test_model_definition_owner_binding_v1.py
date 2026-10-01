from dataclasses import replace

from noetrium_platform.capabilities.model.api import ProjectModelBinding
from noetrium_platform.composition.local_research_execution_authority import (
    _model_definition_owner_identity,
    _model_physical_owner_digest,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _binding(*, role: str, requirement: str, prompt: str) -> ProjectModelBinding:
    return ProjectModelBinding(
        requirement_digest=requirement * 64,
        provider_id="noetrium.qualified-model",
        provider_profile_digest="b" * 64,
        role=role,
        model=ImmutableModelIdentity(
            logical_name="Qwen3-8B",
            model_id="Qwen3-8B",
            revision="artifact-sha256:" + "1" * 64,
            engine="vllm",
            engine_version="0.8.5",
            dtype="bfloat16",
            quantization=None,
            context_length=40960,
        ),
        deployment_id="qualified-runtime",
        deployment_generation="1" * 64,
        model_stack_digest="c" * 64,
        qualification_certificate_digest=None,
        runtime_qualification_digest=None,
        host_identity_digest="d" * 64,
        prompt_generation_id=prompt + "-generation",
        prompt_id=prompt,
        prompt_digest="e" * 64,
        capabilities=("generation",),
        runtime_canary_evidence_digests=(),
        request_tokenization_digest="f" * 64,
    )


def test_model_definition_owner_identity_is_role_and_prompt_independent() -> None:
    planner = _binding(role="planner", requirement="a", prompt="planner")
    meta = _binding(role="meta_architect", requirement="9", prompt="meta")

    assert planner.digest() != meta.digest()
    assert _model_physical_owner_digest(planner) == _model_physical_owner_digest(meta)
    assert _model_definition_owner_identity((planner, meta)) == (
        _model_definition_owner_identity((planner,))
    )


def test_model_definition_owner_identity_tracks_physical_generation() -> None:
    planner = _binding(role="planner", requirement="a", prompt="planner")
    next_generation = replace(
        planner,
        deployment_generation="2" * 64,
    )

    assert _model_physical_owner_digest(planner) != _model_physical_owner_digest(
        next_generation
    )
    assert _model_definition_owner_identity((planner,)) != (
        _model_definition_owner_identity((next_generation,))
    )


def test_model_definition_owner_identity_is_order_independent_and_deduplicated() -> None:
    planner = _binding(role="planner", requirement="a", prompt="planner")
    meta = _binding(role="meta_architect", requirement="9", prompt="meta")
    other = replace(
        planner,
        deployment_id="qualified-runtime-other",
        deployment_generation="3" * 64,
    )

    assert _model_definition_owner_identity((planner, meta, other)) == (
        _model_definition_owner_identity((other, meta, planner))
    )
