"""Runtime projection for Method-owned component Units.

Static component semantics live only in NoetriumUnit.  This module contains
runtime adapters that resolve frozen handler identities when a component Unit
is executed as a unit activation.
"""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    implementation_digest,
    symbol_implementation,
)
from noetrium_platform.foundation.kernel.kernel.unit_host import UnitOperationBinding
from noetrium_platform.foundation.kernel.kernel.universal import (
    UnitStepContext,
    UnitTransition,
    unit_operation_name,
    executable_unit_domain,
    executable_unit_nodes,
    validate_executable_unit,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    METHOD_COMPONENT_TRAIT,
    method_program_components,
    resolve_method_handler,
)

_METHOD_COMPONENT_DOMAINS = frozenset({
    "runtime", "participant", "memory", "environment", "optimization"
})


def _component_handler_ref(node: NoetriumUnit) -> NoetriumUnit:
    try:
        symbol = node.symbol("handler")
    except LookupError as exc:
        raise RuntimeError(
            "method component operation requires one handler implementation symbol"
        ) from exc
    ref = symbol_implementation(symbol)
    if ref is None:
        raise RuntimeError(
            "method component handler symbol has no implementation"
        )
    # The resolver validates implementation type, source identity and
    # import-resolvability. The implementation Unit itself is the sole static
    # handler truth; no duplicate identity fields live in operation config.
    resolve_method_handler(ref)
    return ref


def _component_operation(
    request: UnitStepContext,
    _bindings: object,
) -> UnitTransition:
    handler = resolve_method_handler(_component_handler_ref(request.node))
    value = handler(request)
    if isinstance(value, UnitTransition):
        return value
    if isinstance(value, Mapping):
        state_delta = dict(value.get("state_update", {}))
        events = tuple(value.get("events", ()))
        configuration = request.node.parameters.get("configuration", {})
        if (
            isinstance(configuration, Mapping)
            and configuration.get("await_next_request") is True
        ):
            if value.get("next_node") is not None:
                raise ValueError("persistent request-cycle component cannot branch after dispatch")
            return UnitTransition.suspend(
                "component awaiting next request",
                value=value.get("value"),
                state_delta=state_delta,
                events=events,
                progress=True,
            )
        return UnitTransition.goto(
            value.get("next_node"),
            value=value.get("value"),
            state_delta=state_delta,
            events=events,
        )
    raise TypeError(
        "component handler must return UnitTransition or a result mapping"
    )


def validate_research_component(component: NoetriumUnit) -> None:
    if (
        type(component) is not NoetriumUnit
        or not component.has_trait(METHOD_COMPONENT_TRAIT)
    ):
        raise TypeError(
            "research method component must be a method.component NoetriumUnit"
        )
    validate_executable_unit(component)
    if executable_unit_domain(component) not in _METHOD_COMPONENT_DOMAINS:
        raise ValueError("research method component has unsupported executable domain")
    for node in executable_unit_nodes(component):
        _component_handler_ref(node)


def research_component_operations(
    component: NoetriumUnit,
) -> tuple[UnitOperationBinding, ...]:
    validate_research_component(component)
    return tuple(
        UnitOperationBinding(
            unit_operation_name(node),
            _component_operation,
            implementation_digest(_component_handler_ref(node)),
        )
        for node in executable_unit_nodes(component)
    )


def research_method_components(
    method: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    return method_program_components(method)


__all__ = [
    "research_component_operations",
    "research_method_components",
    "validate_research_component",
]
