from __future__ import annotations


"""Research composition for recursive executable-Unit activation."""

from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.structure import (
    implementation_digest,
    implementation_field,
    is_implementation,
)
from noetrium_platform.product.research_implementation import (
    EXECUTABLE_UNIT_IMPLEMENTATION_TYPE,
    METHOD_IMPLEMENTATION_TYPE,
)
from noetrium_platform.product.research_traits import TRAIT_UNIT_ACTIVATION
from noetrium_platform.composition.research_lowering import (
    resolve_executable_unit_implementation,
    resolve_research_method_implementation,
)
from noetrium_platform.foundation.kernel.kernel.unit_activation import (
    UnitActivationRegistry,
    UnitActivationRuntime,
)
from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit
from noetrium_platform.research.execution.workflow.api import MethodRuntimePortInventory
from noetrium_platform.research.execution.method.components import (
    research_component_operations,
    research_method_components,
)
from noetrium_platform.foundation.kernel.kernel.universal import (
    executable_unit_domain,
    executable_unit_required_capabilities,
)



def compose_research_node_method_runtime_inventory(
    symbols: tuple[NoetriumUnit, ...],
    base: MethodRuntimePortInventory,
    *,
    method_graph_digests: tuple[str, ...],
    journal: MachineJournalPort,
    max_steps: int | None,
) -> MethodRuntimePortInventory:
    """Bind only the selected MethodPrograms' components into one runtime inventory.

    Method-owned activation host ids are logical names scoped by their owning Method.
    A NoetriumUnit may contain many alternative/baseline Methods that legitimately
    reuse the same logical host id with different implementations.  Physical child
    host registration therefore follows the exact structure_unit(s) selected by the
    current execution binding rather than aggregating every Method in the program.
    """

    if type(symbols) is not tuple or any(
        type(symbol) is not NoetriumUnit for symbol in symbols
    ):
        raise TypeError("Unit activation composition requires NoetriumUnit tuple")
    if not isinstance(base, MethodRuntimePortInventory):
        raise TypeError("Unit activation composition requires MethodRuntimePortInventory")
    if not isinstance(journal, MachineJournalPort):
        raise TypeError("Unit activation composition requires MachineJournalPort")
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError("Unit activation composition max_steps must be positive or None")
    if type(method_graph_digests) is not tuple or any(
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
        for value in method_graph_digests
    ):
        raise TypeError(
            "Unit activation composition method_graph_digests must be SHA-256 tuple"
        )
    if len(method_graph_digests) != len(set(method_graph_digests)):
        raise ValueError(
            "Unit activation composition method_graph_digests must be unique"
        )

    selected_method_digests = frozenset(method_graph_digests)
    resolved_methods = tuple(
        (definition, resolve_research_method_implementation(definition).method)
        for definition in symbols
        if is_implementation(
            definition.implementation,
            METHOD_IMPLEMENTATION_TYPE,
        )
    )
    available_method_digests = frozenset(
        method.unit_digest for _definition, method in resolved_methods
    )
    missing_method_digests = selected_method_digests - available_method_digests
    if missing_method_digests:
        raise LookupError(
            "selected NoetriumUnit is not owned by NoetriumUnit: "
            + ",".join(sorted(missing_method_digests))
        )
    owned_components = tuple(
        (definition, method, component)
        for definition, method in resolved_methods
        if method.unit_digest in selected_method_digests
        for component in research_method_components(method)
    )
    declared_activations = tuple(
        definition
        for definition in symbols
        if definition.has_trait(TRAIT_UNIT_ACTIVATION)
    )
    if not owned_components and not declared_activations:
        return base

    host_ids = tuple(
        component.unit_id
        for _definition, _method, component in owned_components
    ) + tuple(definition.symbol_id for definition in declared_activations)
    if len(host_ids) != len(set(host_ids)):
        raise ValueError(
            "Method-owned activation host ids must be unique within one NoetriumUnit"
        )

    registry = UnitActivationRegistry()
    if base.unit_activation is not None:
        if not isinstance(base.unit_activation, UnitActivationRuntime):
            raise TypeError(
                "Method child runtime must use the canonical "
                "UnitActivationRuntime"
            )
        for registered in base.unit_activation.registry.registrations():
            registry.register(
                registered.host,
                registered.binding_factory,
                binding_factory_digest=registered.binding_factory_digest,
            )

    for definition in declared_activations:
        if not is_implementation(
            definition.implementation,
            EXECUTABLE_UNIT_IMPLEMENTATION_TYPE,
        ):
            raise TypeError(
                "research.unit-activation symbol requires executable-Unit implementation"
            )
        resolved = resolve_executable_unit_implementation(definition)
        host = BoundExecutableUnit(
            host_id=definition.symbol_id,
            unit=resolved.program,
            operations=resolved.operations,
            journal=journal,
            max_steps=max_steps,
            dependency_identity={
                "activation_definition_digest": definition.symbol_digest,
                "implementation_digest": implementation_digest(definition.implementation),
                "unit_digest": resolved.program.unit_digest,
                "operations_digest": implementation_field(definition.implementation, "operations_digest"),
            },
        )
        registry.register_static(
            host,
            None,
            binding_identity_digest=canonical_digest(
                {
                    "binding": "research-unit-activation.v1",
                    "activation_definition_digest": definition.symbol_digest,
                    "implementation_digest": implementation_digest(definition.implementation),
                }
            ),
        )

    for definition, method, component in owned_components:
        if executable_unit_required_capabilities(component):
            raise ValueError(
                "Method-owned components are pure state/control machines; "
                "model/tool/environment effects belong to parent Method nodes"
            )
        host = BoundExecutableUnit(
            host_id=component.unit_id,
            unit=component,
            operations=research_component_operations(component),
            journal=journal,
            max_steps=max_steps,
            dependency_identity={
                "method_definition_digest": definition.symbol_digest,
                "method_graph_digest": method.unit_digest,
                "component_domain": executable_unit_domain(component),
                "component_graph_digest": component.unit_digest,
            },
        )
        registry.register_static(
            host,
            None,
            binding_identity_digest=canonical_digest({
                "binding": "method-owned-component.v1",
                "method_definition_digest": definition.symbol_digest,
                "component_domain": executable_unit_domain(component),
                "component_graph_digest": component.unit_digest,
            }),
        )

    return MethodRuntimePortInventory(
        agent_loop=base.agent_loop,
        capabilities=base.capabilities,
        unit_activation=registry.runtime(),
        schemas=base.schemas,
    )


__all__ = ["compose_research_node_method_runtime_inventory"]
