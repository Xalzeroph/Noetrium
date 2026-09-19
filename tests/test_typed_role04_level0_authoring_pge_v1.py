from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProjectDefinition,
    ModelRequirementContribution,
)
from noetrium_platform.capabilities.model.request.prompt.composition import RegistryPromptSelection
from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRegistry, PromptSection, PromptSpec
from noetrium_platform.capabilities.participant.api import (
    AgentIdentity,
    AgentProjectDefinition,
    MethodProjectDefinition,
    ParticipantRequirement,
    ParticipantRequirementContribution,
)
from noetrium_platform.capabilities.participant.method.api import MethodIdentity
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity


def _prompt(*, version: str = "1", role: str = "planner") -> PromptSpec:
    return PromptSpec(
        prompt_id="planner-main",
        role=role,
        version=version,
        model_family="generic-chat",
        output_schema="planner.output.v1",
        sections=(PromptSection("system", f"planner {version}", 10),),
        temperature=0.2,
        top_p=0.9,
        max_output_tokens=512,
    )


def _selection(generation: str = "prompt-gen-1", *, version: str = "1") -> RegistryPromptSelection:
    registry = PromptRegistry()
    registry.publish(generation, (_prompt(version=version),))
    return RegistryPromptSelection(registry)


def test_agent_level0_compiles_to_canonical_participant_requirement() -> None:
    definition = AgentProjectDefinition(
        role="planner",
        identity=AgentIdentity("agent-planner", "1", "1", "1", "a" * 64),
        configuration_digest="b" * 64,
        required_capabilities=("tool.search", "memory.recall"),
    )

    requirement = definition.requirement()
    contribution = definition.contribution()

    assert isinstance(requirement, ParticipantRequirement)
    assert requirement.implementation.kind == "agent"
    assert requirement.implementation.participant_id == "agent-planner"
    assert contribution == ParticipantRequirementContribution(definition.digest(), requirement)


def test_method_level0_uses_same_canonical_participant_requirement_family() -> None:
    definition = MethodProjectDefinition(
        role="method",
        identity=MethodIdentity("sem-method", "3", "2", "1", "c" * 64),
        configuration_digest="d" * 64,
        required_capabilities=("memory.recall",),
    )

    requirement = definition.requirement()
    contribution = definition.contribution()

    assert isinstance(requirement, ParticipantRequirement)
    assert requirement.implementation.kind == "method"
    assert requirement.implementation.participant_id == "sem-method"
    assert contribution.author_definition_digest == definition.digest()
    assert contribution.requirement == requirement


def test_generation_level0_author_declares_prompt_id_not_generation_or_digest() -> None:
    definition = ModelProjectDefinition(
        role="planner",
        prompt_id="planner-main",
        required_capabilities=("chat",),
        minimum_context_tokens=4096,
    )
    requirement = definition.requirement(_selection())

    assert isinstance(requirement, ModelCapabilityRequirement)
    assert requirement.prompt_id == "planner-main"
    assert requirement.prompt_generation_id == "prompt-gen-1"
    assert requirement.prompt_digest == _prompt().bundle_digest()


def test_prompt_generation_change_changes_compiled_requirement_not_author_identity() -> None:
    definition = ModelProjectDefinition(role="planner", prompt_id="planner-main")
    author_digest = definition.digest()

    first = definition.contribution(_selection("prompt-gen-1", version="1"))
    second = definition.contribution(_selection("prompt-gen-2", version="2"))

    assert isinstance(first, ModelRequirementContribution)
    assert first.author_definition_digest == second.author_definition_digest == author_digest
    assert first.requirement.digest() != second.requirement.digest()
    assert first.digest() != second.digest()


def test_non_generation_level0_compiles_without_prompt_authority() -> None:
    definition = ModelProjectDefinition(
        role="retriever",
        capability_id="embedding",
        input_schema_id="model.embedding.input.v1",
        output_schema_id="model.embedding.output.v1",
        required_capabilities=("embedding",),
        minimum_context_tokens=1,
    )

    requirement = definition.requirement()

    assert requirement.capability_id == "embedding"
    assert requirement.prompt_generation_id is None
    assert requirement.prompt_id is None
    assert requirement.prompt_digest is None


