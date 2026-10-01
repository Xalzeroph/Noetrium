from __future__ import annotations

"""Program-scoped child ResearchMachine runtime composition."""

from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    canonical_digest,
)
from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
    ResearchMachineProgramImplementation,
    ResearchMethodImplementation,
    ResearchProgram,
)
from noetrium_platform.composition.research_os_lowering import (
    resolve_machine_program_implementation,
)
from noetrium_platform.research.execution.machines import (
    ChildResearchHostRegistry,
    ChildResearchMachineExecutor,
    ResearchProgramHost,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRuntimePortInventory,
    ProgramScopedCapabilityPort,
)



def compose_program_method_runtime_inventory(
    program: ResearchProgram,
    base: MethodRuntimePortInventory,
    *,
    method_program_digests: tuple[str, ...],
    journal: MachineJournalPort,
    max_steps: int | None,
) -> MethodRuntimePortInventory:
    """Bind only the selected MethodPrograms' components into one runtime inventory.

    Method-owned component host ids are logical names scoped by their owning Method.
    A ResearchProgram may contain many alternative/baseline Methods that legitimately
    reuse the same logical host id with different implementations.  Physical child
    host registration therefore follows the exact MethodProgram(s) selected by the
    current execution binding rather than aggregating every Method in the program.
    """

    if type(program) is not ResearchProgram:
        raise TypeError("child runtime composition requires ResearchProgram")
    if not isinstance(base, MethodRuntimePortInventory):
        raise TypeError("child runtime composition requires MethodRuntimePortInventory")
    if not isinstance(journal, MachineJournalPort):
        raise TypeError("child runtime composition requires MachineJournalPort")
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError("child runtime composition max_steps must be positive or None")
    if type(method_program_digests) is not tuple or any(
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
        for value in method_program_digests
    ):
        raise TypeError(
            "child runtime composition method_program_digests must be SHA-256 tuple"
        )
    if len(method_program_digests) != len(set(method_program_digests)):
        raise ValueError(
            "child runtime composition method_program_digests must be unique"
        )

    capabilities = base.capabilities
    if isinstance(capabilities, ProgramScopedCapabilityPort):
        capabilities = capabilities.for_program(program.program_id)
    effective_base = MethodRuntimePortInventory(
        agent_loop=base.agent_loop,
        capabilities=capabilities,
        child_machines=base.child_machines,
        schemas=base.schemas,
    )

    selected_method_digests = frozenset(method_program_digests)
    resolved_methods = tuple(
        (definition, definition.implementation.resolve())
        for definition in program.definitions
        if type(definition.implementation) is ResearchMethodImplementation
    )
    available_method_digests = frozenset(
        method.program.program_digest for _definition, method in resolved_methods
    )
    missing_method_digests = selected_method_digests - available_method_digests
    if missing_method_digests:
        raise LookupError(
            "selected MethodProgram is not owned by ResearchProgram: "
            + ",".join(sorted(missing_method_digests))
        )
    owned_components = tuple(
        (definition, method, component)
        for definition, method in resolved_methods
        if method.program.program_digest in selected_method_digests
        for component in method.components
    )
    declared_children = tuple(
        definition
        for definition in program.definitions
        if definition.kind is ResearchDefinitionKind.CHILD_MACHINE
    )
    if not owned_components and not declared_children:
        return effective_base

    host_ids = tuple(
        component.host_id
        for _definition, _method, component in owned_components
    ) + tuple(definition.definition_id for definition in declared_children)
    if len(host_ids) != len(set(host_ids)):
        raise ValueError(
            "Method-owned component host ids must be unique within one ResearchProgram"
        )

    registry = ChildResearchHostRegistry()
    if effective_base.child_machines is not None:
        if not isinstance(effective_base.child_machines, ChildResearchMachineExecutor):
            raise TypeError(
                "Method child runtime must use the canonical "
                "ChildResearchMachineExecutor"
            )
        for registered in effective_base.child_machines.registry.registrations():
            registry.register(
                registered.host,
                registered.binding_factory,
                binding_factory_digest=registered.binding_factory_digest,
            )

    for definition in declared_children:
        if type(definition.implementation) is not ResearchMachineProgramImplementation:
            raise TypeError(
                "Program-scoped CHILD_MACHINE requires ResearchMachineProgramImplementation"
            )
        resolved = resolve_machine_program_implementation(definition)
        host = ResearchProgramHost(
            host_id=definition.definition_id,
            program=resolved.program,
            operations=resolved.operations,
            journal=journal,
            max_steps=max_steps,
            dependency_identity={
                "child_definition_digest": definition.definition_digest,
                "implementation_digest": definition.implementation.implementation_digest,
                "program_digest": resolved.program.program_digest,
                "operations_digest": definition.implementation.operations_digest,
            },
        )
        registry.register_static(
            host,
            None,
            binding_identity_digest=canonical_digest(
                {
                    "binding": "program-scoped-child-machine.v1",
                    "child_definition_digest": definition.definition_digest,
                    "implementation_digest": definition.implementation.implementation_digest,
                }
            ),
        )

    for definition, method, component in owned_components:
        if component.program.required_capabilities:
            raise ValueError(
                "Method-owned components are pure state/control machines; "
                "model/tool/environment effects belong to parent Method nodes"
            )
        host = ResearchProgramHost(
            host_id=component.host_id,
            program=component.program,
            operations=component.operations,
            journal=journal,
            max_steps=max_steps,
            dependency_identity={
                "method_definition_digest": definition.definition_digest,
                "method_artifact_digest": method.artifact_digest,
                "component_domain": component.domain.value,
                "component_artifact_digest": component.artifact_digest,
            },
        )
        registry.register_static(
            host,
            None,
            binding_identity_digest=canonical_digest({
                "binding": "method-owned-component.v1",
                "method_definition_digest": definition.definition_digest,
                "component_domain": component.domain.value,
                "component_artifact_digest": component.artifact_digest,
            }),
        )

    return MethodRuntimePortInventory(
        agent_loop=effective_base.agent_loop,
        capabilities=effective_base.capabilities,
        child_machines=registry.executor(),
        schemas=base.schemas,
    )


__all__ = ["compose_program_method_runtime_inventory"]
