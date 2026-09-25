from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity

from ..api.recovery import RecoveryPlan, RecoveryStep
from ..api.state import ModelRunState


class RecoveryPlanner:
    def plan(
        self,
        state: ModelRunState,
        requested_identity: ImmutableModelIdentity,
        requested_deployment_digest: str,
    ) -> RecoveryPlan:
        if state.identity.resume_key() != requested_identity.resume_key():
            raise ValueError("recovery refuses model/engine/precision/context identity drift")
        if state.deployment_digest != requested_deployment_digest:
            raise ValueError("recovery refuses qualified deployment stack/certificate/placement drift")
        return RecoveryPlan(
            source_run_id=state.run_id,
            frozen_identity=state.identity,
            frozen_deployment_digest=state.deployment_digest,
            steps=(
                RecoveryStep.VERIFY_ARTIFACTS,
                RecoveryStep.VERIFY_LOG_CHAIN,
                RecoveryStep.VERIFY_MODEL_IDENTITY,
                RecoveryStep.VERIFY_HOST_INVENTORY,
                RecoveryStep.RECONCILE_PROCESS,
                RecoveryStep.RESTART_EXACT_MODEL,
                RecoveryStep.WAIT_READY,
                RecoveryStep.VERIFY_RUNTIME_QUALIFICATION,
                RecoveryStep.RECONCILE_RUN,
                RecoveryStep.RESUME_RUN_EXACT,
            ),
        )


__all__ = ["RecoveryPlanner"]
