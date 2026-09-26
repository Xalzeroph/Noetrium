from __future__ import annotations

import pytest

from noetrium import api
from noetrium_platform.composition.research_method_participant_binding import (
    exact_method_programs,
    exact_method_requirement_implementation_digest,
    resolve_exact_method_participant,
)
from noetrium_platform.foundation.governance.architecture.api import CompositionSubject
from noetrium_platform.research.experimentation.api import ResearchParticipantRequirement


def _return(request: api.MethodNodeRequest) -> api.MethodNodeResult:
    return api.MethodNodeResult(value={"ok": True})


def build_method_v1() -> api.MethodProgram:
    identity = api.MethodProgramIdentity(
        api.MethodIdentity("shared-method", "1", "method-runtime.v1", "schema.v1")
    )
    return (
        api.MethodProgramBuilder(identity, entrypoint="return")
        .return_node("return", "test.return", _return)
        .build()
    )


def build_method_v2() -> api.MethodProgram:
    identity = api.MethodProgramIdentity(
        api.MethodIdentity("shared-method", "2", "method-runtime.v1", "schema.v1")
    )
    return (
        api.MethodProgramBuilder(identity, entrypoint="return")
        .return_node("return", "test.return", _return)
        .build()
    )


def _program(*, duplicate: bool = False) -> api.ResearchProgram:
    builder = api.ResearchProgramBuilder("paper")
    builder.method_program_factory(
        "method-v1",
        module=__name__,
        qualname="build_method_v1",
    )
    builder.method_node("run-v1", definitions=("method-v1",))
    if duplicate:
        builder.method_program_factory(
            "method-v2",
            module=__name__,
            qualname="build_method_v2",
        )
        builder.method_node("run-v2", definitions=("method-v2",))
    return builder.freeze()


def _requirement(treatment: str) -> ResearchParticipantRequirement:
    return ResearchParticipantRequirement(
        role="agent",
        participant_kind="paper_method_program",
        method_id="shared-method",
        treatment_id=treatment,
        capability_requirement_ids=("minecraft.action",),
    )


def test_exact_method_participant_resolution_binds_frozen_method_ir() -> None:
    program = _program()
    requirement = _requirement("sem")
    subject = CompositionSubject.project_subject("paper", "1")

    resolution = resolve_exact_method_participant(program, requirement, subject)

    assert resolution.binding is not None
    assert resolution.proof is not None
    assert resolution.proof.provider_identity == "noetrium.method-runtime"
    runtime_binding = resolution.binding.binding
    assert runtime_binding.role == "agent"
    assert runtime_binding.implementation.participant_id == "shared-method"
    assert runtime_binding.implementation.implementation_version == "1"
    assert runtime_binding.runtime.runtime_id == "noetrium.universal-method-machine"
    assert runtime_binding.configuration_digest == build_method_v1().program_identity.configuration_digest


def test_treatment_changes_requirement_not_method_implementation_identity() -> None:
    program = _program()
    sem = _requirement("sem")
    fixed = _requirement("fixed_typed")

    assert sem.requirement_digest != fixed.requirement_digest
    assert (
        exact_method_requirement_implementation_digest(program, sem)
        == exact_method_requirement_implementation_digest(program, fixed)
    )


def test_duplicate_method_id_with_different_program_ir_fails_closed() -> None:
    with pytest.raises(ValueError, match="multiple exact MethodPrograms"):
        exact_method_programs(_program(duplicate=True))


def test_missing_exact_method_returns_blocking_diagnostic() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.definition(
        "noop",
        kind=api.ResearchDefinitionKind.CUSTOM,
        config={"kind": "noop"},
    )
    builder.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("noop",),
    )
    program = builder.freeze()
    requirement = _requirement("sem")
    resolution = resolve_exact_method_participant(
        program,
        requirement,
        CompositionSubject.project_subject("paper", "1"),
    )

    assert resolution.binding is None
    assert resolution.proof is None
    assert resolution.diagnostics
    assert resolution.diagnostics[0].blocking is True
    assert resolution.diagnostics[0].code.value == "participant.runtime_unavailable"
