from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol
import uuid


@dataclass(frozen=True, slots=True)
class DecisionCycleIdentity:
    """Stable identity for one trial decision cycle.

    Exact recovery must reuse this object.  It deliberately contains no method or
    environment state; those identities are frozen independently by ``ExperimentSpec``.
    """

    run_id: str
    decision_cycle_id: str
    session_id: str
    task_id: str
    trace_id: str

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if not isinstance(value, str):
                raise TypeError(f"DecisionCycleIdentity.{field_name} must be text")
            resolved = value.strip()
            if not resolved:
                raise ValueError(f"DecisionCycleIdentity.{field_name} must be non-empty")
            object.__setattr__(self, field_name, resolved)

    def digest(self) -> str:
        raw = json.dumps(
            asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
        return hashlib.sha256(raw).hexdigest()


class DecisionCycleIdentityProvider(Protocol):
    def allocate(self) -> DecisionCycleIdentity: ...


class RandomDecisionCycleIdentityProvider:
    """Allocates fresh identities for new runs.

    Exact recovery injects/reuses a previously frozen identity instead of allocating.
    """

    def allocate(self) -> DecisionCycleIdentity:
        run_id = f"run_{uuid.uuid4().hex}"
        decision_cycle_id = f"dc_{uuid.uuid4().hex}"
        return DecisionCycleIdentity(
            run_id=run_id,
            decision_cycle_id=decision_cycle_id,
            session_id=f"session_{uuid.uuid4().hex}",
            task_id="task_1",
            trace_id=run_id,
        )


class FixedDecisionCycleIdentityProvider:
    """Exact-recovery provider: always returns the caller-frozen identity."""

    def __init__(self, identity: DecisionCycleIdentity) -> None:
        self.identity = identity

    def allocate(self) -> DecisionCycleIdentity:
        return self.identity


__all__ = [
    "FixedDecisionCycleIdentityProvider",
    "RandomDecisionCycleIdentityProvider",
    "DecisionCycleIdentity",
    "DecisionCycleIdentityProvider",
]
