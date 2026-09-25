from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from noetrium_platform.foundation.governance.api import ScopeIdentity
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
)


MANAGED_CONTAINER_LABEL = "io.noetrium.managed"
MANAGED_CONTAINER_LABEL_VALUE = "leased-container-v1"

LABEL_AUTHORITY = "io.noetrium.authority-id"
LABEL_OWNER_GENERATION = "io.noetrium.owner-generation-id"
LABEL_ALLOCATION = "io.noetrium.allocation-id"
LABEL_LEASE = "io.noetrium.lease-id"
LABEL_FENCING = "io.noetrium.fencing-token"
LABEL_RUNTIME = "io.noetrium.runtime-identity"
LABEL_HOLDER = "io.noetrium.holder-scope"


@dataclass(frozen=True, slots=True)
class DockerContainerObservation:
    container_id: str
    name: str
    image: str
    running: bool
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        if (
            not self.container_id.strip()
            or not self.name.strip()
            or not self.image.strip()
        ):
            raise ValueError("Docker container observation identity is incomplete")


@dataclass(frozen=True, slots=True)
class DockerContainerLeasePolicy:
    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.ttl_seconds)) or self.ttl_seconds <= 0:
            raise ValueError("container lease ttl_seconds must be finite and > 0")
        if (
            not math.isfinite(float(self.renewal_interval_seconds))
            or self.renewal_interval_seconds <= 0
        ):
            raise ValueError(
                "container lease renewal_interval_seconds must be finite and > 0"
            )
        if self.renewal_interval_seconds >= self.ttl_seconds:
            raise ValueError("container lease renewal interval must be shorter than ttl")


DEFAULT_DOCKER_CONTAINER_LEASE_POLICY = DockerContainerLeasePolicy()


@dataclass(frozen=True, slots=True)
class ManagedDockerContainerLease:
    allocation_id: str
    holder_scope: ScopeIdentity
    image: str
    runtime_identity_digest: str
    authority_id: str
    owner_generation_id: str
    container_name: str
    lease: ResourceLease

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.image.strip():
            raise ValueError("managed Docker container identity is incomplete")
        for field_name, value in (
            ("runtime_identity_digest", self.runtime_identity_digest),
            ("authority_id", self.authority_id),
            ("owner_generation_id", self.owner_generation_id),
        ):
            if (
                len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"managed Docker {field_name} must be lowercase sha256"
                )
        if self.lease.resource != ResourceIdentity(
            ResourceKind.CONTAINER, self.allocation_id
        ):
            raise ValueError("managed Docker resource identity drifted")
        if self.lease.holder_scope != self.holder_scope:
            raise ValueError("managed Docker holder scope drifted")
        if self.lease.state is not LeaseState.ACTIVE:
            raise ValueError("managed Docker lease must be active")

    @property
    def labels(self) -> tuple[tuple[str, str], ...]:
        return (
            (MANAGED_CONTAINER_LABEL, MANAGED_CONTAINER_LABEL_VALUE),
            (LABEL_AUTHORITY, self.authority_id),
            (LABEL_OWNER_GENERATION, self.owner_generation_id),
            (LABEL_ALLOCATION, self.allocation_id),
            (LABEL_LEASE, self.lease.lease_id),
            (LABEL_FENCING, str(self.lease.fencing_token)),
            (LABEL_RUNTIME, self.runtime_identity_digest),
            (LABEL_HOLDER, self.holder_scope.key),
        )

    def docker_run_options(self) -> tuple[str, ...]:
        values: list[str] = [
            "--name",
            self.container_name,
            "--restart",
            "no",
            "--init",
            # Relative weights preserve full idle-host throughput while making
            # Noetrium yield CPU/block-I/O first when other users contend.
            "--cpu-shares",
            "128",
            "--blkio-weight",
            "100",
            # Under unrecoverable host memory pressure, prefer sacrificing our
            # disposable worker generation over unrelated user processes.
            "--oom-score-adj",
            "500",
        ]
        for key, value in self.labels:
            values.extend(("--label", f"{key}={value}"))
        return tuple(values)


@dataclass(frozen=True, slots=True)
class DockerContainerReconciliation:
    removed_container_ids: tuple[str, ...]
    released_lease_ids: tuple[str, ...] = ()


__all__ = [
    "DEFAULT_DOCKER_CONTAINER_LEASE_POLICY",
    "DockerContainerLeasePolicy",
    "DockerContainerObservation",
    "DockerContainerReconciliation",
    "LABEL_AUTHORITY",
    "LABEL_OWNER_GENERATION",
    "LABEL_ALLOCATION",
    "LABEL_FENCING",
    "LABEL_HOLDER",
    "LABEL_LEASE",
    "LABEL_RUNTIME",
    "MANAGED_CONTAINER_LABEL",
    "MANAGED_CONTAINER_LABEL_VALUE",
    "ManagedDockerContainerLease",
]
