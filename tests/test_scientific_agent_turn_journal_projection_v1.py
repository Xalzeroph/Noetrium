from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import AgentTurnFactKind
from noetrium_platform.composition.agent_turn_machine import AgentTurnMachineFactSink
from noetrium_platform.composition.agent_turn_projection import AgentTurnJournalProjection
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    thaw_json,
)
from noetrium_platform.research.execution.machines import participant_turn_host


def _digest(char: str) -> str:
    return char * 64


def _host(journal: InMemoryMachineJournal):
    return participant_turn_host(journal=journal)


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run:1",
        "trace:1",
        "span:1",
        task_id="task:1",
        decision_cycle_id="cycle:1",
    )


def test_projection_rebuilds_only_from_accepted_kernel_journal_facts() -> None:
    journal = InMemoryMachineJournal()
    sink = AgentTurnMachineFactSink(
        _host(journal),
        machine_id="agent-turn:1",
        turn_id="turn:1",
        session_id="session:1",
        goal_digest=_digest("8"),
    )
    context = _context()
    action = sink.append(
        AgentTurnFactKind.ACTION,
        context=context,
        payload={"action_id": "a1", "command": "look"},
    )
    observation = sink.append(
        AgentTurnFactKind.OBSERVATION,
        context=context,
        payload={"observation_id": "o1", "text": "You see a table."},
    )
    sink.finish(context=context, success=True, termination="environment_done")

    trajectory = AgentTurnJournalProjection(journal).rebuild(
        machine_id="agent-turn:1",
        turn_id="turn:1",
        session_id="session:1",
    )

    assert trajectory.completed is True
    assert trajectory.success is True
    assert trajectory.termination == "environment_done"
    assert trajectory.fact_count == 3
    assert trajectory.facts[0].fact_digest == action.fact_digest
    assert trajectory.facts[1].fact_digest == observation.fact_digest
    assert trajectory.facts[-1].kind is AgentTurnFactKind.TERMINATION
    assert trajectory.head_digest == sink.head_digest
    assert tuple(fact.kind for fact in trajectory.facts_of(
        AgentTurnFactKind.ACTION, AgentTurnFactKind.OBSERVATION
    )) == (AgentTurnFactKind.ACTION, AgentTurnFactKind.OBSERVATION)


def test_projection_fails_closed_when_journaled_domain_fact_digest_is_tampered() -> None:
    journal = InMemoryMachineJournal()
    sink = AgentTurnMachineFactSink(
        _host(journal),
        machine_id="agent-turn:1",
        turn_id="turn:1",
        session_id="session:1",
        goal_digest=_digest("8"),
    )
    sink.append(
        AgentTurnFactKind.ACTION,
        context=_context(),
        payload={"action_id": "a1"},
    )

    commits = list(journal.commits("agent-turn:1"))
    record = commits[-1]
    events = tuple(thaw_json(row) for row in record.event_payloads)
    event = next(
        row for row in events
        if isinstance(row, dict) and row.get("type") == "agent_turn_fact"
    )
    fact = event["fact"]
    assert isinstance(fact, dict)
    fact["fact_digest"] = _digest("0")
    event["fact"] = fact
    commits[-1] = replace(record, event_payloads=(event,))

    class TamperedReadJournal:
        durability = "test"

        def append(self, commit):
            raise AssertionError("read projection must never append")

        def latest(self, machine_id):
            return commits[-1] if machine_id == "agent-turn:1" else None

        def get(self, commit_id):
            return next((item for item in commits if item.commit_id == commit_id), None)

        def command_commit(self, machine_id, command_id):
            if machine_id != "agent-turn:1":
                return None
            return next((item for item in commits if item.command_id == command_id), None)

        def has_emitted_commands(self, machine_id):
            return (
                machine_id == "agent-turn:1"
                and any(item.emitted_commands for item in commits)
            )

        def commits(self, machine_id):
            return tuple(commits) if machine_id == "agent-turn:1" else ()

    with pytest.raises(ValueError, match="fact digest mismatch"):
        AgentTurnJournalProjection(TamperedReadJournal()).rebuild(
            machine_id="agent-turn:1",
            turn_id="turn:1",
            session_id="session:1",
        )
