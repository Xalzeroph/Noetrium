from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RecoveryActionCode(StrEnum):
    NONE = "none"
    VERIFY_EVIDENCE = "verify_evidence"
    REBUILD_DERIVED_STATE = "rebuild_derived_state"
    RECONCILE_RUNTIME_HISTORY = "reconcile_runtime_history"
    RECONCILE_RUNTIME_TRANSACTION = "reconcile_runtime_transaction"
    RECONCILE_RECOVERY_OWNERSHIP = "reconcile_recovery_ownership"
    RECONCILE_PERSISTENT_SESSION = "reconcile_persistent_session"
    RECONCILE_SESSION_CONTROL = "reconcile_session_control"
    RECONCILE_SERVICE_START = "reconcile_service_start"
    RECONCILE_SERVICE = "reconcile_service"
    RECONCILE_MODEL_SERVICE = "reconcile_model_service"
    BLOCK_IDENTITY_DRIFT = "block_identity_drift"
    MANUAL_DIAGNOSIS = "manual_diagnosis"


class RecoveryAutomation(StrEnum):
    SAFE = "safe"
    CONDITIONAL = "conditional"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class RecoveryRecommendation:
    subsystem: str
    action: RecoveryActionCode
    automation: RecoveryAutomation
    reason_codes: tuple[str, ...]
    required_checks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subsystem:
            raise ValueError("recovery recommendation subsystem required")
        if not self.reason_codes and self.action is not RecoveryActionCode.NONE:
            raise ValueError("non-trivial recovery recommendation requires reason codes")
        if self.automation is RecoveryAutomation.SAFE and self.required_checks:
            raise ValueError("safe automatic recovery cannot depend on unresolved checks")
        if self.action is RecoveryActionCode.BLOCK_IDENTITY_DRIFT and self.automation is not RecoveryAutomation.FORBIDDEN:
            raise ValueError("identity drift must fail closed")


@dataclass(frozen=True, slots=True)
class RecoveryDecisionReport:
    recommendations: tuple[RecoveryRecommendation, ...]

    @property
    def blocked(self) -> tuple[RecoveryRecommendation, ...]:
        return tuple(item for item in self.recommendations if item.automation is RecoveryAutomation.FORBIDDEN)

    @property
    def safe(self) -> tuple[RecoveryRecommendation, ...]:
        return tuple(item for item in self.recommendations if item.automation is RecoveryAutomation.SAFE)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "recovery-decision.v1",
            "blocked": bool(self.blocked),
            "recommendations": [
                {
                    "subsystem": item.subsystem,
                    "action": item.action.value,
                    "automation": item.automation.value,
                    "reason_codes": list(item.reason_codes),
                    "required_checks": list(item.required_checks),
                }
                for item in self.recommendations
            ],
        }


__all__ = [
    "RecoveryActionCode",
    "RecoveryAutomation",
    "RecoveryDecisionReport",
    "RecoveryRecommendation",
]
