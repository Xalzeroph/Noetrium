"""Explicit Participant/Method composition with reproducible provider evidence."""
from __future__ import annotations


from dataclasses import dataclass

from noetrium_platform.substrate.api import (
    METHOD_COMPOSITION_PORTS_V1,
)
from noetrium_platform.substrate.api import (
    CapabilityOffer,
    CompositionContract,
    CompositionIdentity,
    CompositionSubject,
    interface_contract_digest,
)
from noetrium_platform.substrate.api import (
    CapabilityCompositionPlannerPort,
)
from noetrium_platform.substrate.api import SystemIdentity
from noetrium_platform.capabilities.participant.method.api import (
    MethodCompositionPorts,
    MethodEndpointBinder,
    MethodObservationOutboxBuilder,
    MethodSystemBinding,
)
from noetrium_platform.capabilities.participant.method.runtime import (
    bind_method_endpoint,
    build_method_observation_outbox,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import PLATFORM_SCOPE, NoetriumUnit


_METHOD_SYSTEM = SystemIdentity("participant")
_METHOD_SUBJECT = CompositionSubject.system_subject(_METHOD_SYSTEM)


@dataclass(frozen=True, slots=True)
class MethodSystemProviders:
    """Concrete method-system providers chosen only by a composition root."""

    bind_endpoint: MethodEndpointBinder
    build_observation_outbox: MethodObservationOutboxBuilder
    provider_identity: str
    configuration_digest: str


def compose_method_system(
    *,
    providers: MethodSystemProviders,
    planner: CapabilityCompositionPlannerPort,
    scope: NoetriumUnit = PLATFORM_SCOPE,
    parent_plan_digest: str | None = None,
) -> MethodSystemBinding:
    """Expose participant-method composition ports without a hidden default."""

    offer = CapabilityOffer(
        offer_id="participant.method.composition-ports",
        owner=_METHOD_SUBJECT,
        scope=scope,
        capability=METHOD_COMPOSITION_PORTS_V1,
        interface_digest=interface_contract_digest(MethodCompositionPorts),
        provider_identity=providers.provider_identity,
        configuration_digest=providers.configuration_digest,
    )
    plan = planner.freeze(
        CompositionIdentity(
            "participant.method",
            scope,
            owner=_METHOD_SUBJECT,
            parent_plan_digest=parent_plan_digest,
        ),
        (CompositionContract(_METHOD_SUBJECT, scope, offers=(offer,)),),
    )
    return MethodSystemBinding(
        ports=MethodCompositionPorts(
            bind_endpoint=providers.bind_endpoint,
            build_observation_outbox=providers.build_observation_outbox,
        ),
        plan=plan,
        offer=offer,
    )


def compose_default_method_system(
    *,
    planner: CapabilityCompositionPlannerPort,
    scope: NoetriumUnit = PLATFORM_SCOPE,
    parent_plan_digest: str | None = None,
) -> MethodSystemBinding:
    """Select the platform's default method providers at the system boundary."""

    return compose_method_system(
        providers=MethodSystemProviders(
            bind_endpoint=bind_method_endpoint,
            build_observation_outbox=build_method_observation_outbox,
            provider_identity="participant.method.default-composition.v1",
            configuration_digest=canonical_digest(
                {
                    "bind_endpoint": "participant.method.default-endpoint.v2",
                    "build_observation_outbox": "participant.method.default-outbox.v2",
                }
            ),
        ),
        planner=planner,
        scope=scope,
        parent_plan_digest=parent_plan_digest,
    )


__all__ = [
    "MethodSystemProviders",
    "compose_default_method_system",
    "compose_method_system",
]
