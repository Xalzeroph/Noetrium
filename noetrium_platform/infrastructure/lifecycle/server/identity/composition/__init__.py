from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.governance.architecture.api.capabilities import (
    HOST_OPERATING_SYSTEM_ROUTE_V1,
    SERVER_CONNECTION_FACTORY_V1,
    SERVER_FILE_TRANSFER_FACTORY_V1,
)
from noetrium_platform.foundation.governance.architecture.api.capability_composition import (
    BindingPlan,
    CapabilityOffer,
    CapabilityRequirement,
    CompositionContract,
    CompositionIdentity,
    CompositionSubject,
    RequirementAddress,
    interface_contract_digest,
    CapabilityCompositionPlannerPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerConnectionFactoryPort,
    ServerFileTransferFactoryPort,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity

from noetrium_platform.infrastructure.lifecycle.server.identity.providers import (
    EnvironmentSSHServerConnectionFactory,
    EnvironmentSSHServerFileTransferFactory,
)


_SERVER_IDENTITY_SYSTEM = SystemIdentity("runtime", ("server", "identity"))
_SERVER_IDENTITY_SUBJECT = CompositionSubject.system_subject(_SERVER_IDENTITY_SYSTEM)


@dataclass(frozen=True, slots=True)
class ServerIdentityComposition:
    """Explicit server-identity assembly with its immutable binding evidence."""

    connection_factory: ServerConnectionFactoryPort
    file_transfer_factory: ServerFileTransferFactoryPort
    plan: BindingPlan
    connection_factory_offer: CapabilityOffer
    file_transfer_factory_offer: CapabilityOffer


def compose_environment_server_identity(
    *,
    operating_system: OperatingSystemRoute,
    host_operating_system_offer: CapabilityOffer,
    planner: CapabilityCompositionPlannerPort,
    task_group: TaskGroupPort,
    scope: ScopeIdentity = PLATFORM_SCOPE,
    parent_plan_digest: str | None = None,
) -> ServerIdentityComposition:
    """Bind environment-backed SSH identity to the host OS route explicitly."""

    host_requirement = CapabilityRequirement(
        RequirementAddress(_SERVER_IDENTITY_SUBJECT, "host-operating-system-route"),
        scope,
        HOST_OPERATING_SYSTEM_ROUTE_V1,
        interface_contract_digest(OperatingSystemRoute),
    )
    factory_offer = CapabilityOffer(
        offer_id="runtime.server.environment-ssh-connection-factory",
        owner=_SERVER_IDENTITY_SUBJECT,
        scope=scope,
        capability=SERVER_CONNECTION_FACTORY_V1,
        interface_digest=interface_contract_digest(ServerConnectionFactoryPort),
        provider_identity="runtime.server.environment-ssh-connection-factory.v1",
        configuration_digest=canonical_digest(
            {"provider": "environment-ssh", "host_offer": host_operating_system_offer.offer_id}
        ),
    )
    transfer_factory_offer = CapabilityOffer(
        offer_id="runtime.server.environment-ssh-file-transfer-factory",
        owner=_SERVER_IDENTITY_SUBJECT,
        scope=scope,
        capability=SERVER_FILE_TRANSFER_FACTORY_V1,
        interface_digest=interface_contract_digest(ServerFileTransferFactoryPort),
        provider_identity="runtime.server.environment-ssh-file-transfer-factory.v1",
        configuration_digest=canonical_digest(
            {"provider": "environment-ssh-scp", "host_offer": host_operating_system_offer.offer_id}
        ),
    )
    plan = planner.freeze(
        CompositionIdentity(
            "runtime.server.identity",
            scope,
            owner=_SERVER_IDENTITY_SUBJECT,
            parent_plan_digest=parent_plan_digest,
        ),
        (
            CompositionContract(
                _SERVER_IDENTITY_SUBJECT,
                scope,
                offers=(factory_offer, transfer_factory_offer),
                requirements=(host_requirement,),
            ),
        ),
        imported_offers=(host_operating_system_offer,),
    )
    process_runner = build_process_command_runner(task_group)
    factory = EnvironmentSSHServerConnectionFactory(
        operating_system,
        process_runner=process_runner,
    )
    transfer_factory = EnvironmentSSHServerFileTransferFactory(
        operating_system,
        process_runner=process_runner,
    )
    return ServerIdentityComposition(
        factory,
        transfer_factory,
        plan,
        factory_offer,
        transfer_factory_offer,
    )


__all__ = ["ServerIdentityComposition", "compose_environment_server_identity"]
