from __future__ import annotations

from dataclasses import dataclass
import math
from time import time
from typing import Protocol

from noetrium_platform.composition.environment_instance_leases import (
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceReconciliation,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
    EndpointAllocationPort,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation,
    ComputeSchedulerPort,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DockerContainerReconciliation,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)


class ResourceReconcileStopPort(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class ManagedResourceReconciliation:
    observed_at_epoch_s: float
    containers: DockerContainerReconciliation
    environments: EnvironmentInstanceReconciliation
    endpoints: tuple[EndpointAllocation, ...]
    compute: tuple[ComputeAllocation, ...]

    @property
    def changed(self) -> bool:
        return bool(
            self.containers.removed_container_ids
            or self.containers.released_lease_ids
            or self.environments.dirtied_instance_ids
            or self.environments.released_orphan_lease_ids
            or self.endpoints
            or self.compute
        )


class ManagedResourceReconciler:
    """One fail-closed recovery loop for all ephemeral research resources.

    Ordering is deliberate:
      1. physical Docker state is reconciled first;
      2. reusable Environment generations are invalidated next;
      3. network endpoints are released;
      4. compute/GPU allocations are released last.

    Durable recovery carriers such as workspaces, checkpoints, artifacts and
    datasets are intentionally excluded. They are retained across crashes and
    require explicit terminal retention/GC policy rather than lease expiry.
    """

    def __init__(
        self,
        *,
        containers: DockerContainerLeaseAuthority,
        environments: EnvironmentInstanceLeaseAuthority,
        endpoints: EndpointAllocationPort,
        compute: ComputeSchedulerPort,
    ) -> None:
        self._containers = containers
        self._environments = environments
        self._endpoints = endpoints
        self._compute = compute

    def reconcile(
        self,
        *,
        now: float | None = None,
    ) -> ManagedResourceReconciliation:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s) or now_epoch_s <= 0:
            raise ValueError(
                "managed resource reconciliation time must be finite and positive"
            )

        lease_now = None if now is None else now_epoch_s
        containers = self._containers.reconcile(now=lease_now)
        environments = self._environments.reconcile(now=lease_now)
        endpoints = self._endpoints.reconcile(now=lease_now)
        compute = self._compute.reconcile_expired(now=lease_now)

        return ManagedResourceReconciliation(
            observed_at_epoch_s=now_epoch_s,
            containers=containers,
            environments=environments,
            endpoints=endpoints,
            compute=compute,
        )

    def shutdown_cleanup(
        self,
        *,
        now: float | None = None,
    ) -> ManagedResourceReconciliation:
        """Terminal cleanup for one exclusively owned, quiesced runtime.

        Cleanup is a dependency transaction, not best-effort fan-out:

          Docker physical processes -> Environment generations -> endpoints -> compute.

        A stage must prove convergence before the next ownership layer is
        released.  On failure, later layers remain fenced and a later call may
        retry from durable/provider truth.
        """

        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s) or now_epoch_s <= 0:
            raise ValueError(
                "managed resource shutdown time must be finite and positive"
            )

        lease_now = None if now is None else now_epoch_s

        try:
            containers = self._containers.shutdown_cleanup(now=lease_now)
        except BaseException as exc:
            raise ExceptionGroup(
                "managed resource shutdown failed during container cleanup",
                [exc],
            ) from exc

        try:
            environments = self._environments.shutdown_cleanup(now=lease_now)
        except BaseException as exc:
            raise ExceptionGroup(
                "managed resource shutdown failed during environment cleanup",
                [exc],
            ) from exc

        try:
            # Upper model/container owners have already converged. At this
            # recovery boundary current socket occupancy is not endpoint
            # ownership evidence: a foreign process may have re-bound the port
            # immediately after our exact binder stopped.
            released_endpoints: list[EndpointAllocation] = []
            for allocation in self._endpoints.active():
                released_endpoints.append(
                    self._endpoints.recover_release(
                        allocation,
                        now=lease_now,
                    )
                )
            if self._endpoints.active():
                raise RuntimeError(
                    "endpoint allocations survived owner shutdown cleanup"
                )
            endpoints = tuple(
                sorted(
                    released_endpoints,
                    key=lambda row: row.allocation_id,
                )
            )
        except BaseException as exc:
            raise ExceptionGroup(
                "managed resource shutdown failed during endpoint cleanup",
                [exc],
            ) from exc

        try:
            compute = self._compute.allocations()
            for allocation in compute:
                self._compute.recover_release(allocation)
            if self._compute.allocations():
                raise RuntimeError(
                    "compute allocations survived owner shutdown cleanup"
                )
        except BaseException as exc:
            raise ExceptionGroup(
                "managed resource shutdown failed during compute cleanup",
                [exc],
            ) from exc

        return ManagedResourceReconciliation(
            observed_at_epoch_s=now_epoch_s,
            containers=containers,
            environments=environments,
            endpoints=endpoints,
            compute=compute,
        )

    def recover_abandoned_owner_generation(
        self,
        *,
        now: float | None = None,
    ) -> ManagedResourceReconciliation:
        """Take over one abandoned exclusive runtime generation immediately.

        The interprocess runtime lock proves that no previous local controller
        generation is still authoritative.  Waiting for TTL would strand ports
        and GPUs after SIGKILL/SSH loss, so startup performs the same physical-
        first dependency transaction as terminal cleanup before admitting work.
        """

        return self.shutdown_cleanup(now=now)

    def run(
        self,
        *,
        interval_seconds: float,
        stop: ResourceReconcileStopPort,
        max_cycles: int | None = None,
    ) -> ManagedResourceReconciliation:
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(float(interval_seconds))
            or float(interval_seconds) <= 0
        ):
            raise ValueError(
                "managed resource reconciliation interval must be finite and positive"
            )
        if max_cycles is not None and (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or max_cycles <= 0
        ):
            raise ValueError("managed resource reconciliation max_cycles must be positive")

        cycles = 0
        latest: ManagedResourceReconciliation | None = None
        while True:
            latest = self.reconcile()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return latest
            if stop.wait(float(interval_seconds)):
                return latest


__all__ = [
    "ManagedResourceReconciliation",
    "ManagedResourceReconciler",
    "ResourceReconcileStopPort",
]
