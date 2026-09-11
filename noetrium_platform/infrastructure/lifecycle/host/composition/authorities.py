from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.governance.architecture.api.capabilities import (
    HOST_OPERATING_SYSTEM_ROUTE_V1,
)
from noetrium_platform.foundation.governance.architecture.api.capability_composition import (
    BindingPlan,
    CapabilityOffer,
    CompositionContract,
    CompositionIdentity,
    CompositionSubject,
    interface_contract_digest,
    CapabilityCompositionPlannerPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity

from ..api import OperatingSystemRoute
from ..providers import LocalOperatingSystemRoute


_HOST_SYSTEM = SystemIdentity("runtime", ("host",))
_HOST_SUBJECT = CompositionSubject.system_subject(_HOST_SYSTEM)


@dataclass(frozen=True, slots=True)
class HostComposition:
    """Frozen host binding evidence plus the one injected runtime port."""

    operating_system: OperatingSystemRoute
    plan: BindingPlan
    operating_system_offer: CapabilityOffer


def compose_local_host(
    *,
    planner: CapabilityCompositionPlannerPort,
    scope: ScopeIdentity = PLATFORM_SCOPE,
    parent_plan_digest: str | None = None,
) -> HostComposition:
    """Select the local host provider at one explicit composition root.

    Runtime modules must receive ``OperatingSystemRoute`` directly; they never
    construct this provider or ask a container to find it.
    """

    operating_system = LocalOperatingSystemRoute()
    offer = CapabilityOffer(
        offer_id="runtime.host.local-operating-system-route",
        owner=_HOST_SUBJECT,
        scope=scope,
        capability=HOST_OPERATING_SYSTEM_ROUTE_V1,
        interface_digest=interface_contract_digest(OperatingSystemRoute),
        provider_identity="runtime.host.local-operating-system-route.v1",
        configuration_digest=canonical_digest(
            {
                "family": operating_system.identity.family,
                "system_name": operating_system.identity.system_name,
                "release": operating_system.identity.release,
                "machine": operating_system.identity.machine,
            }
        ),
    )
    plan = planner.freeze(
        CompositionIdentity(
            "runtime.host",
            scope,
            owner=_HOST_SUBJECT,
            parent_plan_digest=parent_plan_digest,
        ),
        (CompositionContract(_HOST_SUBJECT, scope, offers=(offer,)),),
    )
    return HostComposition(operating_system, plan, offer)


def local_operating_system_route() -> OperatingSystemRoute:
    """Select the one local host route for higher-level composition."""

    return LocalOperatingSystemRoute()


__all__ = ["HostComposition", "compose_local_host", "local_operating_system_route"]
