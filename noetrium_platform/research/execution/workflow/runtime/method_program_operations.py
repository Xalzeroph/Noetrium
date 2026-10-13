from __future__ import annotations

from collections.abc import Callable, Mapping

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    OperationRequest,
    OperationResult,
)
from noetrium_platform.research.execution.workflow.api.dispatch import (
    OperationDispatchPort,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    MethodNodeResult,
)


METHOD_PROGRAM_TARGET = ComponentIdentity(
    "platform.workflow_runtime",
    "method_program_adapter",
    "1",
    "1",
    "method-graph-transform-v1",
)
_METHOD_PROGRAM_PAYLOAD_SCHEMA = "noetrium.method-program-node.v3"


class MethodProgramOperationAdapter:
    """Only authority allowed to dispatch one lowered Method node Operation."""

    def __init__(self, dispatcher: OperationDispatchPort) -> None:
        self._dispatcher = dispatcher

    def invoke(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        payload: Mapping[str, object],
        handler: Callable[
            [OperationRequest[Mapping[str, object]]],
            MethodNodeResult,
        ],
        idempotency_key: str,
    ) -> OperationResult[MethodNodeResult]:
        return self._dispatcher.dispatch(
            root_context=root_context,
            operation_id=operation_id,
            operation_type=operation_type,
            target=METHOD_PROGRAM_TARGET,
            payload=payload,
            payload_schema=_METHOD_PROGRAM_PAYLOAD_SCHEMA,
            handler=handler,
            digest_output=True,
            effect_projector=lambda output: tuple(output.effect_receipts),
            idempotency_key=idempotency_key,
        )

    def require(
        self,
        result: OperationResult[MethodNodeResult],
    ) -> MethodNodeResult:
        return self._dispatcher.require(result)


__all__ = ["METHOD_PROGRAM_TARGET", "MethodProgramOperationAdapter"]
