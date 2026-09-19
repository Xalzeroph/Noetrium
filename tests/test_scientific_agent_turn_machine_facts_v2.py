from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import (
    AGENT_TURN_FACT_SCHEMA,
    AgentTurnFactBuffer,
    AgentTurnFactKind,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    MachineCommand,
    MachineExecutor,
    MachineIdentity,
    MachineKind,
    ProgramLock,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    PARTICIPANT_TURN_FACT_KINDS,
    PARTICIPANT_TURN_FACT_WIRE_SCHEMA,
    ProgrammableMachineInterpreter,
    participant_turn_handlers,
    participant_turn_initial_data,
    participant_turn_program,
    programmable_machine_family,
)


def _digest(value: object) -> str:
    return canonical_digest(value)


def _lock() -> ProgramLock:
    return ProgramLock(
        code_digest=_digest("code"), dependency_digest=_digest("deps"),
        schema_digest=_digest("schema"), interpreter_digest=_digest("interpreter"),
        data_digest=_digest("data"), config_digest=_digest("config"),
    )


def _machine():
    journal = InMemoryMachineJournal()
    program = participant_turn_program()
    machine = MachineExecutor(
        identity=MachineIdentity("participant-turn:1", MachineKind.PARTICIPANT, "1", "g1"),
        program=program.machine_program_ref(_lock()),
        journal=journal,
        family=programmable_machine_family(MachineKind.PARTICIPANT),
    )
    machine.open({})
    return machine, journal, ProgrammableMachineInterpreter(program, participant_turn_handlers())


def _command(command_id: str, revision: int, kind: str, payload: object) -> MachineCommand:
    return MachineCommand(
        command_id=command_id,
        machine_id="participant-turn:1",
        expected_revision=revision,
        kind=kind,
        payload=payload,
    )


def test_fact_wire_contract_matches_participant_turn_program() -> None:
    assert AGENT_TURN_FACT_SCHEMA == PARTICIPANT_TURN_FACT_WIRE_SCHEMA
    assert {kind.value for kind in AgentTurnFactKind} == PARTICIPANT_TURN_FACT_KINDS


def test_participant_program_journals_full_facts_but_keeps_bounded_cursor() -> None:
    machine, journal, interpreter = _machine()
    context = ExecutionContext("run:1", "trace:1", "span:1", task_id="goal:1", decision_cycle_id="cycle:1")
    facts = AgentTurnFactBuffer("session:1")
    planning = facts.append(AgentTurnFactKind.PLANNING_INPUT, context=context,
                            payload={"goal_digest": "a" * 64, "observation_digest": "b" * 64})
    termination = facts.append(AgentTurnFactKind.TERMINATION, context=context,
                               payload={"success": True, "reason": "environment_done"})

    machine.step(_command("start", 0, "program.start", {
        "initial_data": participant_turn_initial_data(
            turn_id="turn:1", session_id="session:1", goal_digest="a" * 64
        )
    }), interpreter)
    fact_commit = machine.step(_command("fact1", 1, "program.step", {
        "action": "record_fact", "fact": planning.as_payload()
    }), interpreter)
    machine.step(_command("fact2", 2, "program.step", {
        "action": "record_fact", "fact": termination.as_payload()
    }), interpreter)
    final = machine.step(_command("finish", 3, "program.step", {
        "action": "finish", "success": True, "termination": "environment_done",
        "fact_head_digest": termination.fact_digest,
    }), interpreter)

    event = thaw_json(fact_commit.event_payloads[1])
    assert event["type"] == "agent_turn_fact"
    state = thaw_json(final.state)["_program"]["data"]
    assert state["fact_count"] == 2
    assert state["fact_head_digest"] == termination.fact_digest
    assert state["status"] == "completed"
    assert len(journal.commits("participant-turn:1")) == 4


def test_participant_turn_rejects_tampered_fact() -> None:
    machine, _, interpreter = _machine()
    machine.step(_command("start", 0, "program.start", {
        "initial_data": participant_turn_initial_data(turn_id="turn:1", session_id="session:1")
    }), interpreter)
    context = ExecutionContext("run:1", "trace:1", "span:1")
    fact = AgentTurnFactBuffer("session:1").append(
        AgentTurnFactKind.OBSERVATION, context=context,
        payload={"observation_id": "obs:1", "state": {"text": "room"}},
    )
    tampered = fact.as_payload()
    tampered["payload"] = {"observation_id": "obs:1", "state": {"text": "different"}}
    with pytest.raises(ValueError, match="digest mismatch"):
        machine.step(_command("fact", 1, "program.step", {
            "action": "record_fact", "fact": tampered
        }), interpreter)
