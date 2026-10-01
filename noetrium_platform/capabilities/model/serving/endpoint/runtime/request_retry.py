from __future__ import annotations

from dataclasses import dataclass, field
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(frozen=True, slots=True)
class ModelRequestRetryPolicy:
    max_attempts: int = 1
    retryable_failure_kinds: tuple[str, ...] = (
        "rate_limit",
        "capacity",
        "timeout",
        "transient",
    )
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 30.0
    honor_retry_after: bool = True
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise ValueError("model request retry max_attempts must be positive")
        if type(self.retryable_failure_kinds) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.retryable_failure_kinds
        ):
            raise TypeError("model request retry failure kinds must be text tuple")
        normalized=tuple(sorted(set(self.retryable_failure_kinds)))
        if len(normalized) != len(self.retryable_failure_kinds):
            raise ValueError("model request retry failure kinds must be unique")
        object.__setattr__(self,"retryable_failure_kinds",normalized)
        for name in ("base_backoff_seconds","max_backoff_seconds"):
            value=getattr(self,name)
            if (
                isinstance(value,bool)
                or not isinstance(value,(int,float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"model request retry {name} must be finite and non-negative")
        if float(self.max_backoff_seconds) < float(self.base_backoff_seconds):
            raise ValueError("model request retry max backoff cannot be below base backoff")
        if type(self.honor_retry_after) is not bool:
            raise TypeError("model request retry honor_retry_after must be bool")
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest({
                "schema":"noetrium.model-request-retry-policy.v1",
                "max_attempts":self.max_attempts,
                "retryable_failure_kinds":self.retryable_failure_kinds,
                "base_backoff_seconds":float(self.base_backoff_seconds),
                "max_backoff_seconds":float(self.max_backoff_seconds),
                "honor_retry_after":self.honor_retry_after,
            }),
        )

    def wait_seconds(
        self,
        *,
        attempt_number: int,
        retry_after_seconds: float | None,
    ) -> float:
        if type(attempt_number) is not int or attempt_number <= 0:
            raise ValueError("retry attempt_number must be positive")
        if self.honor_retry_after and retry_after_seconds is not None:
            return min(float(self.max_backoff_seconds), float(retry_after_seconds))
        delay=float(self.base_backoff_seconds) * (2 ** max(0,attempt_number-1))
        return min(float(self.max_backoff_seconds),delay)


__all__=["ModelRequestRetryPolicy"]
