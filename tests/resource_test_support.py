from __future__ import annotations

from pathlib import Path
import tempfile

from noetrium_platform.composition.platform_meta import (
    PlatformMetaAuthorities,
    build_platform_meta,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority


def make_resource_authority(root: Path | None = None) -> UniversalResourceAuthority:
    resolved = (
        Path(tempfile.mkdtemp(prefix="noetrium-resource-test-"))
        if root is None
        else Path(root)
    )
    resolved.mkdir(parents=True, exist_ok=True)
    return UniversalResourceAuthority(resolved / "platform-resources.sqlite")


def make_execution_pool(**kwargs) -> ResearchExecutionPool:
    authority = kwargs.pop("resource_authority", None)
    if authority is None:
        authority = make_resource_authority()
    return ResearchExecutionPool(
        resource_authority=authority,
        **kwargs,
    )


def build_test_platform_meta(
    root: Path,
    **kwargs,
) -> PlatformMetaAuthorities:
    root = Path(root)
    authority = kwargs.pop("resource_authority", None)
    if authority is None:
        authority = make_resource_authority(root)
    return build_platform_meta(
        root,
        resource_authority=authority,
        **kwargs,
    )


__all__ = [
    "build_test_directory_authorities",
    "build_test_platform_meta",
    "make_execution_pool",
    "make_resource_authority",
    "make_resource_competition_reservations",
]


def make_resource_competition_reservations(
    root: Path | None = None,
    *,
    ttl_seconds: float = 30.0,
):
    from uuid import uuid4
    from noetrium_platform.composition.shared_host_pressure import (
        ResourceCompetitionReservations,
    )

    root = (
        Path(tempfile.mkdtemp(prefix="noetrium-resource-competition-test-"))
        if root is None
        else Path(root)
    )
    authority = make_resource_authority(root)
    owner = uuid4().hex
    lease = authority.acquire_ttl_lease(
        lease_id="test-resource-competition-owner:" + owner,
        resource_key="test-resource-competition-owner:" + owner,
        holder_key="test-resource-competition-owner:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=ttl_seconds,
        metadata={"kind": "resource-competition-owner-test"},
    )
    reservations = ResourceCompetitionReservations(
        authority,
        lease,
        coordination_directory=root / "coordination",
    )
    return authority, lease, reservations


def build_test_directory_authorities(layout):
    from noetrium_platform.infrastructure.resources.directory.composition import (
        build_local_directory_authorities,
    )

    authority = make_resource_authority(
        Path(layout.state) / ".resource-authority"
    )
    return build_local_directory_authorities(layout, authority)
