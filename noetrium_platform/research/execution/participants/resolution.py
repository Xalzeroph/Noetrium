from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import BoundParticipant
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantRuntimeBinding
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapterRegistry
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from noetrium_platform.capabilities.participant.core.api.runtime_operations import participant_operation_type
from noetrium_platform.research.execution.workflow.api import OperationDispatchPort


class ParticipantResolutionOperations:
    """Resolve and validate one frozen participant binding through a generic runtime adapter."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        adapters: ParticipantLifecycleAdapterRegistry,
    ) -> None:
        self._dispatcher = dispatcher
        self._adapters = adapters

    @staticmethod
    def _scope(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def resolve(
        self,
        binding: ParticipantRuntimeBinding,
        context: ExecutionContext,
    ) -> tuple[BoundParticipant, OperationResult[JsonValue]]:
        adapter = self._adapters.resolve(binding.implementation.kind)
        frozen = adapter.frozen_component(binding)
        scope = self._scope(context)
        operation = self._dispatcher.dispatch(
            root_context=context,
            operation_id=(
                f"{scope}:{binding.implementation.kind}.resolve:{binding.role}"
            ),
            operation_type=participant_operation_type(adapter.kind, "resolve"),
            target=frozen,
            payload={
                "role": binding.role,
                "implementation_digest": binding.implementation.digest(),
                "runtime_digest": binding.runtime.digest(),
                "configuration_digest": binding.configuration_digest,
            },
            payload_schema="participant.resolve.request.v1",
            handler=lambda request: adapter.resolve(binding),
            digest_output=False,
        )
        resolved = self._dispatcher.require(operation)
        if not isinstance(resolved, ParticipantRuntimeHandle):
            raise TypeError("participant resolve operation must return ParticipantRuntimeHandle")
        adapter.validate(binding, resolved)
        return (
            BoundParticipant(
                role=binding.role,
                implementation=binding.implementation,
                runtime=resolved,
                component=adapter.actual_component(resolved),
                adapter=adapter,
            ),
            operation,
        )


__all__ = ["ParticipantResolutionOperations"]
