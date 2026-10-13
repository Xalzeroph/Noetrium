from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_non_finite_json(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


_READY_PHASES = frozenset({"ready", "running", "succeeded", "complete", "completed"})
_FAILED_PHASES = frozenset({"failed", "failure", "error", "recovery_required", "crashed"})


class JsonStateStatusProbe:
    """Conservative read-only projection for external JSON phase records."""

    def __init__(self, subsystem: str, path: Path) -> None:
        self._subsystem = subsystem
        self._path = path

    def _snapshot(
        self,
        state: HealthState,
        summary: str,
        *,
        failure_id: str | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> SubsystemSnapshot:
        return SubsystemSnapshot(
            subsystem=self._subsystem,
            state=state,
            summary=summary,
            evidence=(str(self._path),),
            failure_id=failure_id,
            reason_codes=reason_codes,
        )

    def snapshot(self) -> SubsystemSnapshot:
        if not self._path.exists():
            return self._snapshot(
                HealthState.UNKNOWN,
                f"state record missing: {self._path}",
                reason_codes=("state_record_missing",),
            )
        try:
            payload = json.loads(
                self._path.read_text(encoding="utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_non_finite_json,
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return self._snapshot(
                HealthState.DEGRADED_EVIDENCE,
                f"state record cannot be decoded: {type(exc).__name__}",
                reason_codes=("state_record_invalid",),
            )
        if not isinstance(payload, dict):
            return self._snapshot(
                HealthState.DEGRADED_EVIDENCE,
                "state record must be a JSON object",
                reason_codes=("state_record_not_object",),
            )

        if "phase" in payload:
            phase_raw = payload["phase"]
        elif "state" in payload:
            phase_raw = payload["state"]
        else:
            return self._snapshot(
                HealthState.UNKNOWN,
                "state record has no phase/state field",
                reason_codes=("state_phase_missing",),
            )

        if not isinstance(phase_raw, str) or not phase_raw:
            return self._snapshot(
                HealthState.UNKNOWN,
                "state phase must be a non-empty string",
                reason_codes=("state_phase_invalid_type",),
            )
        phase = phase_raw
        if phase in _FAILED_PHASES:
            state = HealthState.FAILED
            reasons = [f"state_phase_{phase}"]
        elif phase in _READY_PHASES:
            state = HealthState.READY
            reasons = []
        else:
            return self._snapshot(
                HealthState.UNKNOWN,
                f"unrecognized state phase={phase}",
                reason_codes=("state_phase_unrecognized",),
            )

        failure_raw = payload.get("last_failure_id")
        failure_id = None
        if failure_raw is not None:
            if isinstance(failure_raw, str) and failure_raw.strip():
                failure_id = failure_raw
            else:
                reasons.append("state_failure_id_invalid")
                if state is HealthState.READY:
                    state = HealthState.DEGRADED_EVIDENCE

        return self._snapshot(
            state,
            f"phase={phase}",
            failure_id=failure_id,
            reason_codes=tuple(reasons),
        )


__all__ = ["JsonStateStatusProbe"]
