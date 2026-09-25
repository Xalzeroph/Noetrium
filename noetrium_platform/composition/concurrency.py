from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
    AdmissionTopologySnapshot,
    ExecutionAdmissionPort,
)
from noetrium_platform.research.execution.policy.composition import build_execution_admission
from noetrium_platform.research.execution.policy.api import ExecutionPriority
from noetrium_platform.research.execution.policy.composition import build_admission_scheduling_policy
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ConcurrencyTopologySnapshot,
    Deadline,
    HeartbeatSchedulerPort,
    TaskFailurePolicy,
    TaskGroupPort,
    StructuredConcurrencyRuntimePort,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime as _build_kernel_concurrency_runtime
from noetrium_platform.infrastructure.resources.compute.api import HostRuntimeObserverPort

from .shared_host_pressure import (
    SharedHostPressureAdmissionGate,
    SharedHostPressurePolicy,
    SharedStoragePressureObserverPort,
    configure_opportunistic_cpu_worker,
)


@dataclass(slots=True)
class ExecutionConcurrencyAuthorities:
    """Composition-only bundle over three independent system authorities.

    No policy lives here. Scheduling orders candidates, admission owns capacity
    decisions, and platform/concurrency owns only execution mechanisms/lifecycle.
    """

    concurrency: StructuredConcurrencyRuntimePort
    admission: ExecutionAdmissionPort

    @property
    def heartbeats(self) -> HeartbeatSchedulerPort:
        return self.concurrency.heartbeats

    def open_task_group(
        self,
        group_id: str,
        *,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
    ) -> TaskGroupPort:
        # Register policy identity before exposing the task group. If platform
        # ownership fails, this composition attempt fails closed and the process
        # scope is expected to be discarded rather than silently reusing IDs.
        self.admission.register_group(
            group_id,
            identity=AdmissionIdentity(tenant_id=tenant_id, resource_id=resource_id),
            intent=AdmissionIntent(priority=priority, mode=admission_mode),
        )
        return self.concurrency.open_task_group(
            group_id,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def close_task_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        group.close(cancel_pending=cancel_pending, deadline=deadline)
        self.concurrency.release_task_group(group.group_id)
        self.admission.unregister_group(group.group_id)

    def topology_snapshot(self) -> ConcurrencyTopologySnapshot:
        return self.concurrency.topology_snapshot()

    def admission_snapshot(self) -> AdmissionTopologySnapshot:
        return self.admission.snapshot()

    def close(self, *, deadline: Deadline | None = None) -> None:
        try:
            self.concurrency.close(deadline=deadline)
        finally:
            self.admission.close()

    def __enter__(self) -> "ExecutionConcurrencyAuthorities":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def _default_admission_budget(concurrency: ConcurrencyBudget) -> AdmissionBudget:
    total = 64
    return AdmissionBudget(
        max_total_in_flight=total,
        max_blocking_io_in_flight=min(total, int(concurrency.max_blocking_io_in_flight)),
        max_async_io_in_flight=min(total, int(concurrency.max_async_io_in_flight)),
        max_cpu_in_flight=min(total, int(concurrency.max_cpu_in_flight)),
        max_serial_in_flight=total,
    )


def build_structured_concurrency_runtime(
    *,
    budget: ConcurrencyBudget | None = None,
    blocking_io_thread_name_prefix: str = "platform-blocking-io",
    timer_name: str = "platform-timer",
    permits=None,
    cpu_worker_initializer=None,
) -> StructuredConcurrencyRuntimePort:
    """Application-composition boundary for the Kernel concurrency implementation."""

    kwargs = {
        "budget": budget or ConcurrencyBudget(),
        "blocking_io_thread_name_prefix": blocking_io_thread_name_prefix,
        "timer_name": timer_name,
    }
    if permits is not None:
        kwargs["permits"] = permits
    if cpu_worker_initializer is not None:
        kwargs["cpu_worker_initializer"] = cpu_worker_initializer
    return _build_kernel_concurrency_runtime(**kwargs)


def _validate_admission_provider_alignment(
    concurrency: ConcurrencyBudget,
    admission: AdmissionBudget,
) -> None:
    """Reject admission capacities that can overbook their physical provider."""

    limits = (
        (
            "blocking_io",
            int(admission.max_blocking_io_in_flight),
            int(concurrency.max_blocking_io_in_flight),
        ),
        (
            "async_io",
            int(admission.max_async_io_in_flight),
            int(concurrency.max_async_io_in_flight),
        ),
        (
            "cpu",
            int(admission.max_cpu_in_flight),
            int(concurrency.max_cpu_in_flight),
        ),
    )
    violations = tuple(
        (lane, admitted, provider)
        for lane, admitted, provider in limits
        if admitted > provider
    )
    if violations:
        detail = ", ".join(
            f"{lane}: admission={admitted} provider={provider}"
            for lane, admitted, provider in violations
        )
        raise ValueError(
            "execution admission cannot exceed provider in-flight capacity: "
            + detail
        )


def build_execution_concurrency_runtime(
    *,
    concurrency_budget: ConcurrencyBudget | None = None,
    admission_budget: AdmissionBudget | None = None,
    priority_aging_seconds: float = 1.0,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
    storage_pressure_observer: SharedStoragePressureObserverPort | None = None,
    shared_host_pressure_policy: SharedHostPressurePolicy | None = None,
    blocking_io_thread_name_prefix: str = "platform-blocking-io",
    timer_name: str = "platform-timer",
) -> ExecutionConcurrencyAuthorities:
    resolved_concurrency = concurrency_budget or ConcurrencyBudget()
    resolved_admission = admission_budget or _default_admission_budget(resolved_concurrency)
    _validate_admission_provider_alignment(
        resolved_concurrency,
        resolved_admission,
    )
    scheduling = build_admission_scheduling_policy(
        priority_aging_seconds=priority_aging_seconds,
    )
    base_admission = build_execution_admission(
        budget=resolved_admission,
        scheduling=scheduling,
    )
    if shared_host_pressure_policy is not None and host_runtime_observer is None:
        raise ValueError(
            "shared-host pressure policy requires a host runtime observer"
        )
    admission: ExecutionAdmissionPort = base_admission
    if host_runtime_observer is not None:
        admission = SharedHostPressureAdmissionGate(
            base_admission,
            host_runtime_observer,
            storage_observer=storage_pressure_observer,
            policy=shared_host_pressure_policy or SharedHostPressurePolicy(),
        )
    concurrency = build_structured_concurrency_runtime(
        budget=resolved_concurrency,
        blocking_io_thread_name_prefix=blocking_io_thread_name_prefix,
        timer_name=timer_name,
        permits=admission,
        cpu_worker_initializer=(
            configure_opportunistic_cpu_worker
            if host_runtime_observer is not None
            else None
        ),
    )
    return ExecutionConcurrencyAuthorities(concurrency=concurrency, admission=admission)


__all__ = [
    "ExecutionConcurrencyAuthorities",
    "build_execution_concurrency_runtime",
    "build_structured_concurrency_runtime",
]
