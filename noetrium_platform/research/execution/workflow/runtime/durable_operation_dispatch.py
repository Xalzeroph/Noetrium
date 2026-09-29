from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    ExecutionContext,
    OperationRequest,
    OperationResult,
    OperationStatus,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.execution import (
    OperationFailure as KernelOperationFailure,
)
from noetrium_platform.research.execution.operation.api import (
    CommandIntentPort,
    EffectId,
    ExecutionCommand,
    OperationAdmissionPort,
    OperationEffectCertainty,
    OperationEffectProfile,
    OperationFailure,
    OperationFailureKind,
    OperationId,
    OperationSnapshot,
    OperationLifecyclePort,
    OperationState,
    OperationSubmissionPort,
)
from noetrium_platform.research.execution.workflow.api import (
    OperationEffectBinding,
    OperationExecutionPort,
)

T = TypeVar("T")
R = TypeVar("R")


class DurableOperationRecoveryRequired(RuntimeError):
    """A durable Operation cannot be replayed until lower effect truth is reconciled."""

    def __init__(self, operation_id: str, state: OperationState, message: str) -> None:
        self.operation_id = operation_id
        self.operation_state = state.value
        super().__init__(message)


class DurableOperationReplayRequired(RuntimeError):
    """A durable terminal Operation exists but its output must come from its owning projection."""

    def __init__(self, operation_id: str, state: OperationState) -> None:
        self.operation_id = operation_id
        self.operation_state = state.value
        super().__init__(
            "durable operation is already terminal; recover the authoritative "
            f"higher-level result instead of re-executing it: {operation_id}:{state.value}"
        )


