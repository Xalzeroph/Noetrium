from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math

from .canonical import canonical_digest


@dataclass(frozen=True, slots=True)
class AdaptiveServiceWindowPolicy:
    """Boundary-only policy for parameter-free integer service-concurrency search."""

    min_limit: int = 1
    start_limit: int | None = None
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.min_limit) is not int or self.min_limit <= 0:
            raise ValueError("adaptive service window min_limit must be positive integer")
        if self.start_limit is not None:
            if type(self.start_limit) is not int or self.start_limit <= 0:
                raise ValueError(
                    "adaptive service window start_limit must be positive integer when provided"
                )
            if self.start_limit < self.min_limit:
                raise ValueError(
                    "adaptive service window start_limit cannot be below min_limit"
                )
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "schema": "noetrium.adaptive-service-window-policy.v1",
                    "min_limit": self.min_limit,
                    "start_limit": self.start_limit,
                    "control": (
                        "qualified-start-local-integer-search:"
                        "explicit-pressure-capacity:"
                        "measured-throughput-knee"
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class AdaptiveServiceWindowEvent:
    sequence: int
    old_limit: int
    new_limit: int
    reason: str
    observed_at: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("adaptive service window event sequence must be positive")
        for name in ("old_limit", "new_limit"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"adaptive service window event {name} must be positive"
                )
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("adaptive service window event reason is required")
        if not math.isfinite(float(self.observed_at)):
            raise ValueError(
                "adaptive service window event observed_at must be finite"
            )


@dataclass(frozen=True, slots=True)
class AdaptiveServiceWindowSnapshot:
    min_limit: int
    current_limit: int
    max_limit: int
    clean_completions: int
    scale_up_suspended: bool
    history: tuple[AdaptiveServiceWindowEvent, ...]
    policy_digest: str


class AdaptiveServiceWindow:
    """Parameter-free local search over integer service concurrency.

    With no prior measurement, sqrt(min*max) minimizes worst-case multiplicative
    distance to either feasible boundary. Runtime probes only c+1 after c clean
    completions at concurrency c. When normalized service time is available, the
    probe is retained only if c / mean(service_time) does not decrease.

    Explicit pressure decreases minimally, or directly to an observed physical
    service capacity when supplied. Saturation can suspend growth without
    changing the current limit. No empirical utilization threshold, EWMA,
    cooldown constant or multiplicative-decrease factor participates.
    """

    def __init__(
        self,
        *,
        max_limit: int,
        policy: AdaptiveServiceWindowPolicy | None = None,
        initial_limit: int | None = None,
        clock,
    ) -> None:
        if type(max_limit) is not int or max_limit <= 0:
            raise ValueError("adaptive service window max_limit must be positive")
        if not callable(clock):
            raise TypeError("adaptive service window clock must be callable")
        self._policy = policy or AdaptiveServiceWindowPolicy()
        self._max_limit = max_limit
        self._min_limit = min(self._policy.min_limit, max_limit)
        if initial_limit is not None and (
            type(initial_limit) is not int
            or initial_limit <= 0
            or initial_limit > max_limit
        ):
            raise ValueError(
                "adaptive service window initial_limit must be positive "
                "and cannot exceed max_limit"
            )
        if initial_limit is not None:
            start_limit = initial_limit
        elif self._policy.start_limit is not None:
            start_limit = self._policy.start_limit
        else:
            start_limit = max(
                self._min_limit,
                int(math.ceil(math.sqrt(self._min_limit * max_limit))),
            )
        self._limit = min(max_limit, max(self._min_limit, start_limit))
        self._clock = clock
        self._clean = 0
        self._suspend_growth = False
        self._sequence = 0
        self._history = deque(maxlen=256)
        self._service_sum = 0.0
        self._service_count = 0
        self._probe_parent_limit: int | None = None
        self._probe_parent_throughput: float | None = None

    @property
    def limit(self) -> int:
        return self._limit

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive service window clock must be finite")
        return now

    def _record(self, old: int, new: int, reason: str, now: float) -> None:
        if old == new:
            return
        self._sequence += 1
        self._history.append(
            AdaptiveServiceWindowEvent(
                sequence=self._sequence,
                old_limit=old,
                new_limit=new,
                reason=reason,
                observed_at=now,
            )
        )

    def _reset_window(self) -> None:
        self._clean = 0
        self._service_sum = 0.0
        self._service_count = 0

    def _clear_probe(self) -> None:
        self._probe_parent_limit = None
        self._probe_parent_throughput = None

    def on_pressure(
        self,
        *,
        reason: str,
        observed_capacity: int | None = None,
    ) -> None:
        if type(reason) is not str or not reason.strip():
            raise ValueError("adaptive service pressure reason is required")
        now = self._now()
        old = self._limit
        if old <= self._min_limit:
            self._reset_window()
            self._suspend_growth = True
            self._clear_probe()
            return
        target = old - 1
        if observed_capacity is not None:
            if type(observed_capacity) is not int or observed_capacity < 0:
                raise ValueError(
                    "observed service capacity must be non-negative integer"
                )
            if observed_capacity > 0:
                target = min(target, observed_capacity)
        self._limit = max(self._min_limit, target)
        self._reset_window()
        self._suspend_growth = True
        self._clear_probe()
        self._record(old, self._limit, reason.strip(), now)

    def on_saturation(self) -> None:
        self._now()
        self._reset_window()
        self._suspend_growth = True
        self._clear_probe()

    def on_transient_failure(self) -> None:
        self.on_saturation()

    def on_clean_completion(
        self,
        *,
        service_seconds_per_item: float | None = None,
        demand_pressure: bool = True,
    ) -> None:
        if type(demand_pressure) is not bool:
            raise TypeError(
                "adaptive service window demand_pressure must be boolean"
            )
        now = self._now()
        if service_seconds_per_item is not None:
            observed = float(service_seconds_per_item)
            if not math.isfinite(observed) or observed <= 0:
                raise ValueError(
                    "adaptive service window service time must be finite and positive"
                )
            self._service_sum += observed
            self._service_count += 1

        if not demand_pressure:
            self._reset_window()
            self._suspend_growth = False
            self._clear_probe()
            return

        self._clean += 1
        if self._clean < self._limit:
            return

        current_throughput = None
        if self._service_count > 0:
            mean_service = self._service_sum / self._service_count
            current_throughput = self._limit / mean_service

        parent = self._probe_parent_limit
        parent_throughput = self._probe_parent_throughput
        if (
            parent is not None
            and self._limit == parent + 1
            and current_throughput is not None
            and parent_throughput is not None
            and current_throughput < parent_throughput
        ):
            old = self._limit
            self._limit = max(self._min_limit, parent)
            self._reset_window()
            self._suspend_growth = True
            self._clear_probe()
            self._record(old, self._limit, "throughput_knee", now)
            return

        if self._suspend_growth:
            self._suspend_growth = False
            self._reset_window()
            self._clear_probe()
            return

        if self._limit >= self._max_limit:
            self._reset_window()
            self._clear_probe()
            return

        old = self._limit
        self._probe_parent_limit = old
        self._probe_parent_throughput = current_throughput
        self._limit = old + 1
        self._reset_window()
        self._record(old, self._limit, "clean_completion", now)

    def snapshot(self) -> AdaptiveServiceWindowSnapshot:
        return AdaptiveServiceWindowSnapshot(
            min_limit=self._min_limit,
            current_limit=self._limit,
            max_limit=self._max_limit,
            clean_completions=self._clean,
            scale_up_suspended=self._suspend_growth,
            history=tuple(self._history),
            policy_digest=self._policy.policy_digest,
        )


__all__ = [
    "AdaptiveServiceWindow",
    "AdaptiveServiceWindowEvent",
    "AdaptiveServiceWindowPolicy",
    "AdaptiveServiceWindowSnapshot",
]
