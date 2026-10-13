from __future__ import annotations

from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.foundation.kernel.kernel.canonical import canonical_text


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryAction(StrEnum):
    RETRY_OPERATION = "retry_operation"
    RECONCILE_EFFECT = "reconcile_effect"
    RECONCILE_METHOD_STATE = "reconcile_method_state"
    COMMIT_ONLY = "commit_only"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    REBUILD_DERIVED_STATE = "rebuild_derived_state"
    RESTART_COMPONENT = "restart_component"
    RESTART_EXACT_MODEL = "restart_exact_model"
    QUARANTINE_RUN = "quarantine_run"
    BLOCK_SCIENTIFIC_USE = "block_scientific_use"
    MANUAL_DIAGNOSIS = "manual_diagnosis"
    REPLAY_OBSERVATION = "replay_observation"
    REPLAN_ACTION = "replan_action"

__all__ = ["RecoveryAction", "RiskLevel"]