class DurableKernelOperationDispatcher:
    """Single workflow Operation boundary backed by durable command/lifecycle authorities."""

    def __init__(
        self,
        kernel: OperationExecutionPort,
        *,
        commands: CommandIntentPort,
        submissions: OperationSubmissionPort,
        admissions: OperationAdmissionPort,
        operations: OperationLifecyclePort,
    ) -> None:
        self._kernel = kernel
        self._commands = commands
        self._submissions = submissions
        self._admissions = admissions
        self._operations = operations
        self._identity_digest = canonical_digest(
            {
                "dispatcher": "noetrium.durable-kernel-operation-dispatcher.v3",
                "command_authority": type(commands).__qualname__,
                "submission_authority": type(submissions).__qualname__,
                "admission_authority": type(admissions).__qualname__,
                "lifecycle_authority": type(operations).__qualname__,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def durability(self) -> str:
        value = getattr(self._operations, "durability", None)
        return value if isinstance(value, str) and value.strip() else "unknown"

    @staticmethod
    def _command_id(operation_id: str) -> str:
        return "command:" + canonical_digest(
            {
                "schema": "noetrium.workflow-operation-command.v1",
                "operation_id": operation_id,
            }
        )

    @staticmethod
    def _deduplication_key(
        operation_type: str,
        idempotency_key: str | None,
    ) -> str | None:
        if idempotency_key is None:
            return None
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("operation idempotency_key must be non-empty when provided")
        return "operation-dedup:" + canonical_digest(
            {
                "operation_type": operation_type,
                "idempotency_key": idempotency_key.strip(),
            }
        )

    def _materialize(
        self,
        *,
        operation_id: str,
        operation_type: str,
        payload: T,
        payload_schema: str,
        idempotency_key: str | None,
        root_context: ExecutionContext,
        effect_binding: OperationEffectBinding | None,
    ) -> OperationSnapshot:
        command = ExecutionCommand.create(
            command_id=self._command_id(operation_id),
            command_type=operation_type,
            payload_schema=payload_schema,
            payload_digest=canonical_digest(payload),
            deduplication_key=self._deduplication_key(
                operation_type,
                idempotency_key,
            ),
            now_unix=0.0,
        )
        command, _ = self._commands.submit(command)
        durable_id = OperationId(operation_id)
        parent = None
        if (
            isinstance(root_context.operation_id, str)
            and root_context.operation_id.strip()
            and root_context.operation_id.strip() != operation_id
        ):
            parent = OperationId(root_context.operation_id.strip())

        effect_profile = OperationEffectProfile.NONE
        effect_id = None
        effect_request_id = None
        effect_request_digest = None
        if effect_binding is not None:
            effect_profile = effect_binding.profile
            effect_id = EffectId(effect_binding.effect_id)
            effect_request_id = effect_binding.request_id
            effect_request_digest = effect_binding.request_digest

        snapshot, _ = self._submissions.submit(
            command.command_id,
            operation_id=durable_id,
            parent_operation_id=parent,
            effect_profile=effect_profile,
            effect_id=effect_id,
            effect_request_id=effect_request_id,
            effect_request_digest=effect_request_digest,
            now_unix=0.0,
        )
        if snapshot.state is OperationState.CREATED:
            snapshot = self._admissions.queue(snapshot, now_unix=0.0)
        if snapshot.state is OperationState.QUEUED:
            snapshot = self._admissions.admit(snapshot, now_unix=0.0)
        if snapshot.state in {OperationState.RUNNING, OperationState.CANCELLING}:
            snapshot = self._operations.recover_interrupted(snapshot)

        if snapshot.state is OperationState.UNKNOWN_EFFECT:
            raise DurableOperationRecoveryRequired(
                durable_id.value,
                snapshot.state,
                "durable operation has unknown external-effect certainty; "
                "authoritative reconciliation is required before retry",
            )
        if snapshot.state is OperationState.RECOVERING:
            if snapshot.effect_certainty is not OperationEffectCertainty.NOT_EXECUTED:
                raise DurableOperationRecoveryRequired(
                    durable_id.value,
                    snapshot.state,
                    "durable operation recovery already resolved an external effect; "
                    "recover the owning result instead of re-executing",
                )
            return snapshot
        if snapshot.state in {
            OperationState.COMPLETED,
            OperationState.FAILED,
            OperationState.CANCELLED,
        }:
            raise DurableOperationReplayRequired(durable_id.value, snapshot.state)
        if snapshot.state is not OperationState.ADMITTED:
            raise RuntimeError(
                "durable operation did not reach executable state: "
                f"{snapshot.state.value}"
            )
        return snapshot

    def _unknown(
        self,
        current: OperationSnapshot,
        *,
        result: OperationResult[R] | None,
        message: str,
    ) -> None:
        failure = OperationFailure(
            OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN,
            "EFFECT_UNCERTAIN",
            message,
            retryable=False,
            reconciliation_required=True,
            failure_id=None if result is None else result.failure_id,
        )
        snapshot = self._operations.mark_effect_unknown(
            current,
            failure=failure,
        )
        error = DurableOperationRecoveryRequired(
            current.operation_id.value,
            snapshot.state,
            message,
        )
        if result is not None and result.cause is not None:
            raise error from result.cause
        raise error

    def _finalize(
        self,
        running: OperationSnapshot,
        result: OperationResult[R],
    ) -> OperationResult[R]:
        if result.status is not OperationStatus.SUCCEEDED:
            if running.effect_profile is OperationEffectProfile.NONE:
                self._operations.fail(
                    running,
                    OperationFailure(
                        OperationFailureKind.OPERATION_FAILURE,
                        "OPERATION_FAILED",
                        "kernel operation failed",
                        retryable=False,
                        reconciliation_required=False,
                        failure_id=result.failure_id,
                    ),
                )
                return result
            self._unknown(
                running,
                result=result,
                message=(
                    "effectful kernel operation failed after execution began; "
                    "external-effect certainty is unknown"
                ),
            )

        if running.effect_profile is OperationEffectProfile.NONE:
            self._operations.complete(
                running,
                result_digest=result.output_digest,
                effect_certainty=OperationEffectCertainty.NOT_EXECUTED,
            )
            return result

        receipts = result.effect_receipts
        if (
            len(receipts) != 1
            or running.effect_id is None
            or receipts[0].effect_id != running.effect_id.value
            or receipts[0].request_digest != running.effect_request_digest
            or receipts[0].effect_class.value != running.effect_profile.value
        ):
            self._unknown(
                running,
                result=result,
                message=(
                    "effectful operation completed without one receipt matching "
                    "its pre-execution durable effect identity"
                ),
            )

        receipt = receipts[0]
        if receipt.certainty is EffectCertainty.EFFECT_CONFIRMED:
            certainty = OperationEffectCertainty.EXECUTED
        elif receipt.certainty in {
            EffectCertainty.NO_EFFECT,
            EffectCertainty.EFFECT_REJECTED,
        }:
            certainty = OperationEffectCertainty.NOT_EXECUTED
        else:
            self._unknown(
                running,
                result=result,
                message=(
                    "effectful operation returned unresolved external-effect certainty"
                ),
            )
        self._operations.complete(
            running,
            result_digest=result.output_digest,
            effect_certainty=certainty,
        )
        return result

    def dispatch(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        target: ComponentIdentity,
        payload: T,
        payload_schema: str,
        handler: Callable[[OperationRequest[T]], R],
        digest_output: bool = True,
        effect_projector=None,
        idempotency_key: str | None = None,
        effect_binding: OperationEffectBinding | None = None,
    ) -> OperationResult[R]:
        admitted = self._materialize(
            operation_id=operation_id,
            operation_type=operation_type,
            payload=payload,
            payload_schema=payload_schema,
            idempotency_key=idempotency_key,
            root_context=root_context,
            effect_binding=effect_binding,
        )
        running = self._operations.begin_execution(admitted)
        result = self._kernel.execute(
            root_context=root_context,
            operation_id=operation_id,
            operation_type=operation_type,
            target=target,
            payload=payload,
            payload_schema=payload_schema,
            handler=handler,
            digest_output=digest_output,
            effect_projector=effect_projector,
            idempotency_key=idempotency_key,
        )
        return self._finalize(running, result)

    async def dispatch_async(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        target: ComponentIdentity,
        payload: T,
        payload_schema: str,
        handler: Callable[[OperationRequest[T]], R],
        digest_output: bool = True,
        effect_projector=None,
        idempotency_key: str | None = None,
        effect_binding: OperationEffectBinding | None = None,
    ) -> OperationResult[R]:
        admitted = self._materialize(
            operation_id=operation_id,
            operation_type=operation_type,
            payload=payload,
            payload_schema=payload_schema,
            idempotency_key=idempotency_key,
            root_context=root_context,
            effect_binding=effect_binding,
        )
        running = self._operations.begin_execution(admitted)
        dispatch_async = getattr(self._kernel, "dispatch_async", None)
        if not callable(dispatch_async):
            raise TypeError("durable Operation kernel must provide dispatch_async")
        result = await dispatch_async(
            root_context=root_context,
            operation_id=operation_id,
            operation_type=operation_type,
            target=target,
            payload=payload,
            payload_schema=payload_schema,
            handler=handler,
            digest_output=digest_output,
            effect_projector=effect_projector,
            idempotency_key=idempotency_key,
        )
        return self._finalize(running, result)

    def require(self, result: OperationResult[R]) -> R:
        if result.status is not OperationStatus.SUCCEEDED:
            failure = KernelOperationFailure(result)
            if result.cause is not None:
                raise failure from result.cause
            raise failure
        return result.output  # type: ignore[return-value]


__all__ = [
    "DurableKernelOperationDispatcher",
    "DurableOperationRecoveryRequired",
    "DurableOperationReplayRequired",
]
