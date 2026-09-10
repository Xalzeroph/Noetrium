from __future__ import annotations

import inspect
from typing import Callable, Generic, TypeVar

from .auxiliary_failures import OperationAuxiliaryFailureReporter, OperationAuxiliaryFailureSink
from .json_value import JsonValue
from .failure_materialization import FailureMaterializer, OperationFailureSink
from .operation import EffectReceipt, OperationRequest, OperationResult, OperationStatus
from .operation_observation import OperationObservationBus, OperationObserver
from .result_projection import OperationResultProjector

T = TypeVar("T")
R = TypeVar("R")


class OperationFailure(RuntimeError):
    """Process-local exception wrapper around a durable OperationResult."""

    def __init__(self, result: OperationResult[JsonValue]) -> None:
        self.result = result
        super().__init__(
            f"operation {result.operation_id} invocation {result.invocation_id} failed "
            f"({result.failure_id or 'unrecorded'})"
        )


class OperationExecutor(Generic[T, R]):
    """Small mechanical operation boundary.

    Only the handler decides primary success/failure. Observation, durable failure
    materialization and result projection are independently isolated collaborators.
    """

    def __init__(
        self,
        failure_sink: OperationFailureSink | None = None,
        *,
        observers: tuple[OperationObserver, ...] = (),
        auxiliary_failure_sink: OperationAuxiliaryFailureSink | None = None,
    ) -> None:
        self._failures = FailureMaterializer(failure_sink)
        self._observation = OperationObservationBus(observers)
        self._projection = OperationResultProjector()
        self._auxiliary = OperationAuxiliaryFailureReporter(auxiliary_failure_sink)

    def execute(
        self,
        request: OperationRequest[T],
        handler: Callable[[OperationRequest[T]], R],
        *,
        digest_output: bool = True,
        effect_projector: Callable[[R], tuple[EffectReceipt, ...]] | None = None,
    ) -> OperationResult[R]:
        started_auxiliary = self._observation.started(request)
        try:
            output = handler(request)
        except Exception as exc:
            materialized = self._failures.materialize(request, exc)  # type: ignore[arg-type]
            result = OperationResult(
                request.operation_id,
                request.invocation_id,
                OperationStatus.FAILED,
                failure_id=materialized.failure_id,
                # Kernel records only stable exception taxonomy. Redacted human detail
                # belongs to failure materialization/forensics, not operation truth.
                diagnostics={"exception_type": type(exc).__qualname__},
                auxiliary_failures=started_auxiliary + materialized.auxiliary_failures,
                cause=exc,
            )
            return self._auxiliary.report(request, self._observation.completed(request, result))

        projected = self._projection.project(
            output,
            digest_output=digest_output,
            effect_projector=effect_projector,
        )
        result = OperationResult(
            request.operation_id,
            request.invocation_id,
            OperationStatus.SUCCEEDED,
            output=projected.output,
            output_digest=projected.output_digest,
            effect_receipts=projected.effect_receipts,
            diagnostics=projected.diagnostics,
            auxiliary_failures=started_auxiliary + projected.auxiliary_failures,
        )
        return self._auxiliary.report(request, self._observation.completed(request, result))

    async def execute_async(
        self,
        request: OperationRequest[T],
        handler: Callable[[OperationRequest[T]], R],
        *,
        digest_output: bool = True,
        effect_projector: Callable[[R], tuple[EffectReceipt, ...]] | None = None,
    ) -> OperationResult[R]:
        """Async sibling of execute; preserves the same operation semantics."""
        started_auxiliary = self._observation.started(request)
        try:
            output = handler(request)
            if inspect.isawaitable(output):
                output = await output
        except Exception as exc:
            materialized = self._failures.materialize(request, exc)  # type: ignore[arg-type]
            result = OperationResult(
                request.operation_id,
                request.invocation_id,
                OperationStatus.FAILED,
                failure_id=materialized.failure_id,
                diagnostics={"exception_type": type(exc).__qualname__},
                auxiliary_failures=started_auxiliary + materialized.auxiliary_failures,
                cause=exc,
            )
            return self._auxiliary.report(request, self._observation.completed(request, result))

        projected = self._projection.project(
            output,
            digest_output=digest_output,
            effect_projector=effect_projector,
        )
        result = OperationResult(
            request.operation_id,
            request.invocation_id,
            OperationStatus.SUCCEEDED,
            output=projected.output,
            output_digest=projected.output_digest,
            effect_receipts=projected.effect_receipts,
            diagnostics=projected.diagnostics,
            auxiliary_failures=started_auxiliary + projected.auxiliary_failures,
        )
        return self._auxiliary.report(request, self._observation.completed(request, result))

    @staticmethod
    def require_success(result: OperationResult[R]) -> R:
        if result.status is not OperationStatus.SUCCEEDED:
            failure = OperationFailure(result)  # type: ignore[arg-type]
            if result.cause is not None:
                raise failure from result.cause
            raise failure
        return result.output  # type: ignore[return-value]


__all__ = ["OperationExecutor", "OperationFailure"]
