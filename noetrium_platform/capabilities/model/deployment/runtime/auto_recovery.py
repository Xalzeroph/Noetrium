from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.substrate.api import DirectoryLayoutPort, ManagedDirectoryKind


_SCHEMA = "model.auto-recovery-state.v2"


@dataclass(frozen=True, slots=True)
class ModelAutoRecoveryPolicy:
    max_attempts: int = 6
    window_seconds: float = 900.0
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 120.0
    stable_reset_seconds: float = 300.0
    attempt_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise ValueError("model auto-recovery max_attempts must be positive")
        for name in (
            "window_seconds",
            "base_backoff_seconds",
            "max_backoff_seconds",
            "stable_reset_seconds",
            "attempt_timeout_seconds",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(
                    f"model auto-recovery {name} must be finite and positive"
                )
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("model auto-recovery base backoff exceeds maximum")


@dataclass(frozen=True, slots=True)
class ModelAutoRecoveryState:
    deployment_id: str
    desired_spec_digest: str
    attempt_timestamps: tuple[float, ...] = ()
    active_claim_id: str | None = None
    active_claimed_at_epoch_s: float | None = None
    last_failure_digest: str | None = None
    same_failure_streak: int = 0
    next_retry_at_epoch_s: float | None = None
    circuit_open: bool = False
    running_since_epoch_s: float | None = None
    total_attempts: int = 0
    total_failures: int = 0
    circuit_trip_count: int = 0
    manual_reset_count: int = 0
    updated_at_epoch_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.deployment_id.strip():
            raise ValueError("model auto-recovery deployment_id required")
        _sha(self.desired_spec_digest, "desired_spec_digest")
        if self.active_claim_id is not None:
            _sha(self.active_claim_id, "active_claim_id")
            if self.active_claimed_at_epoch_s is None:
                raise ValueError(
                    "model auto-recovery active claim requires claimed timestamp"
                )
        elif self.active_claimed_at_epoch_s is not None:
            raise ValueError(
                "model auto-recovery claimed timestamp requires active claim"
            )
        if self.last_failure_digest is not None:
            _sha(self.last_failure_digest, "last_failure_digest")
        if self.same_failure_streak < 0:
            raise ValueError(
                "model auto-recovery same_failure_streak must be non-negative"
            )
        for name in (
            "total_attempts",
            "total_failures",
            "circuit_trip_count",
            "manual_reset_count",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(
                    f"model auto-recovery {name} must be non-negative"
                )
        if self.total_failures > self.total_attempts:
            raise ValueError(
                "model auto-recovery failures cannot exceed attempts"
            )
        for value in self.attempt_timestamps:
            _time_value(value, "attempt timestamp")
        for name in (
            "active_claimed_at_epoch_s",
            "next_retry_at_epoch_s",
            "running_since_epoch_s",
        ):
            value = getattr(self, name)
            if value is not None:
                _time_value(value, name)
        _time_value(self.updated_at_epoch_s, "updated_at_epoch_s")


@dataclass(frozen=True, slots=True)
class ModelAutoRecoveryDecision:
    allow: bool
    reason: str
    retry_after_seconds: float | None
    claim_id: str | None
    state: ModelAutoRecoveryState


def _sha(value: str, field: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            f"model auto-recovery {field} must be lowercase SHA-256"
        )


def _time_value(value: float, field: str) -> float:
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < 0:
        raise ValueError(
            f"model auto-recovery {field} must be finite and non-negative"
        )
    return resolved


class DurableModelAutoRecoveryAuthority:
    """Crash-durable bounded auto-restart circuit for model deployments.

    An automatic restart consumes budget *before* the external start effect. The
    durable active claim prevents concurrent controllers from starting the same
    desired generation twice and makes controller death consume one bounded
    attempt rather than resetting the budget.
    """

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        *,
        policy: ModelAutoRecoveryPolicy = ModelAutoRecoveryPolicy(),
        clock=time.time,
    ) -> None:
        self._policy = policy
        self._clock = clock
        state = directories.root(ManagedDirectoryKind.STATE)
        locks = directories.root(ManagedDirectoryKind.LOCKS)
        self._root = state / "model" / "deployments" / "auto-recovery"
        self._lock_root = locks / "model-auto-recovery"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(deployment_id: str) -> str:
        return hashlib.sha256(deployment_id.encode("utf-8")).hexdigest()

    def _path(self, deployment_id: str, desired_spec_digest: str) -> Path:
        return (
            self._root
            / f"{self._key(deployment_id)}.{desired_spec_digest}.json"
        )

    def _lock_path(self, deployment_id: str) -> Path:
        return self._lock_root / f"{self._key(deployment_id)}.lock"

    def _now(self) -> float:
        return _time_value(float(self._clock()), "clock")

    @staticmethod
    def _new(
        deployment_id: str,
        desired_spec_digest: str,
        now: float,
    ) -> ModelAutoRecoveryState:
        return ModelAutoRecoveryState(
            deployment_id=deployment_id,
            desired_spec_digest=desired_spec_digest,
            updated_at_epoch_s=now,
        )

    @staticmethod
    def _payload(state: ModelAutoRecoveryState) -> dict[str, object]:
        return {
            "deployment_id": state.deployment_id,
            "desired_spec_digest": state.desired_spec_digest,
            "attempt_timestamps": list(state.attempt_timestamps),
            "active_claim_id": state.active_claim_id,
            "active_claimed_at_epoch_s": state.active_claimed_at_epoch_s,
            "last_failure_digest": state.last_failure_digest,
            "same_failure_streak": state.same_failure_streak,
            "next_retry_at_epoch_s": state.next_retry_at_epoch_s,
            "circuit_open": state.circuit_open,
            "running_since_epoch_s": state.running_since_epoch_s,
            "total_attempts": state.total_attempts,
            "total_failures": state.total_failures,
            "circuit_trip_count": state.circuit_trip_count,
            "manual_reset_count": state.manual_reset_count,
            "updated_at_epoch_s": state.updated_at_epoch_s,
        }

    def _load_unlocked(
        self,
        deployment_id: str,
        desired_spec_digest: str,
        *,
        now: float,
    ) -> ModelAutoRecoveryState:
        path = self._path(deployment_id, desired_spec_digest)
        if not path.exists():
            return self._new(deployment_id, desired_spec_digest, now)
        decoded = decode_checksummed_document(
            path.read_bytes(),
            expected_schema=_SCHEMA,
        ).payload
        expected_fields = set(self._payload(
            self._new(deployment_id, desired_spec_digest, now)
        ))
        if set(decoded) != expected_fields:
            raise RuntimeError("model auto-recovery state schema drifted")
        if type(decoded["circuit_open"]) is not bool:
            raise RuntimeError(
                "model auto-recovery circuit_open must be boolean"
            )
        state = ModelAutoRecoveryState(
            deployment_id=str(decoded["deployment_id"]),
            desired_spec_digest=str(decoded["desired_spec_digest"]),
            attempt_timestamps=tuple(
                float(x) for x in decoded["attempt_timestamps"]
            ),
            active_claim_id=(
                None
                if decoded["active_claim_id"] is None
                else str(decoded["active_claim_id"])
            ),
            active_claimed_at_epoch_s=(
                None
                if decoded["active_claimed_at_epoch_s"] is None
                else float(decoded["active_claimed_at_epoch_s"])
            ),
            last_failure_digest=(
                None
                if decoded["last_failure_digest"] is None
                else str(decoded["last_failure_digest"])
            ),
            same_failure_streak=int(decoded["same_failure_streak"]),
            next_retry_at_epoch_s=(
                None
                if decoded["next_retry_at_epoch_s"] is None
                else float(decoded["next_retry_at_epoch_s"])
            ),
            circuit_open=decoded["circuit_open"],
            running_since_epoch_s=(
                None
                if decoded["running_since_epoch_s"] is None
                else float(decoded["running_since_epoch_s"])
            ),
            total_attempts=int(decoded["total_attempts"]),
            total_failures=int(decoded["total_failures"]),
            circuit_trip_count=int(decoded["circuit_trip_count"]),
            manual_reset_count=int(decoded["manual_reset_count"]),
            updated_at_epoch_s=float(decoded["updated_at_epoch_s"]),
        )
        if (
            state.deployment_id != deployment_id
            or state.desired_spec_digest != desired_spec_digest
        ):
            raise RuntimeError("model auto-recovery state identity drifted")
        return state

    def _write_unlocked(
        self,
        state: ModelAutoRecoveryState,
    ) -> ModelAutoRecoveryState:
        atomic_replace_bytes(
            self._path(state.deployment_id, state.desired_spec_digest),
            encode_checksummed_document(_SCHEMA, self._payload(state)),
        )
        return state

    def _recent(
        self,
        state: ModelAutoRecoveryState,
        now: float,
    ) -> tuple[float, ...]:
        return tuple(
            value
            for value in state.attempt_timestamps
            if now - value <= self._policy.window_seconds
        )

    def _claim_live(
        self,
        state: ModelAutoRecoveryState,
        now: float,
    ) -> bool:
        return (
            state.active_claim_id is not None
            and state.active_claimed_at_epoch_s is not None
            and now - state.active_claimed_at_epoch_s
            < self._policy.attempt_timeout_seconds
        )

    def claim_attempt(
        self,
        deployment_id: str,
        desired_spec_digest: str,
    ) -> ModelAutoRecoveryDecision:
        _sha(desired_spec_digest, "desired_spec_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            state = self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )
            recent = self._recent(state, now)

            if state.circuit_open:
                return ModelAutoRecoveryDecision(
                    False,
                    "auto-recovery-circuit-open",
                    None,
                    None,
                    state,
                )

            if self._claim_live(state, now):
                assert state.active_claimed_at_epoch_s is not None
                return ModelAutoRecoveryDecision(
                    False,
                    "auto-recovery-attempt-inflight",
                    max(
                        0.0,
                        self._policy.attempt_timeout_seconds
                        - (now - state.active_claimed_at_epoch_s),
                    ),
                    None,
                    state,
                )

            if len(recent) >= self._policy.max_attempts:
                tripped = ModelAutoRecoveryState(
                    deployment_id=state.deployment_id,
                    desired_spec_digest=state.desired_spec_digest,
                    attempt_timestamps=recent,
                    active_claim_id=None,
                    active_claimed_at_epoch_s=None,
                    last_failure_digest=state.last_failure_digest,
                    same_failure_streak=state.same_failure_streak,
                    next_retry_at_epoch_s=None,
                    circuit_open=True,
                    running_since_epoch_s=None,
                    total_attempts=state.total_attempts,
                    total_failures=state.total_failures,
                    circuit_trip_count=state.circuit_trip_count + 1,
                    manual_reset_count=state.manual_reset_count,
                    updated_at_epoch_s=now,
                )
                self._write_unlocked(tripped)
                return ModelAutoRecoveryDecision(
                    False,
                    "auto-recovery-attempt-budget-exhausted",
                    None,
                    None,
                    tripped,
                )

            retry_at = state.next_retry_at_epoch_s
            if retry_at is not None and retry_at > now:
                return ModelAutoRecoveryDecision(
                    False,
                    "auto-recovery-backoff",
                    retry_at - now,
                    None,
                    state,
                )

            ordinal = state.total_attempts + 1
            claim_id = canonical_digest({
                "deployment_id": deployment_id,
                "desired_spec_digest": desired_spec_digest,
                "attempt_ordinal": ordinal,
                "claimed_at_epoch_s": now,
            })
            claimed = ModelAutoRecoveryState(
                deployment_id=state.deployment_id,
                desired_spec_digest=state.desired_spec_digest,
                attempt_timestamps=recent + (now,),
                active_claim_id=claim_id,
                active_claimed_at_epoch_s=now,
                last_failure_digest=state.last_failure_digest,
                same_failure_streak=state.same_failure_streak,
                next_retry_at_epoch_s=None,
                circuit_open=False,
                running_since_epoch_s=None,
                total_attempts=ordinal,
                total_failures=state.total_failures,
                circuit_trip_count=state.circuit_trip_count,
                manual_reset_count=state.manual_reset_count,
                updated_at_epoch_s=now,
            )
            self._write_unlocked(claimed)
            return ModelAutoRecoveryDecision(
                True,
                "auto-recovery-attempt-claimed",
                None,
                claim_id,
                claimed,
            )

    @staticmethod
    def _require_claim(
        state: ModelAutoRecoveryState,
        claim_id: str,
    ) -> None:
        _sha(claim_id, "claim_id")
        if state.active_claim_id != claim_id:
            raise RuntimeError(
                "model auto-recovery claim is stale or no longer authoritative"
            )

    def record_failure(
        self,
        deployment_id: str,
        desired_spec_digest: str,
        claim_id: str,
        failure_digest: str,
    ) -> ModelAutoRecoveryState:
        _sha(desired_spec_digest, "desired_spec_digest")
        _sha(failure_digest, "failure_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            state = self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )
            self._require_claim(state, claim_id)
            streak = (
                state.same_failure_streak + 1
                if state.last_failure_digest == failure_digest
                else 1
            )
            recent = self._recent(state, now)
            opens = len(recent) >= self._policy.max_attempts
            delay = min(
                self._policy.max_backoff_seconds,
                self._policy.base_backoff_seconds
                * (2 ** min(streak - 1, 30)),
            )
            updated = ModelAutoRecoveryState(
                deployment_id=deployment_id,
                desired_spec_digest=desired_spec_digest,
                attempt_timestamps=recent,
                active_claim_id=None,
                active_claimed_at_epoch_s=None,
                last_failure_digest=failure_digest,
                same_failure_streak=streak,
                next_retry_at_epoch_s=None if opens else now + delay,
                circuit_open=opens,
                running_since_epoch_s=None,
                total_attempts=state.total_attempts,
                total_failures=state.total_failures + 1,
                circuit_trip_count=(
                    state.circuit_trip_count
                    + (1 if opens and not state.circuit_open else 0)
                ),
                manual_reset_count=state.manual_reset_count,
                updated_at_epoch_s=now,
            )
            return self._write_unlocked(updated)

    def record_attempt_success(
        self,
        deployment_id: str,
        desired_spec_digest: str,
        claim_id: str,
    ) -> ModelAutoRecoveryState:
        _sha(desired_spec_digest, "desired_spec_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            state = self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )
            self._require_claim(state, claim_id)
            updated = ModelAutoRecoveryState(
                deployment_id=deployment_id,
                desired_spec_digest=desired_spec_digest,
                attempt_timestamps=self._recent(state, now),
                active_claim_id=None,
                active_claimed_at_epoch_s=None,
                last_failure_digest=state.last_failure_digest,
                same_failure_streak=state.same_failure_streak,
                next_retry_at_epoch_s=None,
                circuit_open=state.circuit_open,
                running_since_epoch_s=now,
                total_attempts=state.total_attempts,
                total_failures=state.total_failures,
                circuit_trip_count=state.circuit_trip_count,
                manual_reset_count=state.manual_reset_count,
                updated_at_epoch_s=now,
            )
            return self._write_unlocked(updated)

    def record_running(
        self,
        deployment_id: str,
        desired_spec_digest: str,
    ) -> ModelAutoRecoveryState:
        """Observe physical RUNNING and heal only after a stable window."""

        _sha(desired_spec_digest, "desired_spec_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            state = self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )
            running_since = state.running_since_epoch_s or now
            stable = now - running_since >= self._policy.stable_reset_seconds
            updated = ModelAutoRecoveryState(
                deployment_id=deployment_id,
                desired_spec_digest=desired_spec_digest,
                attempt_timestamps=(
                    () if stable else self._recent(state, now)
                ),
                active_claim_id=None,
                active_claimed_at_epoch_s=None,
                last_failure_digest=(
                    None if stable else state.last_failure_digest
                ),
                same_failure_streak=(
                    0 if stable else state.same_failure_streak
                ),
                next_retry_at_epoch_s=None,
                circuit_open=False if stable else state.circuit_open,
                running_since_epoch_s=running_since,
                total_attempts=state.total_attempts,
                total_failures=state.total_failures,
                circuit_trip_count=state.circuit_trip_count,
                manual_reset_count=state.manual_reset_count,
                updated_at_epoch_s=now,
            )
            return self._write_unlocked(updated)

    def reset(
        self,
        deployment_id: str,
        desired_spec_digest: str,
    ) -> ModelAutoRecoveryState:
        _sha(desired_spec_digest, "desired_spec_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            state = self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )
            if self._claim_live(state, now):
                raise RuntimeError(
                    "cannot reset model auto-recovery while an attempt is active"
                )
            updated = ModelAutoRecoveryState(
                deployment_id=deployment_id,
                desired_spec_digest=desired_spec_digest,
                attempt_timestamps=(),
                active_claim_id=None,
                active_claimed_at_epoch_s=None,
                last_failure_digest=None,
                same_failure_streak=0,
                next_retry_at_epoch_s=None,
                circuit_open=False,
                running_since_epoch_s=None,
                total_attempts=state.total_attempts,
                total_failures=state.total_failures,
                circuit_trip_count=state.circuit_trip_count,
                manual_reset_count=state.manual_reset_count + 1,
                updated_at_epoch_s=now,
            )
            return self._write_unlocked(updated)

    def state(
        self,
        deployment_id: str,
        desired_spec_digest: str,
    ) -> ModelAutoRecoveryState:
        _sha(desired_spec_digest, "desired_spec_digest")
        now = self._now()
        with InterprocessFileLock(self._lock_path(deployment_id)):
            return self._load_unlocked(
                deployment_id,
                desired_spec_digest,
                now=now,
            )


__all__ = [
    "DurableModelAutoRecoveryAuthority",
    "ModelAutoRecoveryDecision",
    "ModelAutoRecoveryPolicy",
    "ModelAutoRecoveryState",
]
