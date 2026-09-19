from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext


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


@dataclass(frozen=True, slots=True)
class FailureEnvelope:
    failure_id: str
    created_at: float
    component_id: str
    operation_id: str | None
    operation_invocation_id: str | None
    operation_type: str | None
    failure_domain: str
    failure_code: str
    stage: str
    context: ExecutionContext
    cause_type: str
    cause_message: str
    cause_chain_digest: str
    retryability: str
    recoverability: str
    data_integrity_risk: RiskLevel
    comparability_risk: RiskLevel
    scientific_validity_risk: RiskLevel
    operation_payload_digest: str | None = None
    operation_idempotency_key: str | None = None
    taxonomy_spec_sha256: str | None = None
    mutation_phase: str | None = None
    effect_certainty: str | None = None
    input_artifacts: tuple[str, ...] = ()
    output_artifacts: tuple[str, ...] = ()
    state_reads: tuple[str, ...] = ()
    state_mutations: tuple[str, ...] = ()
    request_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    recommended_recovery: RecoveryAction | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
