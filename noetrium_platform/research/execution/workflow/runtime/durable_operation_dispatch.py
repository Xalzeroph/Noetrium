from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import TypeVar

from noetrium_platform.research.execution.operation.api import (
    OperationEffectCertainty, OperationEffectProfile, OperationFailure, OperationFailureKind,
    OperationId, OperationLifecyclePort, OperationSnapshot,
)
from noetrium_platform.research.execution.workflow.api import OperationExecutionPort
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity, EffectCertainty, ExecutionContext, OperationRequest, OperationResult, OperationStatus,
)

T=TypeVar("T"); R=TypeVar("R")


@dataclass(frozen=True,slots=True)
class DurableOperationExecution:
    operation: OperationSnapshot
    result: OperationResult


class DurableKernelOperationDispatcher:
    """Binds Kernel invocation mechanics to durable Execution operation truth.

    It requires an already ADMITTED/RECOVERING operation. It never performs admission,
    scheduling, reconciliation or hidden retry on behalf of those authorities.
    """
    def __init__(self,kernel:OperationExecutionPort,operations:OperationLifecyclePort)->None:
        self._kernel=kernel; self._operations=operations

    def execute(self,*,operation_id:OperationId,root_context:ExecutionContext,operation_type:str,
                target:ComponentIdentity,payload:T,payload_schema:str,handler:Callable[[OperationRequest[T]],R],
                digest_output:bool=True,effect_projector=None,idempotency_key:str|None=None)->DurableOperationExecution:
        running=self._operations.begin_execution(operation_id)
        result=self._kernel.execute(root_context=root_context,operation_id=operation_id.value,operation_type=operation_type,
            target=target,payload=payload,payload_schema=payload_schema,handler=handler,digest_output=digest_output,
            effect_projector=effect_projector,idempotency_key=idempotency_key)
        if result.status is not OperationStatus.SUCCEEDED:
            if running.effect_profile is OperationEffectProfile.NONE:
                failure=OperationFailure(OperationFailureKind.OPERATION_FAILURE,result.failure_id or "OPERATION_FAILED",
                                         "kernel operation failed",retryable=False,reconciliation_required=False)
                final=self._operations.fail(operation_id,failure)
            else:
                final=self._operations.mark_effect_unknown(operation_id)
            return DurableOperationExecution(final,result)
        final=self._complete_from_receipts(operation_id,running,result)
        return DurableOperationExecution(final,result)

    def _complete_from_receipts(self,operation_id:OperationId,running:OperationSnapshot,result:OperationResult)->OperationSnapshot:
        if running.effect_profile is OperationEffectProfile.NONE:
            if result.effect_receipts:
                raise RuntimeError("effect-free durable operation produced external effect receipts")
            return self._operations.complete(operation_id,result_digest=result.output_digest,
                                             effect_certainty=OperationEffectCertainty.NOT_EXECUTED)
        receipts=result.effect_receipts
        if len(receipts)!=1 or running.effect_id is None or receipts[0].effect_id!=running.effect_id.value:
            return self._operations.mark_effect_unknown(operation_id)
        receipt=receipts[0]
        if receipt.certainty is EffectCertainty.EFFECT_CONFIRMED:
            return self._operations.complete(operation_id,result_digest=result.output_digest,
                                             effect_certainty=OperationEffectCertainty.EXECUTED)
        if receipt.certainty in {EffectCertainty.NO_EFFECT,EffectCertainty.EFFECT_REJECTED}:
            return self._operations.complete(operation_id,result_digest=result.output_digest,
                                             effect_certainty=OperationEffectCertainty.NOT_EXECUTED)
        return self._operations.mark_effect_unknown(operation_id)


__all__=["DurableKernelOperationDispatcher","DurableOperationExecution"]
