from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.agent.api.turn_facts import (
    AgentTurnFact,
    AgentTurnFactKind,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue


class AgentTurnFactBuffer:
    """Proposal-local ordered fact buffer for one Agent Turn VM session.

    This object deliberately has no persistence API. It only builds a typed,
    digest-chained candidate fact sequence that an enclosing Method/Run Machine
    may project into its TransitionProposal. Kernel Journal remains the sole
    authority for accepted ordered machine facts.
    """

    def __init__(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("agent turn fact buffer requires session_id")
        self._session_id = session_id
        self._facts: list[AgentTurnFact] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def facts(self) -> tuple[AgentTurnFact, ...]:
        return tuple(self._facts)

    @property
    def head_digest(self) -> str | None:
        return None if not self._facts else self._facts[-1].fact_digest

    @property
    def next_sequence(self) -> int:
        return len(self._facts) + 1

    def append(
        self,
        kind: AgentTurnFactKind,
        *,
        context: ExecutionContext,
        payload: Mapping[str, JsonValue] | None = None,
        artifact_refs: tuple[str, ...] = (),
    ) -> AgentTurnFact:
        fact = AgentTurnFact.from_context(
            session_id=self._session_id,
            sequence=self.next_sequence,
            kind=kind,
            context=context,
            payload=payload,
            artifact_refs=artifact_refs,
            previous_fact_digest=self.head_digest,
        )
        self._facts.append(fact)
        return fact

    @classmethod
    def replay_candidate(
        cls,
        session_id: str,
        facts: tuple[AgentTurnFact, ...],
    ) -> "AgentTurnFactBuffer":
        """Validate a fact chain reconstructed from authoritative machine facts."""

        buffer = cls(session_id)
        for expected_sequence, fact in enumerate(facts, start=1):
            if not isinstance(fact, AgentTurnFact):
                raise TypeError("agent turn replay requires AgentTurnFact values")
            if fact.session_id != session_id:
                raise ValueError("agent turn replay session mismatch")
            if fact.sequence != expected_sequence:
                raise ValueError("agent turn replay sequence is not contiguous")
            if fact.previous_fact_digest != buffer.head_digest:
                raise ValueError("agent turn replay digest chain is broken")
            buffer._facts.append(fact)
        return buffer


__all__ = ["AgentTurnFactBuffer"]
