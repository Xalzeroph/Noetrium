from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.contracts import RunCheckpointStore
from .identity import CHECKPOINT_STORE_IDENTITY
from ..api.results import RunRestoreResult
from .validation import validate_restore_bundle
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantCheckpointOperationsPort
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


def _require_session_topology(
    participant_sessions: tuple[ParticipantSessionBinding, ...],
    expected_roles: set[str],
) -> None:
    roles = tuple(binding.participant.role for binding in participant_sessions)
    if len(roles) != len(set(roles)):
        raise RuntimeError("checkpoint participant session topology contains duplicate roles")
    if set(roles) != expected_roles:
        raise RuntimeError(
            f"checkpoint participant topology mismatch: expected={sorted(expected_roles)} actual={sorted(roles)}"
        )


class RunCheckpointRestorer:
    """Restores every active participant after exact bundle validation."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        store: RunCheckpointStore,
        participant_checkpoints: ParticipantCheckpointOperationsPort,
    ) -> None:
        self._dispatcher = dispatcher
        self._store = store
        self._participant_checkpoints = participant_checkpoints

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id


    def restore(
        self,
        checkpoint_id: str,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunRestoreResult:
        dc = self._dc(context)
        load_op = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:run.checkpoint.load",
            operation_type="run.checkpoint.load",
            target=CHECKPOINT_STORE_IDENTITY,
            payload={"checkpoint_id": checkpoint_id},
            payload_schema="run.checkpoint.load.v3",
            idempotency_key=checkpoint_id,
            handler=lambda request: validate_restore_bundle(
                self._store.load(request.payload["checkpoint_id"]),
                spec=spec,
                bound=bound,
                cycle_identity=cycle_identity,
            ),
        )
        bundle = self._dispatcher.require(load_op)
        rows = [load_op]
        payloads = {row.ref.role: row for row in bundle.participant_payloads}
        _require_session_topology(participant_sessions, set(payloads))
        for binding in participant_sessions:
            participant = binding.participant
            item = payloads[participant.role]
            operation = self._participant_checkpoints.restore(
                binding, item.checkpoint, context, session_id=cycle_identity.session_id
            )
            rows.append(operation)
        return RunRestoreResult(bundle, tuple(rows))


__all__ = ["RunCheckpointRestorer"]
