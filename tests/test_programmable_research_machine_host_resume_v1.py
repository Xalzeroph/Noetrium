from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineKind,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgramBuilder,
    ResearchProgramHost,
)


def _program():
    return (
        ResearchProgramBuilder(
            program_id="host.resume",
            kind=MachineKind.RUNTIME,
            version="1",
            state_schema="host.resume.state.v1",
            entrypoint="pause",
        )
        .node("pause", "test.pause", next_node="finish")
        .node("finish", "test.finish")
        .build()
    )


def _host(journal, calls, *, restorer=None):
    program = _program()

    def pause(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
        assert isinstance(binding, dict)
        calls["pause"] += 1
        return ProgramNodeResult(
            value={"phase": "paused"},
            state_update={"counter": 1, "recoverable_value": "machine-truth"},
            status=MachineStatus.WAITING,
            wait_reason="external-resume",
        )

    def finish(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
        assert isinstance(binding, dict)
        calls["finish"] += 1
        assert request.data["counter"] == 1
        assert binding.get("restored_counter") == 1
        assert binding.get("restored_value") == "machine-truth"
        return ProgramNodeResult(
            value={"done": True},
            state_update={"counter": 2},
        )

    return ResearchProgramHost(
        host_id="test.host.resume",
        program=program,
        operations=(
            ResearchHostOperation(
                "test.pause",
                pause,
                canonical_digest({
                    "operation": "test.pause",
                    "implementation_revision": 1,
                }),
            ),
            ResearchHostOperation(
                "test.finish",
                finish,
                canonical_digest({
                    "operation": "test.finish",
                    "implementation_revision": 1,
                }),
            ),
        ),
        journal=journal,
        max_steps=8,
        dependency_identity={"test": "resume"},
        binding_restorer=restorer,
    )


def _restore(binding: object, data, previous_value) -> None:
    assert isinstance(binding, dict)
    binding["restored_counter"] = data["counter"]
    binding["restored_value"] = data["recoverable_value"]
    binding["previous_value"] = previous_value


def _execute(host, binding, *, resume_waiting=False, initial=None):
    return host.execute(
        machine_id="runtime:host-resume",
        instance_identity={"run_id": "run", "cycle_id": "cycle"},
        binding=binding,
        initial_data={"seed": 7} if initial is None else initial,
        payload={"source": "test"},
        command_id_prefix="runtime:host-resume",
        resume_waiting=resume_waiting,
    )


def test_research_program_host_resumes_waiting_machine_from_journal() -> None:
    journal = InMemoryMachineJournal()
    calls = {"pause": 0, "finish": 0}

    first = _execute(_host(journal, calls), {})
    assert first.status is MachineStatus.WAITING
    assert first.data["counter"] == 1
    assert calls == {"pause": 1, "finish": 0}

    rebound: dict[str, object] = {}
    second = _execute(
        _host(journal, calls, restorer=_restore),
        rebound,
        resume_waiting=True,
    )
    assert second.status is MachineStatus.COMPLETED
    assert second.data["counter"] == 2
    assert rebound["restored_counter"] == 1
    assert rebound["previous_value"] == {"phase": "paused"}
    assert calls == {"pause": 1, "finish": 1}


def test_terminal_reopen_projects_machine_truth_without_handler_replay() -> None:
    journal = InMemoryMachineJournal()
    calls = {"pause": 0, "finish": 0}
    _execute(_host(journal, calls), {})
    _execute(_host(journal, calls, restorer=_restore), {}, resume_waiting=True)
    before = dict(calls)

    rebound: dict[str, object] = {}
    terminal = _execute(_host(journal, calls, restorer=_restore), rebound)

    assert terminal.status is MachineStatus.COMPLETED
    assert terminal.previous_value == {"done": True}
    assert terminal.data["counter"] == 2
    assert calls == before
    assert rebound["restored_counter"] == 2


def test_reopen_rejects_initial_data_identity_drift() -> None:
    journal = InMemoryMachineJournal()
    calls = {"pause": 0, "finish": 0}
    _execute(_host(journal, calls), {})

    with pytest.raises(ValueError, match="initial-data identity drifted"):
        _execute(
            _host(journal, calls, restorer=_restore),
            {},
            initial={"seed": 8},
        )
