from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import (
    ChildMachineLink,
    ExecutionContext,
    InMemoryMachineJournal,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineExecutor,
    MachineStatus,
    ProgramLock,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import (
    MachineMethodTransitionAuthority,
    UniversalMethodMachine,
)


def _identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.machine-backed", "1", "1", "1"))


def _context() -> ExecutionContext:
    return ExecutionContext("run-1", "trace-1", "span-1")


def _machine_program(program) -> MachineProgramRef:
    return MachineProgramRef(
        program_digest=program.program_digest,
        schema_id="method.machine.v2",
        program_kind="method",
        program_version="2",
        program_lock=ProgramLock(
            code_digest=program.program_digest,
            dependency_digest=canonical_digest({"deps": "test"}),
            schema_digest=canonical_digest({"schema": "method.machine.v2"}),
            interpreter_digest=canonical_digest({"interpreter": "umm-node"}),
            data_digest=canonical_digest({"data": "none"}),
            config_digest=canonical_digest({"config": "test"}),
        ),
    )


def _runtime(program, journal, *, binding_digest=None):
    machine = MachineExecutor(
        identity=MachineIdentity("method:run-1", MachineKind.METHOD, "2", "generation:1"),
        program=_machine_program(program),
        journal=journal,
    )
    authority = MachineMethodTransitionAuthority(machine)
    return machine, MethodRuntimeContext(
        _context(), transitions=authority, runtime_binding_digest=binding_digest
    )


def _two_node_program():
    def compute(request):
        return MethodNodeResult(value=1, state_update={"count": 1})

    def finish(request):
        return MethodNodeResult(value=request.state["count"])

    return (
        MethodProgramBuilder(_identity(), entrypoint="compute")
        .add(MethodNodeSpec("compute", "test.compute", ("finish",), compute))
        .add(MethodNodeSpec("finish", "test.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
    )


def _interrupt_program():
    def finish(request):
        return MethodNodeResult(value="resumed")

    return (
        MethodProgramBuilder(_identity(), entrypoint="pause")
        .add(MethodNodeSpec("pause", "method.pause", ("finish",), kind=MethodNodeKind.INTERRUPT))
        .add(MethodNodeSpec("finish", "method.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
    )


def test_each_method_node_is_one_machine_commit_and_replay_is_authoritative() -> None:
    program = _two_node_program()
    journal = InMemoryMachineJournal()
    machine, runtime = _runtime(program, journal)
    result = UniversalMethodMachine().run(program, runtime=runtime)

    assert result.status is MethodRunStatus.SUCCEEDED
    commits = journal.commits(machine.machine_id)
    assert len(commits) == 3
    assert tuple(commit.revision for commit in commits) == (1, 2, 3)
    assert commits[0].command_id.endswith(":1:compute")
    assert commits[1].command_id.endswith(":2:finish")
    assert commits[2].accepted_status is MachineStatus.COMPLETED
    replay = machine.replay()
    method = replay.state["method"]
    assert method["sequence"] == 2
    assert method["state"]["count"] == 1
    assert result.step_count == 2


def test_interrupt_is_committed_as_machine_wait_and_resume_uses_journal() -> None:
    program = _interrupt_program()
    journal = InMemoryMachineJournal()
    machine, runtime = _runtime(program, journal)
    host = UniversalMethodMachine()

    first = host.run(program, runtime=runtime)
    assert first.status is MethodRunStatus.INTERRUPTED
    assert machine.inspect().status is MachineStatus.INTERRUPTED
    commits = journal.commits(machine.machine_id)
    assert len(commits) == 2
    assert commits[-1].accepted_status is MachineStatus.INTERRUPTED
    assert any(
        isinstance(payload, dict) and payload.get("kind") == "method.interrupt"
        for payload in map(dict, commits[0].event_payloads)
    )

    resumed = host.run(program, runtime=runtime, resume=True)
    assert resumed.status is MethodRunStatus.SUCCEEDED
    assert resumed.value == "resumed"
    assert len(journal.commits(machine.machine_id)) == 4
    assert machine.inspect().status is MachineStatus.COMPLETED


def test_resume_rejects_runtime_binding_drift() -> None:
    program = _interrupt_program()
    journal = InMemoryMachineJournal()
    digest_a = canonical_digest({"binding": "a"})
    digest_b = canonical_digest({"binding": "b"})
    _machine, runtime = _runtime(program, journal, binding_digest=digest_a)
    first = UniversalMethodMachine().run(program, runtime=runtime)
    assert first.status is MethodRunStatus.INTERRUPTED

    _machine2, changed_runtime = _runtime(program, journal, binding_digest=digest_b)
    with pytest.raises(ValueError, match="runtime binding drift"):
        UniversalMethodMachine().run(program, runtime=changed_runtime, resume=True)


def test_node_exception_is_machine_failed_fact_without_advancing_method_sequence() -> None:
    def explode(_request):
        raise RuntimeError("boom")

    program = (
        MethodProgramBuilder(_identity(), entrypoint="explode")
        .add(MethodNodeSpec("explode", "test.explode", (), explode, kind=MethodNodeKind.RETURN))
        .build()
    )
    journal = InMemoryMachineJournal()
    machine, runtime = _runtime(program, journal)
    result = UniversalMethodMachine().run(program, runtime=runtime)

    assert result.status is MethodRunStatus.FAILED
    commits = journal.commits(machine.machine_id)
    assert len(commits) == 1
    assert commits[0].accepted_status is MachineStatus.FAILED
    assert commits[0].state["method"]["sequence"] == 0
    assert machine.replay().state["method"]["current_node"] == "explode"
    assert machine.inspect().status is MachineStatus.FAILED


def test_step_limit_is_committed_as_resumable_interrupted_control_fact() -> None:
    def loop(request):
        return MethodNodeResult(
            value=request.visit,
            state_update={"n": request.visit + 1},
            next_node="loop",
        )

    program = (
        MethodProgramBuilder(_identity(), entrypoint="loop")
        .add(MethodNodeSpec("loop", "test.loop", ("loop",), loop, max_visits=5))
        .build()
    )
    journal = InMemoryMachineJournal()
    machine, runtime = _runtime(program, journal)
    result = UniversalMethodMachine(max_steps=1).run(program, runtime=runtime)

    assert result.status is MethodRunStatus.LIMIT_REACHED
    commits = journal.commits(machine.machine_id)
    assert len(commits) == 2
    assert commits[0].accepted_status is MachineStatus.RUNNABLE
    assert commits[1].accepted_status is MachineStatus.INTERRUPTED
    assert machine.inspect().status is MachineStatus.INTERRUPTED
    assert machine.replay().state["method"]["sequence"] == 1



def test_method_transition_commits_child_machine_link() -> None:
    child_program_digest = canonical_digest({"program": "child-optimization"})
    link = ChildMachineLink(
        parent_machine_id="method:run-1",
        child_machine_id="optimization:method-child",
        child_program_digest=child_program_digest,
        child_snapshot_ref="machine:optimization:method-child:cut:2:ref",
        child_transition_start=1,
        child_transition_end=2,
        child_result_ref="machine:optimization:method-child:result:best",
        failure_policy="fail_parent",
    )

    def finish(_request):
        return MethodNodeResult(
            value={"delegated": True},
            child_links=(link,),
        )

    program = (
        MethodProgramBuilder(_identity(), entrypoint="finish")
        .add(
            MethodNodeSpec(
                "finish",
                "test.child-machine",
                (),
                finish,
                kind=MethodNodeKind.RETURN,
            )
        )
        .build()
    )
    journal = InMemoryMachineJournal()
    machine, runtime = _runtime(program, journal)
    result = UniversalMethodMachine().run(program, runtime=runtime)

    assert result.status is MethodRunStatus.SUCCEEDED
    commits = journal.commits(machine.machine_id)
    assert len(commits[0].child_links) == 1
    assert commits[0].child_links[0] == link
    assert commits[0].child_links[0].child_program_digest == child_program_digest
