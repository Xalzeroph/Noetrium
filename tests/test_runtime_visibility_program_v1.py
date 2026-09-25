from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ResearchProgramHost,
    RuntimeProgramComposer,
    VisibilityDecision,
    VisibilityDeciderRegistry,
    VisibilityDisposition,
    VisibilityProgram,
    VisibilityResource,
    VisibilityRuntimeBinding,
    VisibilitySubject,
    visibility_initial_data,
    visibility_runtime_module,
    visibility_runtime_operations,
)


def _implementation_digest() -> str:
    return canonical_digest({
        "visibility_policy": "owner-or-shared",
        "implementation_revision": 1,
    })


def _program(
    implementation_digest: str | None = None,
) -> VisibilityProgram:
    return VisibilityProgram(
        program_id="paper.visibility.owner-or-shared",
        version="1",
        decider="paper.owner-or-shared",
        decider_digest=implementation_digest or _implementation_digest(),
    )


def _registry(
    implementation_digest: str | None = None,
) -> VisibilityDeciderRegistry:
    registry = VisibilityDeciderRegistry()

    def decide(request):
        resource = request.resource
        subject = request.subject
        if resource.owner_id == subject.subject_id:
            return VisibilityDecision(
                VisibilityDisposition.FULL,
                reason_code="owner",
                receipt={"relation": "owner"},
            )
        if "shared" in resource.labels:
            return VisibilityDecision(
                VisibilityDisposition.PROJECTED,
                projection_profile="team-shared",
                reason_code="shared",
                receipt={"relation": "shared"},
            )
        return VisibilityDecision(
            VisibilityDisposition.HIDDEN,
            reason_code="private",
            receipt={"relation": "none"},
        )

    registry.register(
        "paper.owner-or-shared",
        decide,
        implementation_digest=(
            implementation_digest or _implementation_digest()
        ),
    )
    return registry


def _host(program, journal):
    module = visibility_runtime_module(program)
    runtime_program = (
        RuntimeProgramComposer(
            program_id="runtime.visibility.test",
            version="1",
            state_schema="runtime.visibility.test.v1",
            entry_module=module.module_id,
        )
        .module(module)
        .build()
    )
    return ResearchProgramHost(
        host_id="runtime.visibility.test",
        program=runtime_program,
        operations=visibility_runtime_operations(),
        journal=journal,
        dependency_identity={
            "visibility_program_digest": program.program_digest,
        },
    )


def test_visibility_decision_is_journaled_against_exact_resource_digest() -> None:
    program = _program()
    registry = _registry()
    binding = VisibilityRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)

    subject = VisibilitySubject(
        "agent-b",
        roles=("solver",),
        groups=("team-1",),
    )
    resource = VisibilityResource(
        resource_id="scratchpad:agent-a:turn-3",
        resource_kind="participant.scratchpad",
        content_digest=canonical_digest(
            {"thought": "private host truth"}
        ),
        owner_id="agent-a",
        namespace="participant.private",
        labels=("shared",),
    )
    initial_data = visibility_initial_data(
        decision_id="visibility:turn-3:agent-b",
        program=program,
        subject=subject,
        resource=resource,
        context={"turn": 3, "phase": "deliberation"},
    )

    execution = host.execute(
        machine_id="runtime:visibility:test",
        instance_identity={
            "decision_id": initial_data["decision_id"],
            "subject_digest": subject.subject_digest,
            "resource_digest": resource.resource_digest,
        },
        binding=binding,
        initial_data=initial_data,
        command_id_prefix="visibility:test",
    )

    assert execution.status is MachineStatus.COMPLETED
    assert binding.decision is not None
    assert binding.decision.disposition is VisibilityDisposition.PROJECTED
    assert binding.decision.projection_profile == "team-shared"
    assert execution.data["decision"]["decision_digest"] == (
        binding.decision.decision_digest
    )
    assert execution.data["resource"]["content_digest"] == (
        resource.content_digest
    )
    assert "content" not in execution.data["resource"]
    assert len(journal.commits(execution.machine_id)) == 2


def test_visibility_private_resource_is_hidden_from_non_owner() -> None:
    program = _program()
    registry = _registry()
    binding = VisibilityRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)

    subject = VisibilitySubject("agent-b")
    resource = VisibilityResource(
        resource_id="scratchpad:agent-a",
        resource_kind="participant.scratchpad",
        content_digest=canonical_digest("private-state"),
        owner_id="agent-a",
        labels=("private",),
    )
    execution = host.execute(
        machine_id="runtime:visibility:hidden",
        instance_identity={
            "subject_digest": subject.subject_digest,
            "resource_digest": resource.resource_digest,
        },
        binding=binding,
        initial_data=visibility_initial_data(
            decision_id="visibility:hidden",
            program=program,
            subject=subject,
            resource=resource,
        ),
    )

    assert execution.status is MachineStatus.COMPLETED
    assert binding.decision is not None
    assert binding.decision.disposition is VisibilityDisposition.HIDDEN


def test_visibility_binding_rejects_policy_implementation_drift() -> None:
    expected = _implementation_digest()
    actual = canonical_digest({
        "visibility_policy": "owner-or-shared",
        "implementation_revision": 2,
    })

    with pytest.raises(
        ValueError,
        match="visibility decider implementation identity drifted",
    ):
        VisibilityRuntimeBinding(
            _program(expected),
            _registry(actual),
        )


def test_visibility_projected_decision_requires_named_projection_profile() -> None:
    with pytest.raises(
        ValueError,
        match="projected visibility requires projection_profile",
    ):
        VisibilityDecision(VisibilityDisposition.PROJECTED)
