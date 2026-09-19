from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from noetrium_platform.infrastructure.reliability.effect.api import EffectAlreadyConsumed, EffectIntentPhase, EffectIntentRecord, EffectRecoveryAnchorMissing
from noetrium_platform.capabilities.environment.runtime.api import ActionNotApplied, ActionRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.research.execution.workflow.api import EffectIntentOperationPort, OperationDispatchPort
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from .action_effect_identity import build_action_effect_intent

@dataclass(frozen=True, slots=True)
class ActionSlotInspection:
    existing: EffectIntentRecord | None
    operation_results: tuple[OperationResult[JsonValue], ...]
    @property
    def nonterminal(self) -> EffectIntentRecord | None:
        row=self.existing
        return row if row is not None and not row.phase.terminal else None

class ActionSlotGuard:
    """Stateless journal query/guard for one logical action slot."""
    def __init__(self, dispatcher: OperationDispatchPort, bound: BoundParticipants, *, journal_ops: EffectIntentOperationPort | None, journal_durability: str | None) -> None:
        self._dispatcher=dispatcher; self._bound=bound; self._journal_ops=journal_ops; self._journal_durability=journal_durability
    @staticmethod
    def _dc(context: ExecutionContext)->str: return context.decision_cycle_id or context.span_id
    def preflight_slot(self, *, action_type: str, action_payload: object, context: ExecutionContext) -> ActionSlotInspection:
        if self._journal_ops is None: return ActionSlotInspection(None,())
        dc=self._dc(context); request=ActionRequest(f"action_{dc}",action_type,action_payload,context)
        intent=build_action_effect_intent(request,operation_id=f"{dc}:environment.act",provider_component=self._bound.component("environment"))
        rows=[]
        _,op=self._journal_ops.require_scope_clear(intent,context); rows.append(op)
        existing,op=self._journal_ops.inspect(intent,context); rows.append(op)
        if existing is None: return ActionSlotInspection(None,tuple(rows))
        guard=self.guard_existing_intent(existing.phase,context)
        if guard is not None: rows.append(guard)
        recovery=self.guard_nonterminal_recovery_anchor(existing.phase,context)
        if recovery is not None: rows.append(recovery)
        return ActionSlotInspection(existing,tuple(rows))
    @staticmethod
    def _require_existing_intent_replay_allowed(phase: EffectIntentPhase)->str:
        if phase is EffectIntentPhase.CONSUMED: raise EffectAlreadyConsumed("exact action intent is already CONSUMED by trial state; restore/return prior cycle result instead of replay")
        if phase is EffectIntentPhase.NOT_APPLIED: raise ActionNotApplied("exact action intent was previously proven NOT_APPLIED; a new action decision is required")
        return phase.value
    def guard_existing_intent(self,phase:EffectIntentPhase,context:ExecutionContext)->OperationResult[JsonValue]|None:
        if not phase.terminal:return None
        dc=self._dc(context); op=self._dispatcher.dispatch(root_context=context,operation_id=f"{dc}:environment.effect.replay_guard",operation_type="environment.effect.replay_guard",target=self._journal_ops.component_identity,payload={"phase":phase.value},payload_schema="environment.effect.replay_guard.v1",handler=lambda request:self._require_existing_intent_replay_allowed(EffectIntentPhase(str(request.payload["phase"]))))
        self._dispatcher.require(op); return op
    def guard_nonterminal_recovery_anchor(self,phase:EffectIntentPhase,context:ExecutionContext)->OperationResult[JsonValue]|None:
        if phase.terminal or self._journal_durability!="crash_durable" or context.checkpoint_id:return None
        dc=self._dc(context); op=self._dispatcher.dispatch(root_context=context,operation_id=f"{dc}:environment.effect.recovery_anchor_guard",operation_type="environment.effect.recovery_anchor_guard",target=self._journal_ops.component_identity,payload={"phase":phase.value,"checkpoint_id":context.checkpoint_id},payload_schema="environment.effect.recovery_anchor_guard.v1",handler=lambda request:self._require_recovery_anchor(request.payload))
        self._dispatcher.require(op); return op
    @staticmethod
    def _require_recovery_anchor(payload:Mapping[str,JsonValue])->str:
        if not payload.get("checkpoint_id"): raise EffectRecoveryAnchorMissing("crash-durable non-terminal action recovery requires a verified pre-cycle checkpoint anchor")
        return str(payload["checkpoint_id"])

__all__=["ActionSlotGuard","ActionSlotInspection"]
