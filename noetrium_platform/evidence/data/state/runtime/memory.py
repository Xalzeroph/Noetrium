from __future__ import annotations
from threading import RLock
from noetrium_platform.evidence.data.state.api import AggregateValue, AtomicMutation, StateVersionConflict

class InMemoryAtomicStateStore:
    """Reference CAS store: all preconditions are checked before any mutation becomes visible."""
    def __init__(self, initial: tuple[AggregateValue, ...] = ()) -> None:
        self._values={x.aggregate_id:x for x in initial}
        self._lock=RLock()

    def read(self, aggregate_id: str) -> AggregateValue:
        with self._lock:
            try: return self._values[aggregate_id]
            except KeyError as exc: raise KeyError(f"unknown aggregate: {aggregate_id}") from exc

    def commit_batch(self, mutations: tuple[AtomicMutation, ...]) -> tuple[AggregateValue, ...]:
        with self._lock:
            if len({m.aggregate_id for m in mutations}) != len(mutations):
                raise ValueError("duplicate aggregate mutation in one atomic batch")
            for m in mutations:
                try: cur=self._values[m.aggregate_id]
                except KeyError as exc: raise KeyError(f"unknown aggregate: {m.aggregate_id}") from exc
                if cur.version != m.expected_version or cur.generation != m.expected_generation:
                    raise StateVersionConflict(
                        f"aggregate {m.aggregate_id} expected v{m.expected_version}/{m.expected_generation}, "
                        f"found v{cur.version}/{cur.generation}"
                    )
            out=[]
            for m in mutations:
                cur=self._values[m.aggregate_id]
                out.append(AggregateValue(m.aggregate_id,cur.version+1,m.new_generation,m.new_digest,m.new_payload))
            for value in out: self._values[value.aggregate_id]=value
            return tuple(out)

__all__=["InMemoryAtomicStateStore"]
