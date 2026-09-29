from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    OperationExecutor,
    OperationRequest,
    OperationResult,
    canonical_digest,
    new_operation_invocation_id,
)

from .operation_policy import ProtectedOperationSemanticPolicy
from ..api.dispatch import OperationDispatchPort, OperationEffectBinding

T = TypeVar("T")
R = TypeVar("R")


WORKFLOW_RUNTIME_IDENTITY = ComponentIdentity(
    "platform.workflow_runtime",
    "generic_workflow_runtime",
    "1",
    "1",
    "workflow-runtime-v1",
)


class KernelOperationDispatcher:
    """Generic workflow-to-Kernel dispatch adapter; owns no Study/domain implementation."""

    def __init__(
        self,
        executor: OperationExecutor,
        *,
        caller: ComponentIdentity = WORKFLOW_RUNTIME_IDENTITY,
        semantic_policy: type[ProtectedOperationSemanticPolicy] = ProtectedOperationSemanticPolicy,
    ) -> None:
        self._executor = executor
        self._caller = caller
        self._semantic_policy = semantic_policy
        self._identity_digest = canonical_digest(
            {
                "dispatcher": "noetrium.kernel-operation-dispatcher.v2",
                "executor_type": (
                    type(executor).__module__
                    + "."
                    + type(executor).__qualname__
                ),
                "caller": caller,
                "semantic_policy": (
                    semantic_policy.__module__
                    + "."
                    + semantic_policy.__qualname__
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def _execute(
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
    ) -> OperationResult[R]:
        invocation_id = new_operation_invocation_id(operation_id)
        operation_context = root_context.child(
            span_id=f"span:{invocation_id}",
            operation_id=operation_id,
            component_id=target.component_id,
        )
        request = OperationRequest(
            operation_id,
            invocation_id,
            operation_type,
            operation_context,
            self._caller,
            target,
            payload,
            payload_schema,
            canonical_digest(payload),
            idempotency_key=idempotency_key,
        )

        def guarded_handler(envelope: OperationRequest[T]) -> R:
            self._semantic_policy.validate(envelope.operation_type, envelope.idempotency_key)
            return handler(envelope)

        return self._executor.execute(
            request,
            guarded_handler,
            digest_output=digest_output,
            effect_projector=effect_projector,
        )

    async def _execute_async(
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
    ) -> OperationResult[R]:
        invocation_id = new_operation_invocation_id(operation_id)
        operation_context = root_context.child(
            span_id=f"span:{invocation_id}",
            operation_id=operation_id,
            component_id=target.component_id,
        )
        request = OperationRequest(
            operation_id,
            invocation_id,
            operation_type,
            operation_context,
            self._caller,
            target,
            payload,
            payload_schema,
            canonical_digest(payload),
            idempotency_key=idempotency_key,
        )

        def guarded_handler(envelope: OperationRequest[T]) -> R:
            self._semantic_policy.validate(envelope.operation_type, envelope.idempotency_key)
            return handler(envelope)

        return await self._executor.execute_async(
            request,
            guarded_handler,
            digest_output=digest_output,
            effect_projector=effect_projector,
        )

    def dispatch(self, *, root_context: ExecutionContext, operation_id: str, operation_type: str,
                 target: ComponentIdentity, payload: T, payload_schema: str,
                 handler: Callable[[OperationRequest[T]], R], digest_output: bool = True,
                 effect_projector=None, idempotency_key: str | None = None,
                 effect_binding: OperationEffectBinding | None = None) -> OperationResult[R]:
        if effect_binding is not None:
            raise RuntimeError(
                "effectful operation requires the durable Operation dispatcher"
            )
        return self._execute(root_context=root_context, operation_id=operation_id, operation_type=operation_type,
                             target=target, payload=payload, payload_schema=payload_schema, handler=handler,
                             digest_output=digest_output, effect_projector=effect_projector,
                             idempotency_key=idempotency_key)

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
        if effect_binding is not None:
            raise RuntimeError(
                "effectful operation requires the durable Operation dispatcher"
            )
        return await self._execute_async(
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

    def execute(self, *, root_context: ExecutionContext, operation_id: str, operation_type: str,
                target: ComponentIdentity, payload: T, payload_schema: str,
                handler: Callable[[OperationRequest[T]], R], digest_output: bool = True,
                effect_projector=None, idempotency_key: str | None = None) -> OperationResult[R]:
        """Non-dispatch-named entry used by durable workflow ownership wrappers."""
        return self._execute(root_context=root_context, operation_id=operation_id, operation_type=operation_type,
                             target=target, payload=payload, payload_schema=payload_schema, handler=handler,
                             digest_output=digest_output, effect_projector=effect_projector,
                             idempotency_key=idempotency_key)

    def require(self, result: OperationResult[R]) -> R:
        return self._executor.require_success(result)


__all__ = ["KernelOperationDispatcher", "WORKFLOW_RUNTIME_IDENTITY"]
