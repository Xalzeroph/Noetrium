from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    LogicalSchedulingCandidate,
    LogicalSchedulingProgram,
    LogicalSchedulingRuntimeBinding,
    LogicalSchedulingSelection,
    LogicalSchedulingSelectorRegistry,
    ResearchProgramHost,
    RuntimeProgramComposer,
    logical_scheduling_initial_data,
    logical_scheduling_runtime_module,
    logical_scheduling_runtime_operations,
)


def _program(selector_digest: str) -> LogicalSchedulingProgram:
    return LogicalSchedulingProgram(
        program_id="paper.logical-scheduling",
        version="1",
        selector="paper.priority-ready",
        selector_digest=selector_digest,
        batch_size=2,
        allow_idle=False,
        require_ready=True,
    )


def _registry(
    implementation_digest: str,
) -> LogicalSchedulingSelectorRegistry:
    registry = LogicalSchedulingSelectorRegistry()

    def select(request):
        ready = tuple(
            candidate
            for candidate in request.candidates
            if candidate.ready
        )
        ordered = tuple(
            sorted(
                ready,
                key=lambda candidate: (
                    -candidate.priority,
                    candidate.participant_id,
                ),
            )
        )
        selected = tuple(
            candidate.participant_id
            for candidate in ordered[: request.batch_size]
        )
        return LogicalSchedulingSelection(
            selected,
            {
                "policy": "priority-ready",
                "candidate_count": len(request.candidates),
            },
        )

    registry.register(
        "paper.priority-ready",
        select,
        implementation_digest=implementation_digest,
    )
    return registry


def test_logical_scheduling_executes_as_runtime_machine_transition() -> None:
    implementation_digest = canonical_digest(
        {"selector": "paper.priority-ready", "version": 1}
    )
    program = _program(implementation_digest)
    registry = _registry(implementation_digest)
    binding = LogicalSchedulingRuntimeBinding(program, registry)

    candidates = (
        LogicalSchedulingCandidate("agent-b", ready=True, priority=2),
        LogicalSchedulingCandidate("agent-a", ready=True, priority=4),
        LogicalSchedulingCandidate("agent-c", ready=False, priority=100),
    )
    module = logical_scheduling_runtime_module(program)
    runtime_program = (
        RuntimeProgramComposer(
            program_id="runtime.logical-scheduling.test",
            version="1",
            state_schema="runtime.logical-scheduling.test.v1",
            entry_module=module.module_id,
        )
        .module(module)
        .build()
    )
    journal = InMemoryMachineJournal()
    host = ResearchProgramHost(
        host_id="runtime.logical-scheduling.test",
        program=runtime_program,
        operations=logical_scheduling_runtime_operations(),
        journal=journal,
        dependency_identity={
            "logical_scheduling_binding_digest": binding.binding_digest,
        },
    )
    initial_data = logical_scheduling_initial_data(
        decision_id="turn-7",
        program=program,
        candidates=candidates,
        prior_selected_ids=("agent-b",),
    )
    execution = host.execute(
        machine_id="runtime:logical-scheduling:test",
        instance_identity={
            "decision_id": "turn-7",
            "program_digest": program.program_digest,
            "candidate_set_digest": initial_data["candidate_set_digest"],
        },
        binding=binding,
        initial_data=initial_data,
        command_id_prefix="logical-scheduling:test",
    )

    assert execution.status is MachineStatus.COMPLETED
    assert execution.data["selected_participant_ids"] == (
        "agent-a",
        "agent-b",
    )
    assert binding.selection is not None
    assert execution.data["selection_digest"] == (
        binding.selection.selection_digest
    )
    assert len(journal.commits(execution.machine_id)) == 2


def test_logical_scheduling_rejects_selector_identity_drift() -> None:
    expected = canonical_digest(
        {"selector": "paper.priority-ready", "version": 1}
    )
    actual = canonical_digest(
        {"selector": "paper.priority-ready", "version": 2}
    )
    program = _program(expected)
    registry = _registry(actual)

    with pytest.raises(
        ValueError,
        match="selector implementation identity drifted",
    ):
        LogicalSchedulingRuntimeBinding(program, registry)


def test_logical_scheduling_rejects_unready_selector_output() -> None:
    implementation_digest = canonical_digest(
        {"selector": "paper.unready", "version": 1}
    )
    program = LogicalSchedulingProgram(
        program_id="paper.logical-scheduling.unready",
        version="1",
        selector="paper.unready",
        selector_digest=implementation_digest,
        batch_size=1,
        allow_idle=False,
        require_ready=True,
    )
    registry = LogicalSchedulingSelectorRegistry()
    registry.register(
        "paper.unready",
        lambda request: LogicalSchedulingSelection(("agent-c",)),
        implementation_digest=implementation_digest,
    )
    binding = LogicalSchedulingRuntimeBinding(program, registry)
    module = logical_scheduling_runtime_module(program)
    runtime_program = (
        RuntimeProgramComposer(
            program_id="runtime.logical-scheduling.unready",
            version="1",
            state_schema="runtime.logical-scheduling.unready.v1",
            entry_module=module.module_id,
        )
        .module(module)
        .build()
    )
    host = ResearchProgramHost(
        host_id="runtime.logical-scheduling.unready",
        program=runtime_program,
        operations=logical_scheduling_runtime_operations(),
        journal=InMemoryMachineJournal(),
        dependency_identity={
            "logical_scheduling_binding_digest": binding.binding_digest,
        },
    )

    with pytest.raises(
        ValueError,
        match="selected unready participants",
    ):
        host.execute(
            machine_id="runtime:logical-scheduling:unready",
            instance_identity={
                "decision_id": "turn-unready",
                "program_digest": program.program_digest,
            },
            binding=binding,
            initial_data=logical_scheduling_initial_data(
                decision_id="turn-unready",
                program=program,
                candidates=(
                    LogicalSchedulingCandidate(
                        "agent-c",
                        ready=False,
                        priority=100,
                    ),
                ),
            ),
        )
