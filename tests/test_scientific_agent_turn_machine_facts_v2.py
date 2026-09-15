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
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineRuntime,
    ProgramLock,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    AGENT_TURN_FACT_KINDS,
    AGENT_TURN_FACT_WIRE_SCHEMA,
    AgentTurnMachineInterpreter,
    agent_turn_machine_family,
)


def _digest(value: object) -> str:
    return canonical_digest(value)


def _program() -> MachineProgramRef:
    return MachineProgramRef(
        program_digest=_digest("agent-turn-program"),
        schema_id="agent.turn.program.v2",
        program_kind="agent",
        program_version="2",
        program_lock=ProgramLock(
            code_digest=_digest("code"),
            dependency_digest=_digest("deps"),
            schema_digest=_digest("schema"),
            interpreter_digest=_digest("interpreter"),
            data_digest=_digest("data"),
            config_digest=_digest("config"),
        ),
    )


def _runtime():
    journal = InMemoryMachineJournal()
    family = agent_turn_machine_family()
    runtime = MachineRuntime(
        identity=MachineIdentity("agent-turn:1", MachineKind.AGENT, family.implementation_version, "g1"),
        program=_program(),
        journal=journal,
        family=family,
    )
    runtime.open({})
    return runtime, journal


def _command(command_id: str, revision: int, kind: str, payload: object) -> MachineCommand:
    return MachineCommand(
        command_id=command_id,
        machine_id="agent-turn:1",
        expected_revision=revision,
        kind=kind,
        payload=payload,
        scope=("machine:agent-turn:1",),
    )


def test_runtime_fact_wire_contract_matches_agent_turn_machine_contract() -> None:
    assert AGENT_TURN_FACT_SCHEMA == AGENT_TURN_FACT_WIRE_SCHEMA
    assert {kind.value for kind in AgentTurnFactKind} == AGENT_TURN_FACT_KINDS


def test_agent_turn_machine_journals_full_facts_but_state_keeps_only_cursor() -> None:
    runtime, journal = _runtime()
    interpreter = AgentTurnMachineInterpreter()
    context = ExecutionContext(
        "run:1", "trace:1", "span:1",
        task_id="goal:1", decision_cycle_id="cycle:1",
    )
    facts = AgentTurnFactBuffer("session:1")
    planning = facts.append(
        AgentTurnFactKind.PLANNING_INPUT,
        context=context,
        payload={"goal_digest": "a" * 64, "observation_digest": "b" * 64},
    )
    termination = facts.append(
        AgentTurnFactKind.TERMINATION,
        context=context,
        payload={"success": True, "reason": "environment_done"},
    )

    runtime.step(
        _command(
            "c1", 0, "agent.turn.begin",
            {"turn_id": "turn:1", "session_id": "session:1", "goal_digest": "a" * 64},
        ),
        interpreter,
    )
    fact_commit = runtime.step(
        _command("c2", 1, "agent.fact.record", {"turn_id": "turn:1", "fact": planning.as_payload()}),
        interpreter,
    )
    runtime.step(
        _command("c3", 2, "agent.fact.record", {"turn_id": "turn:1", "fact": termination.as_payload()}),
        interpreter,
    )
    final_commit = runtime.step(
        _command(
            "c4", 3, "agent.turn.finish",
            {
                "turn_id": "turn:1",
                "success": True,
                "termination": "environment_done",
                "fact_head_digest": termination.fact_digest,
            },
        ),
        interpreter,
    )

    event = thaw_json(fact_commit.event_payloads[0])
    assert event["type"] == "agent_turn_fact"
    assert event["fact"] == planning.as_payload()

    state = thaw_json(final_commit.state)
    assert "facts" not in state
    assert state["fact_count"] == 2
    assert state["fact_head_digest"] == termination.fact_digest
    assert state["last_fact_kind"] == "termination"
    assert state["status"] == "completed"
    assert len(journal.commits("agent-turn:1")) == 4


def test_agent_turn_machine_rejects_tampered_or_noncontiguous_fact() -> None:
    runtime, _ = _runtime()
    interpreter = AgentTurnMachineInterpreter()
    runtime.step(
        _command("c1", 0, "agent.turn.begin", {"turn_id": "turn:1", "session_id": "session:1"}),
        interpreter,
    )
    context = ExecutionContext("run:1", "trace:1", "span:1")
    fact = AgentTurnFactBuffer("session:1").append(
        AgentTurnFactKind.OBSERVATION,
        context=context,
        payload={"observation_id": "obs:1", "state": {"text": "room"}},
    )
    tampered = fact.as_payload()
    tampered["payload"] = {"observation_id": "obs:1", "state": {"text": "different"}}

    with pytest.raises(ValueError, match="digest mismatch"):
        runtime.step(
            _command("c2", 1, "agent.fact.record", {"turn_id": "turn:1", "fact": tampered}),
            interpreter,
        )


def test_agent_turn_machine_requires_termination_fact_before_finish() -> None:
    runtime, _ = _runtime()
    interpreter = AgentTurnMachineInterpreter()
    runtime.step(
        _command("c1", 0, "agent.turn.begin", {"turn_id": "turn:1", "session_id": "session:1"}),
        interpreter,
    )

    with pytest.raises(ValueError, match="termination fact"):
        runtime.step(
            _command(
                "c2", 1, "agent.turn.finish",
                {
                    "turn_id": "turn:1",
                    "success": True,
                    "termination": "done",
                    "fact_head_digest": None,
                },
            ),
            interpreter,
        )
