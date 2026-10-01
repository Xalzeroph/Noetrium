from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.model.serving.endpoint.api.pressure import (
    ModelRuntimePressureSnapshot,
)


@dataclass(frozen=True, slots=True)
class AdaptiveRequestWindowPolicy:
    min_limit: int = 1
    start_limit: int = 4
    decrease_factor: float = 0.8
    scale_up_percent: float = 0.05
    cooldown_seconds: float = 15.0
    latency_decrease_ratio: float = 1.5
    latency_decrease_streak: int = 3
    latency_ewma_alpha: float = 0.1
    kv_pressure_high_watermark: float = 0.90
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("min_limit", "start_limit"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"adaptive request window {name} must be positive integer")
        if self.start_limit < self.min_limit:
            raise ValueError("adaptive request window start_limit cannot be below min_limit")
        for name in (
            "decrease_factor",
            "scale_up_percent",
            "cooldown_seconds",
            "latency_decrease_ratio",
            "latency_ewma_alpha",
            "kv_pressure_high_watermark",
        ):
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
        if float(self.latency_decrease_ratio) <= 1.0:
            raise ValueError(
                "adaptive request window latency_decrease_ratio must exceed 1"
            )
        if (
            type(self.latency_decrease_streak) is not int
            or self.latency_decrease_streak <= 0
        ):
            raise ValueError(
                "adaptive request window latency_decrease_streak must be positive integer"
            )
        if not 0.0 < float(self.latency_ewma_alpha) <= 1.0:
            raise ValueError(
                "adaptive request window latency_ewma_alpha must be in (0,1]"
            )
        if not 0.0 < float(self.kv_pressure_high_watermark) < 1.0:
            raise ValueError(
                "adaptive request window kv_pressure_high_watermark must be in (0,1)"
            )
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
                    "latency_decrease_ratio": float(self.latency_decrease_ratio),
                    "latency_decrease_streak": self.latency_decrease_streak,
                    "latency_ewma_alpha": float(self.latency_ewma_alpha),
                    "kv_pressure_high_watermark": float(
                        self.kv_pressure_high_watermark
                    ),
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
        initial_limit: int | None = None,
        clock,
    ) -> None:
        if type(max_limit) is not int or max_limit <= 0:
            raise ValueError("adaptive request window max_limit must be positive")
        if not callable(clock):
            raise TypeError("adaptive request window clock must be callable")
        self._policy = policy or AdaptiveRequestWindowPolicy()
        self._max_limit = max_limit
        self._min_limit = min(self._policy.min_limit, max_limit)
        if initial_limit is not None and (
            type(initial_limit) is not int
            or initial_limit <= 0
            or initial_limit > max_limit
        ):
            raise ValueError(
                "adaptive request window initial_limit must be positive "
                "and cannot exceed max_limit"
            )
        start_limit = (
            self._policy.start_limit
            if initial_limit is None
            else initial_limit
        )
        self._limit = min(max_limit, max(self._min_limit, start_limit))
        self._clock = clock
        self._clean = 0
        self._last_rate_limit_at: float | None = None
        self._suspend_growth = False
        self._growth_resume_at: float | None = None
        self._service_time_ewma: float | None = None
        self._latency_decrease_streak = 0
        self._sequence = 0
        self._history = deque(maxlen=256)

    @property
    def limit(self) -> int:
        return self._limit

    def _suspend_growth_for_cooldown(self, now: float) -> None:
        self._suspend_growth = True
        resume_at = now + float(self._policy.cooldown_seconds)
        current = self._growth_resume_at
        if current is None or resume_at > current:
            self._growth_resume_at = resume_at

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
            self._suspend_growth_for_cooldown(now)
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
        self._suspend_growth_for_cooldown(now)
        self._record(old, self._limit, "rate_limit", now)

    def on_capacity_pressure(self) -> None:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")
        old = self._limit
        reduced = max(
            self._min_limit,
            int(math.floor(old * float(self._policy.decrease_factor))),
        )
        if reduced == old and old > self._min_limit:
            reduced = old - 1
        self._limit = reduced
        self._clean = 0
        self._suspend_growth_for_cooldown(now)
        self._record(old, self._limit, "capacity_pressure", now)

    def on_transient_failure(self) -> None:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")
        self._clean = 0
        self._suspend_growth_for_cooldown(now)

    def on_runtime_pressure(
        self,
        snapshot: ModelRuntimePressureSnapshot,
        *,
        previous_preemptions_total: int | None,
    ) -> None:
        if not isinstance(snapshot, ModelRuntimePressureSnapshot):
            raise TypeError(
                "adaptive request window pressure requires ModelRuntimePressureSnapshot"
            )
        if previous_preemptions_total is not None and (
            type(previous_preemptions_total) is not int
            or previous_preemptions_total < 0
        ):
            raise ValueError(
                "adaptive request window previous_preemptions_total must be non-negative"
            )
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")

        preemption_pressure = (
            previous_preemptions_total is not None
            and snapshot.preemptions_total > previous_preemptions_total
        )
        kv_queue_pressure = (
            snapshot.requests_waiting > 0
            and snapshot.gpu_kv_cache_usage
            >= float(self._policy.kv_pressure_high_watermark)
        )
        if preemption_pressure or kv_queue_pressure:
            old = self._limit
            reduced = max(
                self._min_limit,
                int(math.floor(
                    old * float(self._policy.decrease_factor)
                )),
            )
            if reduced == old and old > self._min_limit:
                reduced = old - 1
            self._limit = reduced
            self._clean = 0
            self._suspend_growth_for_cooldown(now)
            reason = (
                "engine_preemption"
                if preemption_pressure
                else "kv_queue_pressure"
            )
            self._record(old, self._limit, reason, now)
            return

        if (
            snapshot.requests_waiting > 0
            or snapshot.gpu_kv_cache_usage
            >= float(self._policy.kv_pressure_high_watermark)
        ):
            self._clean = 0
            self._suspend_growth_for_cooldown(now)

    def on_clean_completion(
        self,
        *,
        service_seconds_per_output_token: float | None = None,
        demand_pressure: bool = True,
    ) -> None:
        if type(demand_pressure) is not bool:
            raise TypeError(
                "adaptive request window demand_pressure must be boolean"
            )
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("adaptive request window clock must be finite")
        if service_seconds_per_output_token is not None:
            observed = float(service_seconds_per_output_token)
            if not math.isfinite(observed) or observed <= 0:
                raise ValueError(
                    "adaptive request window service time must be finite and positive"
                )
            baseline = self._service_time_ewma
            if (
                baseline is not None
                and observed
                > baseline * float(self._policy.latency_decrease_ratio)
            ):
                self._latency_decrease_streak += 1
            else:
                self._latency_decrease_streak = 0
            alpha = float(self._policy.latency_ewma_alpha)
            self._service_time_ewma = (
                observed
                if baseline is None
                else alpha * observed + (1.0 - alpha) * baseline
            )
            if (
                self._latency_decrease_streak
                >= self._policy.latency_decrease_streak
            ):
                old = self._limit
                reduced = max(
                    self._min_limit,
                    int(math.floor(
                        old * float(self._policy.decrease_factor)
                    )),
                )
                if reduced == old and old > self._min_limit:
                    reduced = old - 1
                self._limit = reduced
                self._latency_decrease_streak = 0
                self._clean = 0
                self._suspend_growth_for_cooldown(now)
                self._record(old, self._limit, "latency_pressure", now)
                return
        if self._suspend_growth:
            resume_at = self._growth_resume_at
            if resume_at is not None and now < resume_at:
                return
            self._suspend_growth = False
            self._growth_resume_at = None
        if not demand_pressure:
            self._clean = 0
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
