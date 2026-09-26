from __future__ import annotations

"""Program-scoped child ResearchMachine runtime composition."""

from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.product.research_os import (
    ResearchMethodImplementation,
    ResearchProgram,
)
from noetrium_platform.research.execution.machines import (
    ChildResearchHostRegistry,
    ResearchProgramHost,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodChildMachinePort,
    MethodRuntimePortInventory,
)



class ProgramScopedChildMachineRouter(MethodChildMachinePort):
    """Route declared host ids locally and delegate all other ids explicitly."""

    def __init__(
        self,
        declared: MethodChildMachinePort,
        host_ids: tuple[str, ...],
        fallback: MethodChildMachinePort | None = None,
    ) -> None:
        if not isinstance(declared, MethodChildMachinePort):
            raise TypeError("declared child machine router requires typed port")
        if fallback is not None and not isinstance(fallback, MethodChildMachinePort):
            raise TypeError("child machine fallback must satisfy MethodChildMachinePort")
        if type(host_ids) is not tuple or any(
            type(host_id) is not str or not host_id.strip()
            for host_id in host_ids
        ):
            raise TypeError("declared child host ids must be a text tuple")
        ordered = tuple(sorted(host_ids))
        if len(ordered) != len(set(ordered)):
            raise ValueError("declared child host ids must be unique")
        self._declared = declared
        self._fallback = fallback
        self._host_ids = frozenset(ordered)
        self._identity_digest = canonical_digest(
            {
                "router": "program-scoped-child-machines.v1",
                "declared_host_ids": ordered,
                "declared_identity": require_sha256(
                    declared.identity_digest,
                    "declared child machine identity",
                ),
                "fallback_identity": (
                    None
                    if fallback is None
                    else require_sha256(
                        fallback.identity_digest,
                        "fallback child machine identity",
                    )
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def _port(self, request: object) -> MethodChildMachinePort:
        host_id = getattr(request, "host_id", None)
        if type(host_id) is not str or not host_id.strip():
            raise TypeError("child machine request must expose non-empty host_id")
        if host_id in self._host_ids:
            return self._declared
        if self._fallback is not None:
            return self._fallback
        return self._declared

    def execute(self, request: object) -> object:
        return self._port(request).execute(request)

    def step_once(self, request: object) -> object:
        return self._port(request).step_once(request)


def compose_program_method_runtime_inventory(
    program: ResearchProgram,
    base: MethodRuntimePortInventory,
    *,
    journal: MachineJournalPort,
    max_steps: int,
) -> MethodRuntimePortInventory:
    """Bind Method-owned pure components into one immutable runtime inventory."""

    if type(program) is not ResearchProgram:
        raise TypeError("child runtime composition requires ResearchProgram")
    if not isinstance(base, MethodRuntimePortInventory):
        raise TypeError("child runtime composition requires MethodRuntimePortInventory")
    if not isinstance(journal, MachineJournalPort):
        raise TypeError("child runtime composition requires MachineJournalPort")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("child runtime composition max_steps must be positive")

    owned_components = tuple(
        (definition, method, component)
        for definition in program.definitions
        if type(definition.implementation) is ResearchMethodImplementation
        for method in (definition.implementation.resolve(),)
        for component in method.components
    )
    if not owned_components:
        return base

    host_ids = tuple(
        component.host_id
        for _definition, _method, component in owned_components
    )
    if len(host_ids) != len(set(host_ids)):
        raise ValueError(
            "Method-owned component host ids must be unique within one ResearchProgram"
        )

    registry = ChildResearchHostRegistry()
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

    declared_executor = registry.executor()
    child_port: MethodChildMachinePort = ProgramScopedChildMachineRouter(
        declared_executor,
        registry.host_ids(),
        base.child_machines,
    )
    return MethodRuntimePortInventory(
        agent_loop=base.agent_loop,
        capabilities=base.capabilities,
        child_machines=child_port,
        schemas=base.schemas,
    )


__all__ = [
    "ProgramScopedChildMachineRouter",
    "compose_program_method_runtime_inventory",
]
