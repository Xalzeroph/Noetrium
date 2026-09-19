from __future__ import annotations

from uuid import uuid4

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeLeaseGuardFactoryPort,
    ComputeLeasePolicy,
    ComputeSchedulerPort,
    DEFAULT_COMPUTE_LEASE_POLICY,
)
from noetrium_platform.infrastructure.resources.compute.runtime import ComputeLeaseHeartbeatFactory
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    TaskFailurePolicy,
    TaskGroupPort,
)
from noetrium_platform.research.execution.admission.api import AdmissionBudget, AdmissionMode
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority

from .concurrency import build_execution_concurrency_runtime


class ResearchExecutionPool:
    """Shared execution authorities for nested concurrent research workloads.

    The dependency order is explicit:

        orchestration -> experiment execution -> model I/O

    A synchronous parent may wait only on work in a downstream domain. Keeping
    the three admission/concurrency domains independent prevents nested-admission
    deadlock while preserving one composition owner and bounded resources.
    Exact model-serving capacity is shared separately through one admission
    registry per deployment generation.
    """

    def __init__(
        self,
        *,
        orchestration_concurrency_budget: ConcurrencyBudget | None = None,
        orchestration_admission_budget: AdmissionBudget | None = None,
        experiment_concurrency_budget: ConcurrencyBudget | None = None,
        experiment_admission_budget: AdmissionBudget | None = None,
        model_io_concurrency_budget: ConcurrencyBudget | None = None,
        model_io_admission_budget: AdmissionBudget | None = None,
        priority_aging_seconds: float = 1.0,
    ) -> None:
        self._orchestration = build_execution_concurrency_runtime(
            concurrency_budget=orchestration_concurrency_budget,
            admission_budget=orchestration_admission_budget,
            priority_aging_seconds=priority_aging_seconds,
            blocking_io_thread_name_prefix="research-orchestration-io",
            timer_name="research-orchestration-timer",
        )
        try:
            self._experiments = build_execution_concurrency_runtime(
                concurrency_budget=experiment_concurrency_budget,
                admission_budget=experiment_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                blocking_io_thread_name_prefix="research-experiment-io",
                timer_name="research-experiment-timer",
            )
            try:
                self._model_io = build_execution_concurrency_runtime(
                    concurrency_budget=model_io_concurrency_budget,
                    admission_budget=model_io_admission_budget,
                    priority_aging_seconds=priority_aging_seconds,
                    blocking_io_thread_name_prefix="research-model-io",
                    timer_name="research-model-timer",
                )
                self._model_admission: ModelAdmissionRegistryPort = ModelAdmissionRegistry()
            except BaseException:
                self._experiments.close()
                raise
        except BaseException:
            self._orchestration.close()
            raise
        self._compute_lease_group: TaskGroupPort | None = None
        self._closed = False

    @property
    def model_admission(self) -> ModelAdmissionRegistryPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        return self._model_admission

    def open_orchestration_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        return self._orchestration.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_experiment_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        return self._experiments.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def compute_lease_guard_factory(
        self,
        scheduler: ComputeSchedulerPort,
        *,
        policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
        lane_capacity: int | None = 1,
    ) -> ComputeLeaseGuardFactoryPort:
        """Share one structured heartbeat authority across all compute leases."""

        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._compute_lease_group is None:
            self._compute_lease_group = self._experiments.open_task_group(
                f"research-compute-leases:{uuid4().hex}",
                resource_id="compute-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                admission_mode=AdmissionMode.BLOCK,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return ComputeLeaseHeartbeatFactory(
            scheduler=scheduler,
            task_group=self._compute_lease_group,
            heartbeat_scheduler=self._experiments.heartbeats,
            lane_id="research-compute-lease-renewal",
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def open_model_io_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_mode: AdmissionMode = AdmissionMode.BLOCK,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        return self._model_io.open_task_group(
            group_id,
            tenant_id=tenant_id,
            priority=priority,
            admission_mode=admission_mode,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def close_orchestration_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._orchestration.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_experiment_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._experiments.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_model_io_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._model_io.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def orchestration_admission_snapshot(self):
        return self._orchestration.admission_snapshot()

    def experiment_admission_snapshot(self):
        return self._experiments.admission_snapshot()

    def model_io_admission_snapshot(self):
        return self._model_io.admission_snapshot()

    def close(self, *, deadline: Deadline | None = None) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        # Close in dependency order: parent orchestration may synchronously wait
        # on studies, and studies may synchronously wait on model I/O.
        for runtime in (self._orchestration, self._experiments, self._model_io):
            try:
                runtime.close(deadline=deadline)
            except BaseException as exc:
                errors.append(exc)
        try:
            self._model_admission.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("research execution pool close failed", errors)

    def __enter__(self) -> "ResearchExecutionPool":
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["ResearchExecutionPool"]
