"""Adapters from legacy/public whole-method contracts to the canonical UMM ABI.

The adapters preserve the existing typed public contracts while making
MethodProgram the single execution semantic boundary. They only adapt the
method-owned control result; lifecycle, effects, checkpoints and evidence
remain owned by UniversalMethodMachine.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from noetrium_platform.capabilities.participant.method.api import (
    MethodGraphProgram,
    MethodGraphRequest,
    MethodProgramIdentity,
    ResearchMethodProgram,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, freeze_json

from .method_machine import (
    MethodEvent,
    MethodNodeResult,
    MethodNodeSpec,
    MethodNodeKind,
    MethodProgram,
    MethodProgramBuilder,
)


def _result_value(value: Any) -> JsonValue:
    return freeze_json(value)


@dataclass(frozen=True, slots=True)
class ResearchMethodProgramAdapter:
    """Adapt a typed ROLE04 ResearchMethodProgram to one managed UMM node."""

    program: ResearchMethodProgram
    task: JsonValue
    configuration: Mapping[str, JsonValue] | None = None

    @property
    def program_identity(self) -> MethodProgramIdentity:
        return self.program.program_identity

    def to_method_program(self) -> MethodProgram:
        def invoke(request: Any) -> MethodNodeResult:
            result = self.program.run(
                task=self.task,
                input_value=request.input_value,
                context=request.context,
            )
            if inspect.isawaitable(result):
                raise TypeError("async ResearchMethodProgram requires to_async_method_program")
            return MethodNodeResult(value=_result_value(result))

        return (
            MethodProgramBuilder(self.program_identity, entrypoint="method.run")
            .add(MethodNodeSpec(
                "method.run",
                "method.research_program.run",
                handler=invoke,
                kind=MethodNodeKind.RETURN,
            ))
            .build(configuration=self.configuration)
        )

    def to_async_method_program(self) -> MethodProgram:
        async def invoke(request: Any) -> MethodNodeResult:
            result = self.program.run(
                task=self.task,
                input_value=request.input_value,
                context=request.context,
            )
            if inspect.isawaitable(result):
                result = await result
            return MethodNodeResult(value=_result_value(result))

        return (
            MethodProgramBuilder(self.program_identity, entrypoint="method.run")
            .add(MethodNodeSpec(
                "method.run",
                "method.research_program.run",
                handler=invoke,
                kind=MethodNodeKind.RETURN,
            ))
            .build(configuration=self.configuration)
        )


@dataclass(frozen=True, slots=True)
class MethodGraphProgramAdapter:
    """Adapt the older graph contract without creating a second runtime."""

    program: MethodGraphProgram[Any, Any, Any, Any, Any]
    task: Any
    session_id: str = "method-session"
    configuration: Mapping[str, JsonValue] | None = None

    @property
    def program_identity(self) -> MethodProgramIdentity:
        return self.program.program_identity

    def to_method_program(self) -> MethodProgram:
        def invoke(request: Any) -> MethodNodeResult:
            graph_request = MethodGraphRequest(
                task=self.task,
                input_value=request.input_value,
                context=request.context,
                session_id=self.session_id,
                invocation_id=request.context.operation_id or request.context.span_id,
                resume=None,
            )
            result = self.program.invoke(graph_request)
            return MethodNodeResult(
                value=_result_value(result.value),
                events=tuple(MethodEvent(interrupt.node, interrupt.payload) for interrupt in result.interrupts),
            )

        return (
            MethodProgramBuilder(self.program_identity, entrypoint="method.graph")
            .add(MethodNodeSpec(
                "method.graph",
                "method.graph.invoke",
                handler=invoke,
                kind=MethodNodeKind.RETURN,
            ))
            .build(configuration=self.configuration)
        )


__all__ = ["MethodGraphProgramAdapter", "ResearchMethodProgramAdapter"]
