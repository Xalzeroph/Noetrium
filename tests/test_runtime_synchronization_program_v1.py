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
    SynchronizationAction,
    SynchronizationDeciderRegistry,
    SynchronizationDecision,
    SynchronizationMode,
    SynchronizationPoint,
    SynchronizationPresetSpec,
    SynchronizationProgram,
    SynchronizationRuntimeBinding,
    synchronization_initial_data,
    synchronization_program_from_preset,
    synchronization_runtime_module,
    synchronization_runtime_operations,
)


def _host(program, journal):
    module = synchronization_runtime_module(program)
    runtime_program = (
        RuntimeProgramComposer(
            program_id="runtime.synchronization.test",
            version="1",
            state_schema="runtime.synchronization.test.v1",
            entry_module=module.module_id,
        )
        .module(module)
        .build()
    )
    return ResearchProgramHost(
        host_id="runtime.synchronization.test",
        program=runtime_program,
        operations=synchronization_runtime_operations(),
        journal=journal,
        dependency_identity={
            "synchronization_program_digest": program.program_digest,
        },
    )


def test_barrier_waits_and_resumes_on_same_runtime_machine() -> None:
    program, registry = synchronization_program_from_preset(
        SynchronizationPresetSpec(SynchronizationMode.BARRIER_ALL),
        program_id="paper.barrier-all",
    )
    binding = SynchronizationRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)
    point = SynchronizationPoint(
        "turn-4:barrier",
        4,
        ("agent-a", "agent-b", "agent-c"),
        ("agent-a",),
    )
    initial_data = synchronization_initial_data(
        decision_id="sync:turn-4",
        program=program,
        point=point,
    )

    waiting = host.execute(
        machine_id="runtime:synchronization:barrier",
        instance_identity={
            "point_id": point.point_id,
            "epoch": point.epoch,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=initial_data,
        payload={"arrival_participant_ids": ()},
        command_id_prefix="sync:barrier",
    )

    assert waiting.status is MachineStatus.WAITING
    assert binding.decision is not None
    assert binding.decision.action is SynchronizationAction.WAIT
    assert waiting.data["point"]["arrived_participant_ids"] == ("agent-a",)
    assert len(journal.commits(waiting.machine_id)) == 2

    released = host.execute(
        machine_id="runtime:synchronization:barrier",
        instance_identity={
            "point_id": point.point_id,
            "epoch": point.epoch,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=initial_data,
        payload={
            "arrival_participant_ids": ("agent-b", "agent-c"),
        },
        command_id_prefix="sync:barrier",
        resume_waiting=True,
    )

    assert released.status is MachineStatus.COMPLETED
    assert binding.decision is not None
    assert binding.decision.action is SynchronizationAction.RELEASE
    assert binding.decision.released_participant_ids == (
        "agent-a",
        "agent-b",
        "agent-c",
    )
    assert released.data["point"]["arrived_participant_ids"] == (
        "agent-a",
        "agent-b",
        "agent-c",
    )
    assert len(released.data["prior_decision_digests"]) == 2
    assert len(journal.commits(released.machine_id)) == 4


def test_asynchronous_preset_releases_current_arrivals_immediately() -> None:
    program, registry = synchronization_program_from_preset(
        SynchronizationPresetSpec(SynchronizationMode.ASYNCHRONOUS),
        program_id="paper.async",
    )
    binding = SynchronizationRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)
    point = SynchronizationPoint(
        "async:step-1",
        1,
        ("agent-a", "agent-b"),
        ("agent-b",),
    )

    execution = host.execute(
        machine_id="runtime:synchronization:async",
        instance_identity={
            "point_id": point.point_id,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=synchronization_initial_data(
            decision_id="sync:async",
            program=program,
            point=point,
        ),
    )

    assert execution.status is MachineStatus.COMPLETED
    assert binding.decision is not None
    assert binding.decision.action is SynchronizationAction.RELEASE
    assert binding.decision.released_participant_ids == ("agent-b",)


def test_quorum_waits_until_threshold_then_releases_arrived_set() -> None:
    program, registry = synchronization_program_from_preset(
        SynchronizationPresetSpec(
            SynchronizationMode.QUORUM,
            quorum=2,
        ),
        program_id="paper.quorum",
    )
    binding = SynchronizationRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)
    point = SynchronizationPoint(
        "review:quorum",
        2,
        ("reviewer-a", "reviewer-b", "reviewer-c"),
        ("reviewer-a",),
    )
    initial_data = synchronization_initial_data(
        decision_id="sync:review",
        program=program,
        point=point,
    )

    waiting = host.execute(
        machine_id="runtime:synchronization:quorum",
        instance_identity={
            "point_id": point.point_id,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=initial_data,
    )
    assert waiting.status is MachineStatus.WAITING

    released = host.execute(
        machine_id="runtime:synchronization:quorum",
        instance_identity={
            "point_id": point.point_id,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=initial_data,
        payload={"arrival_participant_ids": ("reviewer-c",)},
        resume_waiting=True,
    )
    assert released.status is MachineStatus.COMPLETED
    assert binding.decision is not None
    assert binding.decision.released_participant_ids == (
        "reviewer-a",
        "reviewer-c",
    )


def test_synchronization_binding_rejects_decider_identity_drift() -> None:
    expected = canonical_digest({
        "policy": "paper-sync",
        "implementation_revision": 1,
    })
    actual = canonical_digest({
        "policy": "paper-sync",
        "implementation_revision": 2,
    })
    program = SynchronizationProgram(
        program_id="paper.custom-sync",
        version="1",
        decider="paper.custom-sync",
        decider_digest=expected,
    )
    registry = SynchronizationDeciderRegistry()
    registry.register(
        "paper.custom-sync",
        lambda request: SynchronizationDecision(
            SynchronizationAction.WAIT,
            reason_code="test",
        ),
        implementation_digest=actual,
    )

    with pytest.raises(
        ValueError,
        match="synchronization decider implementation identity drifted",
    ):
        SynchronizationRuntimeBinding(program, registry)


def test_synchronization_resume_rejects_unknown_participant() -> None:
    program, registry = synchronization_program_from_preset(
        SynchronizationPresetSpec(SynchronizationMode.BARRIER_ALL),
        program_id="paper.barrier-strict",
    )
    binding = SynchronizationRuntimeBinding(program, registry)
    journal = InMemoryMachineJournal()
    host = _host(program, journal)
    point = SynchronizationPoint(
        "strict:barrier",
        1,
        ("agent-a", "agent-b"),
        ("agent-a",),
    )
    initial_data = synchronization_initial_data(
        decision_id="sync:strict",
        program=program,
        point=point,
    )

    host.execute(
        machine_id="runtime:synchronization:strict",
        instance_identity={
            "point_id": point.point_id,
            "program_digest": program.program_digest,
        },
        binding=binding,
        initial_data=initial_data,
    )

    with pytest.raises(
        ValueError,
        match="resume includes unknown participants",
    ):
        host.execute(
            machine_id="runtime:synchronization:strict",
            instance_identity={
                "point_id": point.point_id,
                "program_digest": program.program_digest,
            },
            binding=binding,
            initial_data=initial_data,
            payload={"arrival_participant_ids": ("intruder",)},
            resume_waiting=True,
        )
