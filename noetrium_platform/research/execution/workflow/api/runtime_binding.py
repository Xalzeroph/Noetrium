from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_driver import UnitActivationRuntimePort

from noetrium_platform.foundation.kernel.structure import structure_unit

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import CapabilityPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from . import (
    AsyncMethodAgentLoopPort,
    MethodAgentLoopPort,
    NoetriumUnit,
    MethodRuntimePort,
    MethodSchemaPort,
    analyze_method_runtime_requirements,
)


@runtime_checkable
class ProgramScopedCapabilityPort(CapabilityPort, Protocol):
    """Resolve one exact capability surface from frozen NoetriumUnit identity."""

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
    by composition and its identity is frozen before a NoetriumUnit is bound.
    """

    agent_loop: MethodAgentLoopPort | AsyncMethodAgentLoopPort | None = None
    capabilities: CapabilityPort | None = None
    unit_activation: UnitActivationRuntimePort | None = None
    schemas: MethodSchemaPort | None = None
    _identity_digest: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.agent_loop is not None and not isinstance(
            self.agent_loop, (MethodAgentLoopPort, AsyncMethodAgentLoopPort)
        ):
            raise TypeError("method runtime inventory agent_loop has invalid port type")
        if self.capabilities is not None and not isinstance(self.capabilities, CapabilityPort):
            raise TypeError("method runtime inventory capabilities has invalid port type")
        if self.unit_activation is not None and not isinstance(
            self.unit_activation, UnitActivationRuntimePort
        ):
            raise TypeError("method runtime inventory unit_activation has invalid port type")
        if self.schemas is not None and not isinstance(self.schemas, MethodSchemaPort):
            raise TypeError("method runtime inventory schemas has invalid port type")
        rows = []
        for name, value in (
            ("agent_loop", self.agent_loop),
            ("capabilities", self.capabilities),
            ("unit_activation", self.unit_activation),
            ("schemas", self.schemas),
        ):
            if value is not None:
                rows.append((name, _identity_digest(value, name)))
        object.__setattr__(
            self,
            "_identity_digest",
            canonical_digest({
                "inventory": "method-runtime-ports.v1",
                "ports": tuple(rows),
            }),
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def for_program_scope(
        self,
        program_scope_id: str | None,
    ) -> "MethodRuntimePortInventory":
        """Freeze multiplexed capabilities to one canonical Program Unit scope."""
        capabilities = self.capabilities
        if not isinstance(capabilities, ProgramScopedCapabilityPort):
            return self
        if program_scope_id is None:
            bound_capabilities = None
        else:
            if type(program_scope_id) is not str or not program_scope_id.strip():
                raise ValueError(
                    "program-scoped capability binding requires canonical Program scope id"
                )
            bound_capabilities = capabilities.for_program(program_scope_id)
            if isinstance(bound_capabilities, ProgramScopedCapabilityPort):
                raise RuntimeError(
                    "program-scoped capability binding did not converge to an exact capability surface"
                )
        return MethodRuntimePortInventory(
            agent_loop=self.agent_loop,
            capabilities=bound_capabilities,
            unit_activation=self.unit_activation,
            schemas=self.schemas,
        )


METHOD_RUNTIME_BINDING_TRAIT = "method.runtime-binding"

def require_method_runtime_binding(plan: NoetriumUnit) -> NoetriumUnit:
    if type(plan) is not NoetriumUnit or not plan.has_trait(METHOD_RUNTIME_BINDING_TRAIT):
        raise TypeError("method runtime binding must be NoetriumUnit")
    return plan

def method_runtime_binding_value(plan: NoetriumUnit, name: str):
    require_method_runtime_binding(plan)
    return plan.parameters[name]

def method_runtime_binding_digest(plan: NoetriumUnit) -> str:
    require_method_runtime_binding(plan); return plan.semantic_digest

def method_runtime_binding_complete(plan: NoetriumUnit) -> bool:
    require_method_runtime_binding(plan)
    return not (plan.parameters["missing_ports"] or plan.parameters["missing_agent_ids"] or plan.parameters["missing_capability_ids"])

def require_complete_method_runtime_binding(plan: NoetriumUnit) -> None:
    if method_runtime_binding_complete(plan): return
    reasons=[f"port:{x}" for x in plan.parameters["missing_ports"]]
    reasons += [f"agent:{x}" for x in plan.parameters["missing_agent_ids"]]
    reasons += [f"capability:{x}" for x in plan.parameters["missing_capability_ids"]]
    raise RuntimeError("method runtime auto-binding incomplete: " + ", ".join(reasons))


_METHOD_RUNTIME_BINDING_PLAN_CACHE: dict[tuple[str, str], NoetriumUnit] = {}
_METHOD_RUNTIME_BINDING_PLAN_LOCK = RLock()
_METHOD_RUNTIME_BINDING_PLAN_CACHE_LIMIT = 262144


def _plan_method_runtime_binding_uncached(
    program: NoetriumUnit,
    inventory: MethodRuntimePortInventory,
) -> NoetriumUnit:
    requirements = analyze_method_runtime_requirements(program)
    selected: list[tuple[str, str]] = []
    missing_ports: list[MethodRuntimePort] = []
    missing_agents: list[str] = []
    missing_capabilities: list[str] = []

    for port in requirements.ports:
        value = {
            MethodRuntimePort.AGENT_LOOP: inventory.agent_loop,
            MethodRuntimePort.CAPABILITIES: inventory.capabilities,
            MethodRuntimePort.UNIT_ACTIVATION: inventory.unit_activation,
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
    return structure_unit(
        "method-runtime-binding:" + canonical_digest(payload)[:24],
        traits=(METHOD_RUNTIME_BINDING_TRAIT,),
        parameters={
            "requirements_digest": requirements.digest,
            "inventory_digest": inventory.identity_digest,
            "selected_port_digests": selected_rows,
            "missing_ports": tuple(item.value for item in missing_port_rows),
            "missing_agent_ids": missing_agent_rows,
            "missing_capability_ids": missing_capability_rows,
        },
    )


def plan_method_runtime_binding(
    program: NoetriumUnit,
    inventory: MethodRuntimePortInventory,
) -> NoetriumUnit:
    if not isinstance(program, NoetriumUnit):
        raise TypeError("method runtime binding plan requires NoetriumUnit")
    if not isinstance(inventory, MethodRuntimePortInventory):
        raise TypeError("method runtime binding plan requires MethodRuntimePortInventory")
    key = (program.unit_digest, inventory.identity_digest)
    with _METHOD_RUNTIME_BINDING_PLAN_LOCK:
        cached = _METHOD_RUNTIME_BINDING_PLAN_CACHE.get(key)
        if cached is not None:
            return cached
    plan = _plan_method_runtime_binding_uncached(program, inventory)
    with _METHOD_RUNTIME_BINDING_PLAN_LOCK:
        current = _METHOD_RUNTIME_BINDING_PLAN_CACHE.setdefault(key, plan)
        if current.semantic_digest != plan.semantic_digest:
            raise RuntimeError(
                "immutable Method/runtime inventory produced multiple binding plans"
            )
        if len(_METHOD_RUNTIME_BINDING_PLAN_CACHE) > _METHOD_RUNTIME_BINDING_PLAN_CACHE_LIMIT:
            oldest = next(iter(_METHOD_RUNTIME_BINDING_PLAN_CACHE))
            if oldest != key:
                _METHOD_RUNTIME_BINDING_PLAN_CACHE.pop(oldest, None)
        return current


__all__ = [
    "METHOD_RUNTIME_BINDING_TRAIT",
    "method_runtime_binding_complete",
    "method_runtime_binding_digest",
    "method_runtime_binding_value",
    "require_complete_method_runtime_binding",
    "require_method_runtime_binding",
    "MethodRuntimePortInventory",
    "ProgramScopedCapabilityPort",
    "plan_method_runtime_binding",
]
