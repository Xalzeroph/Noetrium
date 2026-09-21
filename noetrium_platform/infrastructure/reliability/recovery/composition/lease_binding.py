from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceLeasePort,
    ResourceOwnershipPort,
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteResourceLeaseRegistry,
)

from ..api import RecoveryLeaseStatePort
from ..runtime.lease_adapter import RecoveryLeaseAdapter


def compose_sqlite_recovery_lease(
    database: str | Path,
) -> RecoveryLeaseStatePort:
    """Project recovery ownership from the canonical resource lease authority."""

    path = Path(database)
    resources = SQLiteResourceLeaseRegistry(path)
    return RecoveryLeaseAdapter(
        resources,
        resources,
        evidence_refs=(f"sqlite-resource-authority:{path.absolute()}",),
    )




def compose_resource_recovery_lease(
    ownership: ResourceOwnershipPort,
    leases: ResourceLeasePort,
    *,
    evidence_refs: tuple[str, ...] = (),
) -> RecoveryLeaseStatePort:
    """Project the platform's canonical resource authority into recovery ownership."""

    return RecoveryLeaseAdapter(
        ownership,
        leases,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "compose_resource_recovery_lease",
    "compose_sqlite_recovery_lease",
]
