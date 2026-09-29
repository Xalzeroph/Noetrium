from __future__ import annotations

from dataclasses import dataclass, field
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(frozen=True, slots=True)
class AdaptiveRequestWindowPolicy:
    min_limit: int = 1
    start_limit: int = 4
    decrease_factor: float = 0.8
    scale_up_percent: float = 0.05
    cooldown_seconds: float = 15.0
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("min_limit", "start_limit"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"adaptive request window {name} must be positive integer")
        if self.start_limit < self.min_limit:
            raise ValueError("adaptive request window start_limit cannot be below min_limit")
        for name in ("decrease_factor", "scale_up_percent", "cooldown_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"adaptive request window {name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"adaptive request window {name} must be finite")
        if not 0.0 < float(self.decrease_factor) < 1.0:
            raise ValueError("adaptive request window decrease_factor must be in (0,1)")
        if float(self.scale_up_percent) <= 0:
            raise ValueError("adaptive request window scale_up_percent must be positive")
        if float(self.cooldown_seconds) < 0:
            raise ValueError("adaptive request window cooldown_seconds must be non-negative")
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(
                {
                    "schema": "noetrium.adaptive-request-window-policy.v1",
                    "min_limit": self.min_limit,
                    "start_limit": self.start_limit,
                    "decrease_factor": float(self.decrease_factor),
                    "scale_up_percent": float(self.scale_up_percent),
                    "cooldown_seconds": float(self.cooldown_seconds),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class AdaptiveRequestWindowEvent:
    sequence: int
    old_limit: int
    new_limit: int
    reason: str
    observed_at: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("adaptive request window event sequence must be positive")
        for name in ("old_limit", "new_limit"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"adaptive request window event {name} must be positive")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("adaptive request window event reason is required")
        if not math.isfinite(float(self.observed_at)):
            raise ValueError("adaptive request window event observed_at must be finite")


@dataclass(frozen=True, slots=True)
class AdaptiveRequestWindowSnapshot:
    min_limit: int
    current_limit: int
    max_limit: int
    clean_completions: int
    last_rate_limit_at: float | None
    scale_up_suspended: bool
    history: tuple[AdaptiveRequestWindowEvent, ...]
    policy_digest: str


class AdaptiveRequestWindow:
    """Deterministic AIMD-style request window bounded by qualified capacity.

    Rate limits reduce the window. Transient infrastructure failures suspend
    growth without reducing it. Clean completions grow the window. The
    controller never exceeds the deployment-qualified maximum.
    """

    def __init__(
        self,
        *,
        max_limit: int,
        policy: AdaptiveRequestWindowPolicy | None = None,
        clock,
    ) -> None:
        if type(max_limit) is not int or max_limit <= 0:
            raise ValueError("adaptive request window max_limit must be positive")
        if not callable(clock):
            raise TypeError("adaptive request window clock must be callable")
        self._policy = policy or AdaptiveRequestWindowPolicy()
        self._max_limit = max_limit
        self._min_limit = min(self._policy.min_limit, max_limit)
        self._limit = min(max_limit, max(self._min_limit, self._policy.start_limit))
        self._clock = clock
        self._clean = 0
        self._last_rate_limit_at: float | None = None
        self._suspend_growth = False
        self._sequence = 0
        self._history: list[AdaptiveRequestWindowEvent] = []

    @property
    def limit(self) -> int:
        return self._limit

    def _record(self, old: int, new: int, reason: str, now: float) -> None:
        if old == new:
            return
        self._sequence += 1
        self._history.append(
            AdaptiveRequestWindowEvent(
                sequence=self._sequence,
                old_limit=old,
                new_limit=new,
                reason=reason,
                observed_at=float(now),
            )
        )

    def on_rate_limit(self) -> None:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")
        cooldown = float(self._policy.cooldown_seconds)
        if (
            self._last_rate_limit_at is not None
            and now - self._last_rate_limit_at < cooldown
        ):
            self._clean = 0
            self._suspend_growth = True
            return
        old = self._limit
        reduced = max(
            self._min_limit,
            int(math.floor(old * float(self._policy.decrease_factor))),
        )
        if reduced == old and old > self._min_limit:
            reduced = old - 1
        self._limit = reduced
        self._last_rate_limit_at = now
        self._clean = 0
        self._suspend_growth = True
        self._record(old, self._limit, "rate_limit", now)

    def on_transient_failure(self) -> None:
        self._clean = 0
        self._suspend_growth = True

    def on_clean_completion(self) -> None:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")
        if self._suspend_growth:
            if (
                self._last_rate_limit_at is None
                or now - self._last_rate_limit_at >= float(self._policy.cooldown_seconds)
            ):
                self._suspend_growth = False
            else:
                return
        self._clean += 1
        threshold = max(1, self._limit)
        if self._clean < threshold:
            return
        self._clean = 0
        old = self._limit
        step = max(1, int(math.ceil(old * float(self._policy.scale_up_percent))))
        self._limit = min(self._max_limit, old + step)
        self._record(old, self._limit, "clean_completion", now)

    def snapshot(self) -> AdaptiveRequestWindowSnapshot:
        return AdaptiveRequestWindowSnapshot(
            min_limit=self._min_limit,
            current_limit=self._limit,
            max_limit=self._max_limit,
            clean_completions=self._clean,
            last_rate_limit_at=self._last_rate_limit_at,
            scale_up_suspended=self._suspend_growth,
            history=tuple(self._history),
            policy_digest=self._policy.policy_digest,
        )


__all__ = [
    "AdaptiveRequestWindow",
    "AdaptiveRequestWindowEvent",
    "AdaptiveRequestWindowPolicy",
    "AdaptiveRequestWindowSnapshot",
]
