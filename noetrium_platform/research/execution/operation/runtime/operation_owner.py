from __future__ import annotations
import time
from noetrium_platform.research.execution.command.api import CommandId
from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationProof
from noetrium_platform.research.execution.operation.api import (EffectId,OperationEffectCertainty,OperationEffectProfile,OperationFailure,
    OperationFailureKind,OperationId,OperationSnapshot,OperationState,OperationStorePort,revise_operation,transition_operation,
    EffectReconciliationOutcome,project_effect_reconciliation)

class OperationOwner:
    """Single authority for operation identity, state and crash classification."""
    def __init__(self,store:OperationStorePort)->None: self._store=store
    @property
    def durability(self)->str: return self._store.durability
    def submit(self,command_id:CommandId,*,operation_id:OperationId,parent_operation_id:OperationId|None=None,
               effect_profile:OperationEffectProfile=OperationEffectProfile.NONE,effect_id:EffectId|None=None,
               effect_request_id:str|None=None,effect_request_digest:str|None=None,
               now_unix:float|None=None)->tuple[OperationSnapshot,bool]:
        created_at=time.time() if now_unix is None else now_unix
        snapshot=OperationSnapshot(operation_id,command_id,OperationState.CREATED,0,created_at,created_at,
                                   parent_operation_id,effect_id,effect_profile,
                                   effect_request_id=effect_request_id,effect_request_digest=effect_request_digest)
        return self._store.create_or_get(snapshot)
    def require(self,operation_id:OperationId)->OperationSnapshot:
        snapshot=self._store.load(operation_id)
        if snapshot is None: raise KeyError(f"operation not found: {operation_id.value}")
        return snapshot
    def _transition_from(self,current:OperationSnapshot,target:OperationState,*,now_unix:float|None=None,**changes)->OperationSnapshot:
        updated=transition_operation(current,target,now_unix=now_unix,**changes)
        return self._store.compare_and_swap(current.version,updated)
    def _revise_from(self,current:OperationSnapshot,*,now_unix:float|None=None,**changes)->OperationSnapshot:
        updated=revise_operation(current,now_unix=now_unix,**changes)
        return self._store.compare_and_swap(current.version,updated)
    def queue(self,operation_id:OperationId,*,now_unix:float|None=None)->OperationSnapshot:
        return self._transition_from(self.require(operation_id),OperationState.QUEUED,now_unix=now_unix)
    def admit(self,operation_id:OperationId,*,now_unix:float|None=None)->OperationSnapshot:
        current=self.require(operation_id)
        if current.state not in {OperationState.CREATED,OperationState.QUEUED}:
            raise RuntimeError(f"operation is not admissible from state: {current.state.value}")
        return self._transition_from(current,OperationState.ADMITTED,now_unix=now_unix)
    def begin_execution(self,operation_id:OperationId)->OperationSnapshot:
        current=self.require(operation_id)
        if current.cancellation_requested:
            raise RuntimeError("cancelled operation cannot begin or resume execution")
        if current.state is OperationState.RECOVERING and current.effect_certainty is not OperationEffectCertainty.NOT_EXECUTED:
            raise RuntimeError("recovered external effect must be reconciled as not executed before retry")
        if current.state not in {OperationState.ADMITTED,OperationState.RECOVERING}:
            raise RuntimeError(f"operation is not executable from state: {current.state.value}")
        return self._transition_from(current,OperationState.RUNNING)
    def request_cancel(self,operation_id:OperationId,reason:str)->OperationSnapshot:
        if not isinstance(reason, str): raise TypeError("cancellation reason must be text")
        reason=reason.strip()
        if not reason: raise ValueError("cancellation reason required")
        current=self.require(operation_id)
        if current.cancellation_requested:
            return current
        changes={"cancellation_requested":True,"cancellation_reason":reason}
        if current.state in {OperationState.CREATED,OperationState.QUEUED,OperationState.ADMITTED}:
            return self._transition_from(current,OperationState.CANCELLED,**changes)
        if current.state is OperationState.RUNNING:
            return self._transition_from(current,OperationState.CANCELLING,**changes)
        if current.state is OperationState.UNKNOWN_EFFECT:
            return self._revise_from(current,**changes)
        if current.state is OperationState.RECOVERING:
            if current.effect_certainty is OperationEffectCertainty.NOT_EXECUTED:
                return self._transition_from(current,OperationState.CANCELLED,**changes)
            return self._revise_from(current,**changes)
        raise RuntimeError(f"terminal operation cannot be cancelled from state: {current.state.value}")
    def mark_effect_unknown(self,operation_id:OperationId,*,failure:OperationFailure|None=None)->OperationSnapshot:
        current=self.require(operation_id)
        if current.effect_profile is OperationEffectProfile.NONE or current.effect_id is None:
            raise RuntimeError("effect-free operation cannot enter UNKNOWN_EFFECT")
        if failure is None:
            failure=OperationFailure(OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN,"EFFECT_UNCERTAIN",
                                     "external effect may have occurred; reconciliation required",False,True)
        return self._transition_from(current,OperationState.UNKNOWN_EFFECT,
                                     effect_certainty=OperationEffectCertainty.UNKNOWN,failure=failure)
    def recover_interrupted(self,operation_id:OperationId)->OperationSnapshot:
        current=self.require(operation_id)
        if current.state not in {OperationState.RUNNING,OperationState.CANCELLING}: return current
        if current.effect_profile is not OperationEffectProfile.NONE:
            return self.mark_effect_unknown(operation_id)
        if current.state is OperationState.CANCELLING:
            return self._transition_from(current,OperationState.CANCELLED,
                                         cancellation_reason=current.cancellation_reason or "cancelled during recovery")
        return self._transition_from(current,OperationState.RECOVERING)
    @staticmethod
    def _reconciliation_outcome(current:OperationSnapshot,proof:EffectReconciliationProof)->str:
        verdict=project_effect_reconciliation(proof)
        if current.effect_profile is OperationEffectProfile.NONE or current.effect_id is None:
            raise RuntimeError("effect-free operation does not accept external reconciliation proof")
        if verdict.request_id != current.effect_request_id:
            raise ValueError("effect reconciliation request_id does not match durable operation identity")
        if verdict.effect_id is not None:
            if verdict.effect_id != current.effect_id.value:
                raise ValueError("effect reconciliation effect_id does not match durable operation identity")
            if verdict.request_digest != current.effect_request_digest:
                raise ValueError("effect reconciliation request_digest does not match durable operation identity")
        if verdict.outcome is EffectReconciliationOutcome.UNKNOWN:
            return "unknown"
        if verdict.verification_required:
            raise ValueError("effect reconciliation requiring verification cannot resolve operation authority")
        if verdict.outcome is EffectReconciliationOutcome.EXECUTED:
            return "executed"
        if verdict.outcome is EffectReconciliationOutcome.NOT_EXECUTED:
            return "not_executed"
        if verdict.outcome is EffectReconciliationOutcome.REJECTED:
            return "rejected"
        raise ValueError("effect reconciliation outcome is unsupported")

    def reconcile_effect(self,operation_id:OperationId,proof:EffectReconciliationProof)->OperationSnapshot:
        current=self.require(operation_id)
        outcome=self._reconciliation_outcome(current,proof)
        if outcome == "unknown":
            return current
        if current.state is not OperationState.UNKNOWN_EFFECT:
            if outcome == "executed" and current.state in {OperationState.RECOVERING,OperationState.COMPLETED} and current.effect_certainty is OperationEffectCertainty.EXECUTED:
                return current
            if outcome == "not_executed" and current.effect_certainty is OperationEffectCertainty.NOT_EXECUTED and current.state in {OperationState.RECOVERING,OperationState.CANCELLED}:
                return current
            if outcome == "rejected" and current.state is OperationState.FAILED and current.failure is not None and current.failure.code == "EFFECT_RECONCILIATION_REJECTED":
                return current
            raise RuntimeError(f"operation does not require matching effect reconciliation: {current.state.value}")
        if outcome == "not_executed" and current.cancellation_requested:
            return self._transition_from(current,OperationState.CANCELLED,
                                         effect_certainty=OperationEffectCertainty.NOT_EXECUTED,failure=None)
        if outcome == "not_executed":
            return self._transition_from(current,OperationState.RECOVERING,
                                         effect_certainty=OperationEffectCertainty.NOT_EXECUTED,failure=None)
        if outcome == "executed":
            return self._transition_from(current,OperationState.RECOVERING,
                                         effect_certainty=OperationEffectCertainty.EXECUTED,failure=None)
        failure=OperationFailure(OperationFailureKind.OPERATION_FAILURE,"EFFECT_RECONCILIATION_REJECTED",
                                 "authoritative effect reconciliation confirmed provider rejection")
        return self._transition_from(current,OperationState.FAILED,
                                     effect_certainty=OperationEffectCertainty.NOT_EXECUTED,failure=failure)
    def complete(self,operation_id:OperationId,*,result_digest:str|None=None,effect_certainty:OperationEffectCertainty|None=None)->OperationSnapshot:
        current=self.require(operation_id)
        certainty=effect_certainty
        if current.effect_profile is OperationEffectProfile.NONE:
            if certainty not in {None,OperationEffectCertainty.NOT_EXECUTED}:
                raise ValueError("effect-free operation cannot complete with external effect certainty")
            certainty=OperationEffectCertainty.NOT_EXECUTED
        elif certainty is None:
            if current.state is OperationState.RECOVERING and current.effect_certainty is OperationEffectCertainty.EXECUTED:
                certainty=OperationEffectCertainty.EXECUTED
            else:
                raise ValueError("effectful operation completion requires resolved effect certainty")
        if certainty is OperationEffectCertainty.UNKNOWN:
            raise ValueError("operation cannot complete with unknown effect certainty")
        return self._transition_from(
            current,OperationState.COMPLETED,result_digest=result_digest,failure=None,
            effect_certainty=certainty
        )
    def fail(self,operation_id:OperationId,failure:OperationFailure)->OperationSnapshot:
        current=self.require(operation_id)
        return self._transition_from(current,OperationState.FAILED,failure=failure)

__all__=["OperationOwner"]
