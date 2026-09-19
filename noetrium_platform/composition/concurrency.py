from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.execution.admission.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
    AdmissionTopologySnapshot,
    ExecutionAdmissionPort,
)
from noetrium_platform.research.execution.admission.composition import build_execution_admission
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.research.execution.scheduling.composition import build_admission_scheduling_policy
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ConcurrencyTopologySnapshot,
    Deadline,
    HeartbeatSchedulerPort,
    TaskFailurePolicy,
    TaskGroupPort,
    StructuredConcurrencyRuntimePort,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime


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


def build_execution_concurrency_runtime(
    *,
    concurrency_budget: ConcurrencyBudget | None = None,
    admission_budget: AdmissionBudget | None = None,
    priority_aging_seconds: float = 1.0,
    blocking_io_thread_name_prefix: str = "platform-blocking-io",
    timer_name: str = "platform-timer",
) -> ExecutionConcurrencyAuthorities:
    resolved_concurrency = concurrency_budget or ConcurrencyBudget()
    resolved_admission = admission_budget or _default_admission_budget(resolved_concurrency)
    scheduling = build_admission_scheduling_policy(
        priority_aging_seconds=priority_aging_seconds,
    )
    admission = build_execution_admission(
        budget=resolved_admission,
        scheduling=scheduling,
    )
    concurrency = build_concurrency_runtime(
        budget=resolved_concurrency,
        blocking_io_thread_name_prefix=blocking_io_thread_name_prefix,
        timer_name=timer_name,
        permits=admission,
    )
    return ExecutionConcurrencyAuthorities(concurrency=concurrency, admission=admission)


__all__ = ["ExecutionConcurrencyAuthorities", "build_execution_concurrency_runtime"]
