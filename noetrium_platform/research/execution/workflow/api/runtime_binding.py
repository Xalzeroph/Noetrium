from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import CapabilityPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from . import (
    AsyncMethodAgentLoopPort,
    MethodAgentLoopPort,
    MethodChildMachinePort,
    MethodProgram,
    MethodRuntimePort,
    MethodSchemaPort,
    analyze_method_runtime_requirements,
)


@runtime_checkable
class ProgramScopedCapabilityPort(CapabilityPort, Protocol):
    """Resolve one exact capability surface from frozen ResearchProgram identity."""

    @property
    def identity_digest(self) -> str: ...

    def for_program(self, program_id: str) -> CapabilityPort | None: ...


def _identity_digest(value: object, name: str) -> str:
    digest = getattr(value, "identity_digest", None)
    return require_sha256(digest, f"method runtime inventory {name} identity_digest")


def _agent_closure(loop: object) -> tuple[str, ...] | None:
    values = getattr(loop, "agent_ids", None)
    if values is not None:
        if type(values) is not tuple or any(type(item) is not str or not item.strip() for item in values):
            raise TypeError("method agent-loop agent_ids must be a tuple of non-empty text")
        return tuple(sorted(set(values)))
    binding = getattr(loop, "binding", None)
    agent_id = getattr(binding, "agent_id", None)
    if isinstance(agent_id, str) and agent_id.strip():
        return (agent_id,)
    return None


@dataclass(frozen=True, slots=True)
class MethodRuntimePortInventory:
    """Explicit reusable providers eligible for requirement-driven Method binding.

    This is an inventory, not a service locator: all concrete providers are passed
    by composition and its identity is frozen before a MethodProgram is bound.
    """

    agent_loop: MethodAgentLoopPort | AsyncMethodAgentLoopPort | None = None
    capabilities: CapabilityPort | None = None
    child_machines: MethodChildMachinePort | None = None
    schemas: MethodSchemaPort | None = None

    def __post_init__(self) -> None:
        if self.agent_loop is not None and not isinstance(
            self.agent_loop, (MethodAgentLoopPort, AsyncMethodAgentLoopPort)
        ):
            raise TypeError("method runtime inventory agent_loop has invalid port type")
        if self.capabilities is not None and not isinstance(self.capabilities, CapabilityPort):
            raise TypeError("method runtime inventory capabilities has invalid port type")
        if self.child_machines is not None and not isinstance(
            self.child_machines, MethodChildMachinePort
        ):
            raise TypeError("method runtime inventory child_machines has invalid port type")
        if self.schemas is not None and not isinstance(self.schemas, MethodSchemaPort):
            raise TypeError("method runtime inventory schemas has invalid port type")
        for name, value in (
            ("agent_loop", self.agent_loop),
            ("capabilities", self.capabilities),
            ("child_machines", self.child_machines),
            ("schemas", self.schemas),
        ):
            if value is not None:
                _identity_digest(value, name)

    @property
    def identity_digest(self) -> str:
        rows = []
        for name, value in (
            ("agent_loop", self.agent_loop),
            ("capabilities", self.capabilities),
            ("child_machines", self.child_machines),
            ("schemas", self.schemas),
        ):
            if value is not None:
                rows.append((name, _identity_digest(value, name)))
        return canonical_digest({
            "inventory": "method-runtime-ports.v1",
            "ports": tuple(rows),
        })


@dataclass(frozen=True, slots=True)
class MethodRuntimeBindingPlan:
    requirements_digest: str
    inventory_digest: str
    selected_port_digests: tuple[tuple[str, str], ...]
    missing_ports: tuple[MethodRuntimePort, ...]
    missing_agent_ids: tuple[str, ...]
    missing_capability_ids: tuple[str, ...]
    digest: str

    @property
    def complete(self) -> bool:
        return not (
            self.missing_ports
            or self.missing_agent_ids
            or self.missing_capability_ids
        )

    def require_complete(self) -> None:
        if self.complete:
            return
        reasons = [f"port:{item.value}" for item in self.missing_ports]
        reasons.extend(f"agent:{item}" for item in self.missing_agent_ids)
        reasons.extend(f"capability:{item}" for item in self.missing_capability_ids)
        raise RuntimeError(
            "method runtime auto-binding incomplete: " + ", ".join(reasons)
        )


def plan_method_runtime_binding(
    program: MethodProgram,
    inventory: MethodRuntimePortInventory,
) -> MethodRuntimeBindingPlan:
    if not isinstance(program, MethodProgram):
        raise TypeError("method runtime binding plan requires MethodProgram")
    if not isinstance(inventory, MethodRuntimePortInventory):
        raise TypeError("method runtime binding plan requires MethodRuntimePortInventory")
    requirements = analyze_method_runtime_requirements(program)
    selected: list[tuple[str, str]] = []
    missing_ports: list[MethodRuntimePort] = []
    missing_agents: list[str] = []
    missing_capabilities: list[str] = []

    for port in requirements.ports:
        value = {
            MethodRuntimePort.AGENT_LOOP: inventory.agent_loop,
            MethodRuntimePort.CAPABILITIES: inventory.capabilities,
            MethodRuntimePort.CHILD_MACHINES: inventory.child_machines,
            MethodRuntimePort.SCHEMAS: inventory.schemas,
        }[port]
        if value is None:
            missing_ports.append(port)
        else:
            selected.append((port.value, _identity_digest(value, port.value)))

    if requirements.agent_ids and inventory.agent_loop is not None:
        closure = _agent_closure(inventory.agent_loop)
        if closure is None:
            missing_agents.extend(requirements.agent_ids)
        else:
            missing_agents.extend(sorted(set(requirements.agent_ids) - set(closure)))

    if requirements.capability_ids and inventory.capabilities is not None:
        for capability_id in requirements.capability_ids:
            try:
                descriptor = inventory.capabilities.describe(capability_id)
            except (KeyError, LookupError):
                missing_capabilities.append(capability_id)
                continue
            if descriptor.capability_id != capability_id:
                raise RuntimeError(
                    "method capability binding returned a different descriptor identity: "
                    f"requested={capability_id!r} got={descriptor.capability_id!r}"
                )

    selected_rows = tuple(sorted(selected))
    missing_port_rows = tuple(sorted(set(missing_ports), key=lambda item: item.value))
    missing_agent_rows = tuple(sorted(set(missing_agents)))
    missing_capability_rows = tuple(sorted(set(missing_capabilities)))
    payload = {
        "schema": "method-runtime-binding-plan.v1",
        "requirements_digest": requirements.digest,
        "inventory_digest": inventory.identity_digest,
        "selected_port_digests": selected_rows,
        "missing_ports": tuple(item.value for item in missing_port_rows),
        "missing_agent_ids": missing_agent_rows,
        "missing_capability_ids": missing_capability_rows,
    }
    return MethodRuntimeBindingPlan(
        requirements_digest=requirements.digest,
        inventory_digest=inventory.identity_digest,
        selected_port_digests=selected_rows,
        missing_ports=missing_port_rows,
        missing_agent_ids=missing_agent_rows,
        missing_capability_ids=missing_capability_rows,
        digest=canonical_digest(payload),
    )


__all__ = [
    "MethodRuntimeBindingPlan",
    "MethodRuntimePortInventory",
    "ProgramScopedCapabilityPort",
    "plan_method_runtime_binding",
]
