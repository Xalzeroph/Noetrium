from __future__ import annotations

from collections.abc import Mapping

from noetrium.contracts.json import JsonValue

from ..tools import ToolArguments, ToolRegistry
from .contracts import (
    ReferenceAgentAction,
    ReferenceAgentActionKind,
    ReferenceAgentObservation,
)


class ReferenceToolRegistryPort:
    """Adapter from the reusable ToolRegistry to the ReAct tool port."""

    def __init__(self, registry: ToolRegistry) -> None:
        if type(registry) is not ToolRegistry:
            raise TypeError("registry tool port requires ToolRegistry")
        self._registry = registry

    def invoke_action(self, action: ReferenceAgentAction) -> ReferenceAgentObservation:
        if action.kind is not ReferenceAgentActionKind.TOOL:
            raise ValueError("registry tool port accepts tool actions only")
        result = self._registry.invoke(
            action.name, ToolArguments.from_mapping(action.argument_values())
        )
        return ReferenceAgentObservation(
            action.action_digest,
            result.error or result.content,
            result.success,
            result_digest=result.result_digest,
        )

    def invoke(
        self, name: str, arguments: Mapping[str, JsonValue]
    ) -> ReferenceAgentObservation:
        return self.invoke_action(
            ReferenceAgentAction(ReferenceAgentActionKind.TOOL, name, arguments)
        )


__all__ = ["ReferenceToolRegistryPort"]
