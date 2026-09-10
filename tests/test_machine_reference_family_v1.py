from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCommand,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineRuntime,
    ProgramLock,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    AgentTurnMachineInterpreter,
    EnvironmentMachineInterpreter,
    EvaluationMachineInterpreter,
    ExperimentMachineInterpreter,
    MemoryMachineInterpreter,
    RunLifecycleInterpreter,
    reference_machine_families,
)


def digest(value: object) -> str:
    return canonical_digest(value)


def program(kind: MachineKind) -> MachineProgramRef:
    return MachineProgramRef(
        program_digest=digest(("program", kind.value)),
        schema_id=f"{kind.value}.v1",
        program_kind=kind.value,
        program_version="1",
        program_lock=ProgramLock(
            code_digest=digest(("code", kind.value)),
            dependency_digest=digest(("deps", kind.value)),
            schema_digest=digest(("schema", kind.value)),
            interpreter_digest=digest(("interpreter", kind.value)),
            data_digest=digest(("data", kind.value)),
            config_digest=digest(("config", kind.value)),
        ),
    )


CASES = (
    (MachineKind.EXPERIMENT, ExperimentMachineInterpreter(), "experiment.trial.define", {"trial_id": "t1"}),
    (MachineKind.RUN, RunLifecycleInterpreter(), "run.start", {}),
    (MachineKind.AGENT, AgentTurnMachineInterpreter(), "agent.turn.begin", {"turn_id": "turn-1"}),
    (MachineKind.MEMORY, MemoryMachineInterpreter(), "memory.write", {"entry_id": "m1", "value": "x"}),
    (MachineKind.ENVIRONMENT, EnvironmentMachineInterpreter(), "environment.observe", {"step_id": "s1"}),
    (MachineKind.EVALUATION, EvaluationMachineInterpreter(), "evaluation.metric", {"name": "score", "value": 1.0}),
)


@pytest.mark.parametrize("kind,interpreter,command_kind,payload", CASES)
def test_reference_machine_family_commits_through_shared_kernel(
    kind, interpreter, command_kind, payload
) -> None:
    descriptor = next(item for item in reference_machine_families() if item.kind is kind)
    machine_id = f"{kind.value}-1"
    runtime = MachineRuntime(
        identity=MachineIdentity(machine_id, kind, "1", "g1"),
        program=program(kind),
        journal=InMemoryMachineJournal(),
        family=descriptor,
    )
    runtime.open({})
    commit = runtime.step(
        MachineCommand(
            command_id="c1",
            machine_id=machine_id,
            expected_revision=0,
            kind=command_kind,
            payload=payload,
            scope=(f"machine:{machine_id}",),
        ),
        interpreter,
    )
    assert commit.revision == 1
    assert commit.event_payloads
    assert runtime.inspect().revision == 1
