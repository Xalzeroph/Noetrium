from __future__ import annotations

from types import SimpleNamespace

from noetrium import api
from noetrium_platform.foundation.governance.architecture.api import CompositionSubject
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.research.experimentation.api import ResearchParticipantRequirement
from noetrium_platform.composition.research_method_participant_binding import (
    method_implementation_identity,
)
from research.reproductions.auto_materializer import (
    _auto_method_participant_resolution,
    _method_programs,
    _method_requirement_implementation_digest,
)
from research.reproductions.chain_of_thought_gsm8k.program import (
    CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
)


def _lane():
    builder = api.research_os.ResearchProgramBuilder("auto-materializer-test")
    builder.method_program(
        "method",
        module="research.reproductions.chain_of_thought_gsm8k.program",
        qualname="CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM",
    )
    builder.method_node("run", definitions=("method",))
    return SimpleNamespace(program=builder.freeze())


def _requirement() -> ResearchParticipantRequirement:
    method_id = (
        CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM
        .program_identity.implementation.method_id
    )
    return ResearchParticipantRequirement(
        role="reasoner",
        participant_kind="agent_method",
        method_id=method_id,
        treatment_id="control",
    )


def test_auto_method_participant_preserves_study_kind_and_uses_method_machine() -> None:
    lane = _lane()
    requirement = _requirement()
    subject = CompositionSubject.system_subject(SystemIdentity("test-project"))

    resolution = _auto_method_participant_resolution(
        lane,
        requirement,
        subject,
    )
    assert resolution.binding is not None
    assert resolution.proof is not None
    binding = resolution.binding.binding
    assert binding.implementation.kind == "agent_method"
    assert binding.implementation.participant_id == requirement.method_id
    assert binding.runtime.runtime_id == "noetrium.universal-method-machine"
    assert resolution.proof.requirement_digest.value == requirement.requirement_digest


def test_auto_manifest_method_digest_matches_participant_implementation() -> None:
    lane = _lane()
    requirement = _requirement()
    programs = _method_programs(lane)
    program = programs[requirement.method_id]
    study = SimpleNamespace(
        binding_requirements=SimpleNamespace(participants=(requirement,))
    )

    actual = _method_requirement_implementation_digest(
        study,
        lane.program,
        method_id=requirement.method_id,
        treatment_id=requirement.treatment_id,
        program_digest="f" * 64,
    )
    expected = method_implementation_identity(
        program,
        requirement.participant_kind,
    ).digest()

    assert actual == expected
    assert actual != program.program_digest
