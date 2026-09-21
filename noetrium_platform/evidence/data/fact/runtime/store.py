from __future__ import annotations

from threading import RLock

from noetrium_platform.evidence.data._canonical import canonical_digest
from noetrium_platform.evidence.data.fact.api import (
    DurableFact,
    DurableFactConflict,
    DurableFactNotFound,
    DurableFactReceipt,
)


def _fact_digest(fact: DurableFact) -> str:
    return canonical_digest(
        {
            "fact_id": fact.fact_id,
            "fact_type": fact.fact_type,
            "schema_version": fact.schema_version,
            "criticality": fact.criticality.value,
            "payload": dict(fact.payload),
            "artifact_refs": fact.artifact_refs,
            "state_refs": fact.state_refs,
        }
    )


class InMemoryDurableFactStore:
    """Process-local implementation of the durable-fact contract for tests/composition."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._rows: dict[str, tuple[int, DurableFact, str]] = {}
        self._next_sequence = 1

    def append(self, fact: DurableFact) -> DurableFactReceipt:
        if not isinstance(fact, DurableFact):
            raise TypeError("durable fact store requires DurableFact")
        digest = _fact_digest(fact)
        with self._lock:
            current = self._rows.get(fact.fact_id)
            if current is not None:
                sequence, existing, existing_digest = current
                if existing != fact or existing_digest != digest:
                    raise DurableFactConflict(fact.fact_id)
                return DurableFactReceipt(fact.fact_id, sequence, digest)
            sequence = self._next_sequence
            self._next_sequence += 1
            self._rows[fact.fact_id] = (sequence, fact, digest)
            return DurableFactReceipt(fact.fact_id, sequence, digest)

    def get(self, fact_id: str) -> DurableFact:
        with self._lock:
            try:
                return self._rows[fact_id][1]
            except KeyError as exc:
                raise DurableFactNotFound(fact_id) from exc

    def count(self) -> int:
        with self._lock:
            return len(self._rows)


__all__ = ["InMemoryDurableFactStore"]
