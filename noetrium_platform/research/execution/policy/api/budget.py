from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


def _positive_int(value: int | None, name: str) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError(f"{name} must be a positive integer or None")


def _positive_real(value: float | None, name: str) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or float(value) <= 0.0
    ):
        raise ValueError(f"{name} must be positive numeric or None")


@dataclass(frozen=True, slots=True)
class ExecutionBudgetPolicy:
    scope_id: str
    budget_id: str
    budget_digest: str
    replay_level: str
    max_steps: int | None = None
    max_seconds: float | None = None
    max_tokens: int | None = None
    resource_budget_digest: str | None = None
    max_turns: int | None = None
    max_messages: int | None = None
    max_model_calls: int | None = None
    max_working_seconds: float | None = None
    max_cost_usd: float | None = None
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("scope_id", "budget_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"execution budget {name} must be non-empty text")
        require_sha256(self.budget_digest, "execution budget budget_digest")
        if self.replay_level not in {"exact", "checkpoint", "observational"}:
            raise ValueError("execution budget replay_level is invalid")
        for name in (
            "max_steps",
            "max_tokens",
            "max_turns",
            "max_messages",
            "max_model_calls",
        ):
            _positive_int(getattr(self, name), f"execution budget {name}")
        for name in ("max_seconds", "max_working_seconds", "max_cost_usd"):
            _positive_real(getattr(self, name), f"execution budget {name}")
        if self.resource_budget_digest is not None:
            require_sha256(
                self.resource_budget_digest,
                "execution budget resource_budget_digest",
            )
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "schema": "noetrium.execution-budget-policy.v1",
                    "scope_id": self.scope_id,
                    "budget_id": self.budget_id,
                    "budget_digest": self.budget_digest,
                    "replay_level": self.replay_level,
                    "max_steps": self.max_steps,
                    "max_seconds": self.max_seconds,
                    "max_tokens": self.max_tokens,
                    "resource_budget_digest": self.resource_budget_digest,
                    "max_turns": self.max_turns,
                    "max_messages": self.max_messages,
                    "max_model_calls": self.max_model_calls,
                    "max_working_seconds": self.max_working_seconds,
                    "max_cost_usd": self.max_cost_usd,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionBudgetDelta:
    steps: int = 0
    turns: int = 0
    messages: int = 0
    model_calls: int = 0
    tokens: int = 0
    working_seconds: float = 0.0
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        for name in ("steps", "turns", "messages", "model_calls", "tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"execution budget delta {name} must be non-negative")
        for name in ("working_seconds", "cost_usd"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) < 0.0
            ):
                raise ValueError(
                    f"execution budget delta {name} must be non-negative numeric"
                )

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ExecutionBudgetSnapshot:
    scope_id: str
    policy_digest: str
    usage: ExecutionBudgetDelta
    reserved: ExecutionBudgetDelta
    started_unix_ns: int
    admission_digest: str
    replay_proof_digest: str
    resource_policy_digest: str
    cost_accounting_digest: str | None

    def __post_init__(self) -> None:
        if type(self.scope_id) is not str or not self.scope_id.strip():
            raise ValueError("execution budget snapshot scope_id is required")
        for name in (
            "policy_digest",
            "admission_digest",
            "replay_proof_digest",
            "resource_policy_digest",
        ):
            require_sha256(getattr(self, name), f"execution budget snapshot {name}")
        if self.cost_accounting_digest is not None:
            require_sha256(
                self.cost_accounting_digest,
                "execution budget snapshot cost_accounting_digest",
            )
        if not isinstance(self.usage, ExecutionBudgetDelta):
            raise TypeError("execution budget snapshot usage must be typed")
        if not isinstance(self.reserved, ExecutionBudgetDelta):
            raise TypeError("execution budget snapshot reserved must be typed")
        if type(self.started_unix_ns) is not int or self.started_unix_ns <= 0:
            raise ValueError("execution budget snapshot started_unix_ns is invalid")


@dataclass(frozen=True, slots=True)
class ExecutionBudgetReservationRequest:
    charge_id: str
    requested: ExecutionBudgetDelta

    def __post_init__(self) -> None:
        if type(self.charge_id) is not str or not self.charge_id.strip():
            raise ValueError(
                "execution budget reservation request charge_id is required"
            )
        if not isinstance(self.requested, ExecutionBudgetDelta):
            raise TypeError(
                "execution budget reservation request delta must be typed"
            )


@dataclass(frozen=True, slots=True)
class ExecutionBudgetReservation:
    scope_id: str
    charge_id: str
    requested: ExecutionBudgetDelta
    reservation_digest: str

    def __post_init__(self) -> None:
        for name in ("scope_id", "charge_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"execution budget reservation {name} is required")
        if not isinstance(self.requested, ExecutionBudgetDelta):
            raise TypeError("execution budget reservation delta must be typed")
        require_sha256(
            self.reservation_digest,
            "execution budget reservation digest",
        )


class ExecutionBudgetExceeded(RuntimeError):
    pass


@runtime_checkable
class ExecutionBudgetAuthorityPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def open_scope(
        self,
        policy: ExecutionBudgetPolicy,
    ) -> ExecutionBudgetSnapshot: ...

    def snapshot(self, scope_id: str) -> ExecutionBudgetSnapshot: ...

    def require_active(self, scope_id: str) -> ExecutionBudgetSnapshot: ...

    def reserve(
        self,
        scope_id: str,
        charge_id: str,
        requested: ExecutionBudgetDelta,
    ) -> ExecutionBudgetReservation: ...

    def reserve_batch(
        self,
        scope_id: str,
        requests: tuple[ExecutionBudgetReservationRequest, ...],
    ) -> tuple[ExecutionBudgetReservation, ...]: ...

    def commit(
        self,
        reservation: ExecutionBudgetReservation,
        actual: ExecutionBudgetDelta,
    ) -> tuple[ExecutionBudgetSnapshot, tuple[str, ...]]: ...

    def abort(
        self,
        reservation: ExecutionBudgetReservation,
    ) -> ExecutionBudgetSnapshot: ...

    def consume(
        self,
        scope_id: str,
        charge_id: str,
        actual: ExecutionBudgetDelta,
    ) -> ExecutionBudgetSnapshot: ...


__all__ = [
    "ExecutionBudgetAuthorityPort",
    "ExecutionBudgetDelta",
    "ExecutionBudgetExceeded",
    "ExecutionBudgetPolicy",
    "ExecutionBudgetReservation",
    "ExecutionBudgetReservationRequest",
    "ExecutionBudgetSnapshot",
]
