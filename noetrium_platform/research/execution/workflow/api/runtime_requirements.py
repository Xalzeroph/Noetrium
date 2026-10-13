from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .method_machine import (
    MethodNodeKind,
    NoetriumUnit,
    MethodRuntimeContext,
    MethodRuntimePort,
    method_program_required_runtime_ports,
    method_program_required_capabilities,
    method_program_state_schema,
    method_program_input_schema,
    method_program_output_schema,
    method_program_nodes,
    method_program_evidence_obligations,
    method_node_kind,
    method_node_agent_id,
    method_node_agent_targets,
    method_node_capability_id,
    method_node_capability_targets,
    method_node_input_schema,
    method_node_output_schema,
)

from .method_machine import (
    method_node_agent_id,
    method_node_agent_targets,
    method_node_capability_id,
    method_node_capability_targets,
    method_node_input_schema,
    method_node_output_schema,
    method_node_evidence_obligations,
    method_program_evidence_obligations,
    method_program_input_schema,
    method_program_nodes,
    method_program_output_schema,
    method_program_required_capabilities,
    method_program_required_runtime_ports,
    method_program_state_schema,
    validate_method_program,
)

def _canonical(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class MethodRuntimeRequirements:
    """Complete statically knowable runtime closure for one NoetriumUnit."""

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
            MethodRuntimePort.UNIT_ACTIVATION: runtime.unit_activation,
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


_METHOD_RUNTIME_REQUIREMENTS_CACHE: dict[str, MethodRuntimeRequirements] = {}
_METHOD_RUNTIME_REQUIREMENTS_LOCK = RLock()
_METHOD_RUNTIME_REQUIREMENTS_CACHE_LIMIT = 131072


def _analyze_method_runtime_requirements_uncached(
    program: NoetriumUnit,
) -> MethodRuntimeRequirements:
    ports = set(method_program_required_runtime_ports(program))
    agent_ids: set[str] = set()
    capability_ids = set(method_program_required_capabilities(program))
    if capability_ids:
        ports.add(MethodRuntimePort.CAPABILITIES)
    schema_required = any(
        schema != "json"
        for schema in (
            method_program_state_schema(program),
            method_program_input_schema(program),
            method_program_output_schema(program),
        )
    )

    for node in method_program_nodes(program):
        if method_node_kind(node) is MethodNodeKind.AGENT:
            ports.add(MethodRuntimePort.AGENT_LOOP)
            if method_node_agent_id(node) is not None:
                agent_ids.add(method_node_agent_id(node))
            agent_ids.update(method_node_agent_targets(node))
        elif method_node_kind(node) is MethodNodeKind.CAPABILITY:
            ports.add(MethodRuntimePort.CAPABILITIES)
            if method_node_capability_id(node) is not None:
                capability_ids.add(method_node_capability_id(node))
            capability_ids.update(method_node_capability_targets(node))
        if method_node_input_schema(node) != "json" or method_node_output_schema(node) != "json":
            schema_required = True

    if schema_required:
        ports.add(MethodRuntimePort.SCHEMAS)

    return MethodRuntimeRequirements(
        ports=tuple(sorted(ports, key=lambda value: value.value)),
        agent_ids=_canonical(agent_ids),
        capability_ids=_canonical(capability_ids),
        evidence_obligations=_canonical(set(method_program_evidence_obligations(program))),
    )


def analyze_method_runtime_requirements(
    program: NoetriumUnit,
) -> MethodRuntimeRequirements:
    if not isinstance(program, NoetriumUnit):
        raise TypeError("runtime requirement analysis requires NoetriumUnit")
    key = program.unit_digest
    with _METHOD_RUNTIME_REQUIREMENTS_LOCK:
        cached = _METHOD_RUNTIME_REQUIREMENTS_CACHE.get(key)
        if cached is not None:
            return cached
    resolved = _analyze_method_runtime_requirements_uncached(program)
    with _METHOD_RUNTIME_REQUIREMENTS_LOCK:
        current = _METHOD_RUNTIME_REQUIREMENTS_CACHE.setdefault(key, resolved)
        if current.digest != resolved.digest:
            raise RuntimeError(
                "immutable Method Unit produced multiple runtime requirement identities"
            )
        if len(_METHOD_RUNTIME_REQUIREMENTS_CACHE) > _METHOD_RUNTIME_REQUIREMENTS_CACHE_LIMIT:
            oldest = next(iter(_METHOD_RUNTIME_REQUIREMENTS_CACHE))
            if oldest != key:
                _METHOD_RUNTIME_REQUIREMENTS_CACHE.pop(oldest, None)
        return current


__all__ = [
    "MethodRuntimeRequirements",
    "analyze_method_runtime_requirements",
]
