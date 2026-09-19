from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext

from .contracts import FailureEnvelope, RecoveryAction, RiskLevel


_TUPLE_FIELDS = (
    "input_artifacts",
    "output_artifacts",
    "state_reads",
    "state_mutations",
    "request_refs",
    "effect_refs",
    "state_refs",
    "correlation_refs",
)


def failure_from_dict(data: dict[str, object]) -> FailureEnvelope:
    """Decode the current FailureEnvelope schema independently of storage backend."""

    raw = dict(data)
    raw["context"] = ExecutionContext(**dict(raw["context"]))  # type: ignore[arg-type]
    for name in _TUPLE_FIELDS:
        raw[name] = tuple(raw[name])  # type: ignore[arg-type]
    raw["data_integrity_risk"] = RiskLevel(raw["data_integrity_risk"])
    raw["comparability_risk"] = RiskLevel(raw["comparability_risk"])
    raw["scientific_validity_risk"] = RiskLevel(raw["scientific_validity_risk"])
    recovery = raw["recommended_recovery"]
    raw["recommended_recovery"] = RecoveryAction(recovery) if recovery is not None else None
    return FailureEnvelope(**raw)  # type: ignore[arg-type]


__all__ = ["failure_from_dict"]
