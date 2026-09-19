from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from ..api.contracts import RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef
from .identity import CHECKPOINT_STORE_IDENTITY, build_checkpoint_manifest
from ..api.results import RunCheckpointResult
from ..api import (
    WorkloadCheckpointBundle,
    WorkloadCheckpointManifest,
    WorkloadCheckpointPayload,
    WorkloadCheckpointStore,
)
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantCheckpointOperationsPort
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class RunCheckpointCapture:
    """Captures every active participant, then atomically publishes one generic manifest."""

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

    def capture(
        self,
        *,
        spec: ExperimentSpec,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        cycle_identity: DecisionCycleIdentity,
    ) -> RunCheckpointResult:
        del bound
        dc = self._dc(context)
        rows: list[OperationResult[JsonValue]] = []
        participants: list[RunParticipantPayload] = []
        for binding in participant_sessions:
            participant = binding.participant
            checkpoint, operation = self._participant_checkpoints.capture(
                binding, context, session_id=cycle_identity.session_id
            )
            rows.append(operation)
            participants.append(
                RunParticipantPayload(
                    RunParticipantSnapshotRef(
                        checkpoint=checkpoint.ref,
                        generation=request_generation(context, participant.role),
                    ),
                    checkpoint,
                )
            )

        participant_payloads = tuple(participants)
        manifest = build_checkpoint_manifest(
            spec=spec,
            participant_payloads=participant_payloads,
            cycle_identity=cycle_identity,
        )
        publish_op = self._dispatcher.dispatch(
            root_context=context,
            operation_id=f"{dc}:run.checkpoint.publish",
            operation_type="run.checkpoint.publish",
            target=CHECKPOINT_STORE_IDENTITY,
            payload=manifest,
            payload_schema="study.checkpoint.manifest.v4",
            idempotency_key=manifest.checkpoint_id,
            handler=lambda request: self._store.publish(request.payload, participant_payloads),
        )
        rows.append(publish_op)
        return RunCheckpointResult(self._dispatcher.require(publish_op), tuple(rows))


def request_generation(context: ExecutionContext, role: str) -> str | None:
    """Study-specific generation annotation kept outside generic checkpoint identity."""
    return context.generation(role)


def publish_workload_checkpoint(
    store: WorkloadCheckpointStore,
    manifest: WorkloadCheckpointManifest,
    payloads: tuple[WorkloadCheckpointPayload, ...],
) -> WorkloadCheckpointManifest:
    """Single protected publication primitive for workload checkpoints."""

    return store.publish(manifest, payloads)


def load_workload_checkpoint(
    store: WorkloadCheckpointStore,
    checkpoint_id: str,
) -> WorkloadCheckpointBundle:
    return store.load(checkpoint_id)


__all__ = ["RunCheckpointCapture", "load_workload_checkpoint", "publish_workload_checkpoint"]
