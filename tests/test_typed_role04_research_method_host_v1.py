from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.api import (
    MethodProjectDefinition,
    ParticipantRequirement,
    method_program_identity_for_requirement,
    method_program_identity_for_runtime_binding,
    require_method_program_runtime_binding,
)
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
    MethodProgramIdentityMismatch,
    MethodRuntimeIdentity,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine


def _identity(configuration_digest: str = "b" * 64) -> MethodProgramIdentity:
    return MethodProgramIdentity(
        MethodIdentity("paper-only-control", "1", "abi1", "schema1", "a" * 64),
        configuration_digest,
    )


def _program(configuration_digest: str = "b" * 64) -> MethodProgram:
    def decide(request):
        payload = request.input_value
        values = tuple(float(value) for value in payload["values"])
        score = sum(values) / len(values)
        accepted = score >= float(payload["threshold"])
        return MethodNodeResult(
            value={
                "accepted": accepted,
                "score": score,
                "trace": [
                    request.context.run_id,
                    payload["task_id"],
                    "accept" if accepted else "reject",
                ],
            }
        )

    return (
        MethodProgramBuilder(_identity(configuration_digest), entrypoint="decide")
        .return_node("decide", "paper.decide", decide)
        .build(
            input_schema="paper.vector-observation.v1",
            output_schema="paper.decision.v1",
        )
    )


def _participant_binding(configuration_digest: str = "b" * 64) -> ParticipantRuntimeBinding:
    return ParticipantRuntimeBinding(
        "method",
        ParticipantImplementationIdentity(
            "method",
            "paper-only-control",
            "1",
            "abi1",
            "schema1",
            "a" * 64,
        ),
        ParticipantSessionRuntimeIdentity("method-runtime", "1", "abi1", "e" * 64),
        configuration_digest,
    )


def test_downstream_method_authors_target_method_program_directly() -> None:
    program = _program()

    assert type(program) is MethodProgram
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(ExecutionContext("run-1", "trace-1", "span-1")),
        input_value={
            "task_id": "task-7",
            "threshold": 0.5,
            "values": [0.25, 0.75, 1.0],
        },
    )

    assert result.status.value == "succeeded"
    assert result.value["accepted"] is True
    assert result.value["score"] == pytest.approx(2.0 / 3.0)
    assert result.value["trace"] == ("run-1", "task-7", "accept")
    assert not hasattr(program, "run")
    assert not hasattr(program, "checkpoint_state")


@pytest.mark.parametrize("value", ("", "x" * 64, "A" * 64, "a" * 63))
def test_method_program_identity_rejects_noncanonical_configuration_digest(value: str) -> None:
    with pytest.raises(ValueError, match="configuration_digest"):
        MethodProgramIdentity(
            MethodIdentity("m", "1", "abi", "schema", "c" * 64),
            value,
        )


def test_method_program_identity_separates_configuration_from_implementation_identity() -> None:
    implementation = MethodIdentity("m", "1", "abi", "schema", "c" * 64)
    assert (
        MethodProgramIdentity(implementation, None).digest()
        != MethodProgramIdentity(implementation, "d" * 64).digest()
    )


@pytest.mark.parametrize("value", ("bogus", "g" * 64, "A" * 64, "a" * 63))
def test_method_runtime_identity_rejects_noncanonical_artifact_digest(value: str) -> None:
    with pytest.raises(ValueError, match="artifact_digest"):
        MethodRuntimeIdentity("runtime", "1", "abi1", value)


def test_method_runtime_identity_accepts_canonical_artifact_digest() -> None:
    identity = MethodRuntimeIdentity("runtime", "1", "abi1", "e" * 64)
    assert identity.artifact_digest == "e" * 64


def test_method_program_identity_projects_through_requirement_and_runtime_binding() -> None:
    program = _program()
    definition = MethodProjectDefinition(
        "method",
        program.program_identity.implementation,
        "b" * 64,
    )
    requirement = definition.requirement()
    binding = ParticipantRuntimeBinding(
        requirement.role,
        requirement.implementation,
        ParticipantSessionRuntimeIdentity("method-runtime", "1", "abi1", "e" * 64),
        requirement.configuration_digest,
    )

    assert method_program_identity_for_requirement(requirement) == program.program_identity
    assert method_program_identity_for_runtime_binding(binding) == program.program_identity
    require_method_program_runtime_binding(program.program_identity, binding)


def test_method_program_identity_mismatch_fails_before_execution() -> None:
    program = _program()
    with pytest.raises(MethodProgramIdentityMismatch, match="does not match"):
        require_method_program_runtime_binding(
            program.program_identity,
            _participant_binding("c" * 64),
        )


def test_method_program_projection_rejects_non_method_participant_requirement() -> None:
    requirement = ParticipantRequirement(
        "agent",
        ParticipantImplementationIdentity(
            "agent",
            "not-a-method",
            "1",
            "abi1",
            "schema1",
            "a" * 64,
        ),
        None,
    )
    with pytest.raises(MethodProgramIdentityMismatch, match="not method"):
        method_program_identity_for_requirement(requirement)