def test_generation_requires_prompt_selection_and_rejects_role_drift() -> None:
    definition = ModelProjectDefinition(role="planner", prompt_id="planner-main")
    with pytest.raises(TypeError, match="PromptSelectionPort"):
        definition.requirement()

    registry = PromptRegistry()
    registry.publish("prompt-gen-1", (_prompt(role="critic"),))
    with pytest.raises(ValueError, match="role"):
        definition.requirement(RegistryPromptSelection(registry))


def test_non_generation_rejects_prompt_identity_or_prompt_resolver() -> None:
    with pytest.raises(ValueError, match="must not declare prompt"):
        ModelProjectDefinition(
            role="retriever",
            capability_id="embedding",
            prompt_id="planner-main",
            input_schema_id="model.embedding.input.v1",
            output_schema_id="model.embedding.output.v1",
        )

    definition = ModelProjectDefinition(
        role="retriever",
        capability_id="embedding",
        input_schema_id="model.embedding.input.v1",
        output_schema_id="model.embedding.output.v1",
    )
    with pytest.raises(ValueError, match="must not consume prompt"):
        definition.requirement(_selection())


def test_novel_model_capability_needs_no_platform_registry_edit() -> None:
    definition = ModelProjectDefinition(
        role="paper-component",
        capability_id="paper.novel-value-head",
        input_schema_id="paper.novel.input.v1",
        output_schema_id="paper.novel.output.v1",
        required_capabilities=("paper.novel-value-head",),
    )

    contribution = definition.contribution()

    assert contribution.requirement.capability_id == "paper.novel-value-head"
    assert contribution.requirement.input_schema_id == "paper.novel.input.v1"
    assert contribution.requirement.output_schema_id == "paper.novel.output.v1"


def test_level0_rejects_non_sha_artifact_and_configuration_digests() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        AgentProjectDefinition(
            role="planner",
            identity=AgentIdentity("agent", "1", "1", "1", "not-a-digest"),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        AgentProjectDefinition(
            role="planner",
            identity=AgentIdentity("agent", "1", "1", "1", "a" * 64),
            configuration_digest="not-a-digest",
        )
    with pytest.raises(ValueError, match="SHA-256"):
        MethodProjectDefinition(
            role="method",
            identity=MethodIdentity("method", "1", "1", "1", "not-a-digest"),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        MethodProjectDefinition(
            role="method",
            identity=MethodIdentity("method", "1", "1", "1", "c" * 64),
            configuration_digest="not-a-digest",
        )


def test_direct_participant_implementation_identity_cannot_bypass_digest_validation() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ParticipantImplementationIdentity(
            kind="agent", participant_id="agent", implementation_version="1",
            abi_version="1", schema_version="1", artifact_digest="not-a-digest",
        )


def test_level0_digest_absence_is_none_and_empty_string_is_rejected() -> None:
    definition = AgentProjectDefinition(
        role="planner",
        identity=AgentIdentity("agent", "1", "1", "1"),
    )
    requirement = definition.requirement()
    assert definition.identity.artifact_digest is None
    assert definition.configuration_digest is None
    assert requirement.implementation.artifact_digest is None
    assert requirement.configuration_digest is None

    with pytest.raises(ValueError, match="artifact_digest"):
        AgentIdentity("agent", "1", "1", "1", "")
    with pytest.raises(ValueError, match="configuration_digest"):
        AgentProjectDefinition(
            role="planner",
            identity=AgentIdentity("agent", "1", "1", "1"),
            configuration_digest="",
        )
    with pytest.raises(ValueError, match="artifact_digest"):
        MethodIdentity("method", "1", "1", "1", "")


@pytest.mark.parametrize(
    "invalid_digest",
    (
        "a" * 63,
        "g" * 64,
        "A" * 64,
    ),
)
def test_level0_rejects_noncanonical_digest_spellings(invalid_digest: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        AgentIdentity("agent", "1", "1", "1", invalid_digest)
    with pytest.raises(ValueError, match="SHA-256"):
        MethodIdentity("method", "1", "1", "1", invalid_digest)
    with pytest.raises(ValueError, match="SHA-256"):
        AgentProjectDefinition(
            role="planner",
            identity=AgentIdentity("agent", "1", "1", "1", "a" * 64),
            configuration_digest=invalid_digest,
        )
