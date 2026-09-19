from __future__ import annotations

from threading import Lock

from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeLeaseGuardFactoryPort,
    ComputeLeaseGuardPort,
    ComputeRequirement,
    ComputeSchedulerPort,
)
from noetrium_platform.research.experimentation.experiment.api import ExperimentDefinition
from noetrium_platform.research.experimentation.resource.api import (
    ResourceAllocationLeasePort,
    ResourceAllocationReceipt,
    ResourcePolicy,
)


class ResourceAllocationLease(ResourceAllocationLeasePort):
    def __init__(
        self,
        receipt: ResourceAllocationReceipt,
        scheduler: ComputeSchedulerPort | None,
        guard: ComputeLeaseGuardPort | None = None,
    ) -> None:
        self._receipt = receipt
        self._scheduler = scheduler
        self._guard = guard
        self._released = False
        self._lock = Lock()

    @property
    def receipt(self) -> ResourceAllocationReceipt:
        return self._receipt

    def assert_healthy(self) -> None:
        if self._guard is not None:
            self._guard.assert_healthy()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        errors: list[BaseException] = []
        if self._guard is not None:
            try:
                self._guard.close()
            except BaseException as exc:
                errors.append(exc)
        if self._scheduler is not None and self._receipt.allocation_id is not None:
            try:
                self._scheduler.release(self._receipt.allocation_id)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("resource allocation lease release failed", errors)

    def __enter__(self) -> "ResourceAllocationLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.release()
        return False


class ExperimentResourceBinder:
    """Resolve one frozen experiment resource policy into an auditable placement."""

    def __init__(
        self,
        scheduler: ComputeSchedulerPort | None = None,
        lease_guard_factory: ComputeLeaseGuardFactoryPort | None = None,
    ) -> None:
        if scheduler is not None and lease_guard_factory is None:
            raise ValueError("compute resource binder requires a structured lease guard factory")
        if scheduler is None and lease_guard_factory is not None:
            raise ValueError("compute lease guard factory requires a compute scheduler")
        self._scheduler = scheduler
        self._lease_guard_factory = lease_guard_factory

    def bind(
        self,
        definition: ExperimentDefinition,
        policy: ResourcePolicy,
        *,
        allocation_id: str,
        owner_scope: ScopeIdentity,
        placement_scope: ScopeIdentity | None = None,
    ) -> ResourceAllocationLease:
        if not isinstance(definition, ExperimentDefinition):
            raise TypeError("resource binding requires ExperimentDefinition")
        if not isinstance(policy, ResourcePolicy):
            raise TypeError("resource binding requires ResourcePolicy")
        if definition.resource_policy_digest != policy.policy_digest:
            raise ValueError("experiment resource policy digest does not match frozen definition")
        if not isinstance(owner_scope, ScopeIdentity):
            raise TypeError("resource binding owner_scope must be ScopeIdentity")
        if placement_scope is not None and not isinstance(placement_scope, ScopeIdentity):
            raise TypeError("resource binding placement_scope must be ScopeIdentity or None")
        if type(allocation_id) is not str or not allocation_id.strip():
            raise ValueError("resource binding allocation_id must be non-empty")
        if policy.compute is None:
            return ResourceAllocationLease(
                ResourceAllocationReceipt(policy.policy_digest, owner_scope, placement_scope),
                None,
            )
        if self._scheduler is None:
            raise RuntimeError("compute resource policy requires a compute scheduler")
        demand = policy.compute
        assert self._lease_guard_factory is not None
        lease_policy = self._lease_guard_factory.policy
        allocation = self._scheduler.allocate(
            allocation_id,
            owner_scope,
            ComputeRequirement(
                cpu_cores=demand.cpu_cores,
                memory_bytes=demand.memory_bytes,
                gpu_count=demand.gpu_count,
                minimum_gpu_memory_bytes=demand.minimum_gpu_memory_bytes,
                required_gpu_free_memory_bytes=(
                    demand.gpu_memory_reservation_bytes_per_device
                    + demand.gpu_memory_headroom_bytes
                ),
                max_gpu_utilization_percent=demand.max_gpu_utilization_percent,
                gpu_sharing_mode=demand.gpu_sharing_mode,
                cpu_headroom_cores=demand.cpu_headroom_cores,
                memory_headroom_bytes=demand.memory_headroom_bytes,
                max_cpu_load_ratio=demand.max_cpu_load_ratio,
                require_host_runtime=demand.require_host_runtime,
                required_labels=demand.required_labels,
            ),
            placement_scope=placement_scope,
            ttl_seconds=lease_policy.ttl_seconds,
        )
        guard: ComputeLeaseGuardPort | None = None
        try:
            # Exact-id retries may reuse a lease close to expiry. Refresh it
            # before the first delayed heartbeat so ownership has a full TTL.
            allocation = self._scheduler.renew_many(
                (allocation.allocation_id,),
                ttl_seconds=lease_policy.ttl_seconds,
            )[0]
            guard = self._lease_guard_factory.create((allocation.allocation_id,))
            guard.start()
        except BaseException:
            self._scheduler.release(allocation.allocation_id)
            raise
        receipt = ResourceAllocationReceipt(
            policy_digest=policy.policy_digest,
            owner_scope=owner_scope,
            placement_scope=placement_scope,
            allocation_id=allocation.allocation_id,
            host_id=allocation.host_id,
            cpu_cores=allocation.cpu_cores,
            memory_bytes=allocation.memory_bytes,
            gpu_ids=allocation.gpu_ids,
            lease_fencing_token=allocation.lease_fencing_token,
            lease_expires_at_epoch_s=allocation.lease_expires_at_epoch_s,
        )
        return ResourceAllocationLease(receipt, self._scheduler, guard)


__all__ = ["ExperimentResourceBinder", "ResourceAllocationLease"]
