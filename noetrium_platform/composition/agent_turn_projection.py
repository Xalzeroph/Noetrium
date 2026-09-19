from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import (
    AgentTurnFact,
    AgentTurnFactBuffer,
    AgentTurnFactKind,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, MachineJournalPort, freeze_json


@dataclass(frozen=True, slots=True)
class AgentTurnTrajectory:
    """Rebuildable read model over authoritative Kernel Journal facts."""

    machine_id: str
    turn_id: str
    session_id: str
    facts: tuple[AgentTurnFact, ...]
    completed: bool = False
    success: bool | None = None
    termination: str | None = None

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def head_digest(self) -> str | None:
        return None if not self.facts else self.facts[-1].fact_digest

    def facts_of(self, *kinds: AgentTurnFactKind) -> tuple[AgentTurnFact, ...]:
        if any(not isinstance(kind, AgentTurnFactKind) for kind in kinds):
            raise TypeError("agent turn trajectory kinds must be AgentTurnFactKind")
        selected = frozenset(kinds)
        return tuple(fact for fact in self.facts if fact.kind in selected)


class AgentTurnJournalProjection:
    """Strict read-only projection from Kernel Journal to Agent Turn facts.

    No facts are persisted here. Every call replays accepted Machine commits and
    validates the Agent Turn event/fact chains, so Journal remains the sole
    durable authority and this projection can always be discarded and rebuilt.
    """

    def __init__(self, journal: MachineJournalPort) -> None:
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("agent turn projection requires MachineJournalPort")
        self._journal = journal

    @staticmethod
    def _text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"agent turn projection {field} is required")
        return value

    @staticmethod
    def _event(value: JsonValue) -> JsonObject:
        row = freeze_json(value)
        if not isinstance(row, Mapping):
            raise ValueError("agent turn journal event must be an object")
        return row

    @staticmethod
    def _fact_document(value: JsonValue) -> JsonObject:
        row = freeze_json(value)
        if not isinstance(row, Mapping):
            raise ValueError("agent turn journal fact must be an object")
        return row

    def rebuild(
        self,
        *,
        machine_id: str,
        turn_id: str,
        session_id: str,
    ) -> AgentTurnTrajectory:
        machine_id = self._text(machine_id, "machine_id")
        turn_id = self._text(turn_id, "turn_id")
        session_id = self._text(session_id, "session_id")

        facts: list[AgentTurnFact] = []
        started = False
        completed = False
        success: bool | None = None
        termination: str | None = None
        finish_count: int | None = None
        finish_head: str | None = None

        for commit in self._journal.commits(machine_id):
            for raw_event in commit.event_payloads:
                event = self._event(raw_event)
                event_type = event.get("type")

                if event_type == "agent_turn_started":
                    if frozenset(event) != frozenset({"type", "turn_id", "session_id", "goal_digest"}):
                        raise ValueError("agent turn started event fields mismatch")
                    if started:
                        raise ValueError("agent turn journal contains duplicate start events")
                    if self._text(event.get("turn_id"), "turn_id") != turn_id:
                        raise ValueError("agent turn journal turn_id mismatch")
                    if self._text(event.get("session_id"), "session_id") != session_id:
                        raise ValueError("agent turn journal session_id mismatch")
                    started = True
                    continue

                if event_type == "agent_turn_fact":
                    if frozenset(event) != frozenset({"type", "turn_id", "fact"}):
                        raise ValueError("agent turn fact event fields mismatch")
                    if not started or completed:
                        raise ValueError("agent turn fact lies outside an active turn")
                    if self._text(event.get("turn_id"), "turn_id") != turn_id:
                        raise ValueError("agent turn journal turn_id mismatch")
                    document = self._fact_document(event.get("fact"))
                    fact = AgentTurnFact.from_payload(document)
                    if fact.session_id != session_id:
                        raise ValueError("agent turn fact session_id mismatch")
                    facts.append(fact)
                    continue

                if event_type == "agent_turn_finished":
                    if frozenset(event) != frozenset({
                        "type", "turn_id", "success", "termination", "fact_count", "fact_head_digest"
                    }):
                        raise ValueError("agent turn finished event fields mismatch")
                    if not started or completed:
                        raise ValueError("agent turn finish event is out of order")
                    if self._text(event.get("turn_id"), "turn_id") != turn_id:
                        raise ValueError("agent turn journal turn_id mismatch")
                    event_success = event.get("success")
                    if not isinstance(event_success, bool):
                        raise ValueError("agent turn finished success must be boolean")
                    event_count = event.get("fact_count")
                    if type(event_count) is not int or event_count < 0:
                        raise ValueError("agent turn finished fact_count must be non-negative")
                    event_head = event.get("fact_head_digest")
                    if not isinstance(event_head, str) or not event_head.strip():
                        raise ValueError("agent turn finished fact_head_digest is required")
                    completed = True
                    success = event_success
                    termination = self._text(event.get("termination"), "termination")
                    finish_count = event_count
                    finish_head = event_head
                    continue

                raise ValueError(f"unsupported agent turn journal event type: {event_type!r}")

        if not started:
            raise ValueError("agent turn journal has no start event")
        replayed = AgentTurnFactBuffer.replay_candidate(session_id, tuple(facts))
        if completed:
            if finish_count != replayed.total_count:
                raise ValueError("agent turn finished fact_count does not match fact chain")
            if finish_head != replayed.head_digest:
                raise ValueError("agent turn finished head does not match fact chain")
            if not facts or facts[-1].kind is not AgentTurnFactKind.TERMINATION:
                raise ValueError("completed agent turn must end with termination fact")

        return AgentTurnTrajectory(
            machine_id=machine_id,
            turn_id=turn_id,
            session_id=session_id,
            facts=tuple(facts),
            completed=completed,
            success=success,
            termination=termination,
        )


__all__ = ["AgentTurnJournalProjection", "AgentTurnTrajectory"]
