from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity


class RecoveryStep(StrEnum):
    VERIFY_ARTIFACTS = "verify_artifacts"
    VERIFY_LOG_CHAIN = "verify_log_chain"
    VERIFY_MODEL_IDENTITY = "verify_model_identity"
    VERIFY_HOST_INVENTORY = "verify_host_inventory"
    RECONCILE_PROCESS = "reconcile_process"
    RESTART_EXACT_MODEL = "restart_exact_model"
    WAIT_READY = "wait_ready"
    VERIFY_RUNTIME_QUALIFICATION = "verify_runtime_qualification"
    RECONCILE_RUN = "reconcile_run"
    RESUME_RUN_EXACT = "resume_run_exact"


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    source_run_id: str
    frozen_identity: ImmutableModelIdentity
    frozen_deployment_digest: str
    steps: tuple[RecoveryStep, ...]


__all__ = ["RecoveryPlan", "RecoveryStep"]
