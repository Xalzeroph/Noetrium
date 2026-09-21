from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .method_machine import (
    MethodNodeKind,
    MethodProgram,
    MethodRuntimeContext,
    MethodRuntimePort,
)


def _canonical(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class MethodRuntimeRequirements:
    """Complete statically knowable runtime closure for one MethodProgram."""

    ports: tuple[MethodRuntimePort, ...]
    agent_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    evidence_obligations: tuple[str, ...] = ()
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.ports) is not tuple or any(
            not isinstance(value, MethodRuntimePort) for value in self.ports
        ):
            raise TypeError("method runtime requirement ports must contain MethodRuntimePort")
        if self.ports != tuple(sorted(self.ports, key=lambda value: value.value)):
            raise ValueError("method runtime requirement ports must be canonically sorted")
        if len(self.ports) != len(set(self.ports)):
            raise ValueError("method runtime requirement ports must be unique")
        for name, values in (
            ("agent_ids", self.agent_ids),
            ("capability_ids", self.capability_ids),
            ("evidence_obligations", self.evidence_obligations),
        ):
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"method runtime requirement {name} must be text tuple")
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(
                    f"method runtime requirement {name} must be sorted and unique"
                )
        object.__setattr__(self, "digest", canonical_digest({
            "schema": "noetrium.method-runtime-requirements.v1",
            "ports": tuple(value.value for value in self.ports),
            "agent_ids": self.agent_ids,
            "capability_ids": self.capability_ids,
            "evidence_obligations": self.evidence_obligations,
        }))

    def missing_ports(
        self,
        runtime: MethodRuntimeContext,
    ) -> tuple[MethodRuntimePort, ...]:
        if not isinstance(runtime, MethodRuntimeContext):
            raise TypeError("runtime requirement check requires MethodRuntimeContext")
        available = {
            MethodRuntimePort.AGENT_LOOP: runtime.agent_loop,
            MethodRuntimePort.CAPABILITIES: runtime.capabilities,
            MethodRuntimePort.CHILD_MACHINES: runtime.child_machines,
            MethodRuntimePort.SCHEMAS: runtime.schemas,
        }
        return tuple(port for port in self.ports if available[port] is None)

    def require(self, runtime: MethodRuntimeContext) -> None:
        missing = self.missing_ports(runtime)
        if missing:
            raise RuntimeError(
                "method runtime binding missing required ports: "
                + ", ".join(value.value for value in missing)
            )


def analyze_method_runtime_requirements(
    program: MethodProgram,
) -> MethodRuntimeRequirements:
    if not isinstance(program, MethodProgram):
        raise TypeError("runtime requirement analysis requires MethodProgram")

    ports = set(program.required_runtime_ports)
    agent_ids: set[str] = set()
    capability_ids = set(program.required_capabilities)
    schema_required = any(
        schema != "json"
        for schema in (
            program.state_schema,
            program.input_schema,
            program.output_schema,
        )
    )

    for node in program.graph.nodes:
        if node.kind is MethodNodeKind.AGENT:
            ports.add(MethodRuntimePort.AGENT_LOOP)
            if node.agent_id is not None:
                agent_ids.add(node.agent_id)
            agent_ids.update(node.agent_targets)
        elif node.kind is MethodNodeKind.CAPABILITY:
            ports.add(MethodRuntimePort.CAPABILITIES)
            if node.capability_id is not None:
                capability_ids.add(node.capability_id)
            capability_ids.update(node.capability_targets)
        if node.input_schema != "json" or node.output_schema != "json":
            schema_required = True

    if schema_required:
        ports.add(MethodRuntimePort.SCHEMAS)

    return MethodRuntimeRequirements(
        ports=tuple(sorted(ports, key=lambda value: value.value)),
        agent_ids=_canonical(agent_ids),
        capability_ids=_canonical(capability_ids),
        evidence_obligations=_canonical(set(program.evidence_obligations)),
    )


__all__ = [
    "MethodRuntimeRequirements",
    "analyze_method_runtime_requirements",
]
