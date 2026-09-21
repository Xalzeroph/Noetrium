from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from threading import Event
from typing import Mapping

from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskHandlePort,
)
from noetrium_platform.research.execution.admission.api import AdmissionBudget
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout

from .model_management import (
    ManagementPlaneAuthorities,
    bind_local_model_replica_pool,
    build_local_management_plane,
)
from .research_execution_pool import ResearchExecutionPool


class _EventStop:
    def __init__(self, event: Event) -> None:
        self._event = event

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


@dataclass(slots=True)
class ManagedResearchRuntime:
    """Composition owner for one long-lived platform research process.

    This owns no scheduling/model/run semantics. It only binds already-existing
    authorities to one structured-concurrency lifetime so downstream code cannot
    accidentally bypass resource admission, model reconciliation, automatic
    model placement, lease renewal, or shutdown.
    """

    execution_pool: ResearchExecutionPool
    management: ManagementPlaneAuthorities
    _orchestration_group: object
    _stop: Event
    model_replica_pool: LocalModelReplicaPoolRuntime | None = None
    _model_controller: TaskHandlePort | None = None
    _closed: bool = False

    def start_background_controllers(
        self,
        *,
        model_reconcile_interval_seconds: float = 10.0,
    ) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        if isinstance(model_reconcile_interval_seconds, bool) or not isinstance(
            model_reconcile_interval_seconds, (int, float)
        ):
            raise TypeError("model reconcile interval must be a real number")
        interval = float(model_reconcile_interval_seconds)
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("model reconcile interval must be finite and positive")
        if self._model_controller is not None and not self._model_controller.done():
            return
        stop = _EventStop(self._stop)
        self._model_controller = self._orchestration_group.submit(
            ExecutionSpec(
                task_id="managed-model-desired-state-controller",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            self.management.models.controller.run,
            interval_seconds=interval,
            stop=stop,
        )

    def assert_healthy(self) -> None:
        if self._closed:
            raise RuntimeError("managed research runtime is closed")
        self._orchestration_group.assert_healthy()
        controller = self._model_controller
        if controller is not None and controller.done():
            controller.result()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        controller = self._model_controller
        errors: list[BaseException] = []
        if controller is not None:
            try:
                controller.result(timeout=30.0)
            except BaseException as exc:
                errors.append(exc)
        try:
            self.execution_pool.close_orchestration_group(
                self._orchestration_group,
                cancel_pending=True,
            )
        except BaseException as exc:
            errors.append(exc)
        try:
            self.execution_pool.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            first = errors[0]
            raise RuntimeError(
                f"managed research runtime close failed: "
                f"{type(first).__name__}: {first}"
            ) from first

    def __enter__(self) -> "ManagedResearchRuntime":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def build_local_managed_research_runtime(
    layout: DirectoryLayout,
    *,
    base_service_environment: tuple[tuple[str, str], ...] = (),
    model_source_environment: tuple[tuple[str, str], ...] = (),
    huggingface_cli: str = "hf",
    model_storage_pools: Mapping[str, Path] | None = None,
    orchestration_concurrency_budget: ConcurrencyBudget | None = None,
    orchestration_admission_budget: AdmissionBudget | None = None,
    experiment_concurrency_budget: ConcurrencyBudget | None = None,
    experiment_admission_budget: AdmissionBudget | None = None,
    model_io_concurrency_budget: ConcurrencyBudget | None = None,
    model_io_admission_budget: AdmissionBudget | None = None,
    start_background_controllers: bool = True,
    model_reconcile_interval_seconds: float = 10.0,
) -> ManagedResearchRuntime:
    pool = ResearchExecutionPool(
        orchestration_concurrency_budget=orchestration_concurrency_budget,
        orchestration_admission_budget=orchestration_admission_budget,
        experiment_concurrency_budget=experiment_concurrency_budget,
        experiment_admission_budget=experiment_admission_budget,
        model_io_concurrency_budget=model_io_concurrency_budget,
        model_io_admission_budget=model_io_admission_budget,
    )
    try:
        group = pool.open_orchestration_group(
            "managed-research-runtime",
            resource_id="platform-runtime-controller",
            priority=ExecutionPriority.CRITICAL,
        )
        try:
            management = build_local_management_plane(
                layout,
                base_service_environment=base_service_environment,
                model_source_environment=model_source_environment,
                huggingface_cli=huggingface_cli,
                model_storage_pools=model_storage_pools,
                task_group=group,
            )
            model_replica_pool = bind_local_model_replica_pool(management, pool)
        except BaseException:
            pool.close_orchestration_group(group, cancel_pending=True)
            raise
        runtime = ManagedResearchRuntime(
            execution_pool=pool,
            management=management,
            _orchestration_group=group,
            _stop=Event(),
            model_replica_pool=model_replica_pool,
        )
        if start_background_controllers:
            runtime.start_background_controllers(
                model_reconcile_interval_seconds=model_reconcile_interval_seconds,
            )
        return runtime
    except BaseException:
        pool.close()
        raise


__all__ = [
    "ManagedResearchRuntime",
    "build_local_managed_research_runtime",
]
