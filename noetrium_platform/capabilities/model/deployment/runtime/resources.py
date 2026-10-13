from __future__ import annotations

import heapq

from noetrium_platform.capabilities.model.asset.api import ModelAssetManagementPort
from noetrium_platform.substrate.api import GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot
from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelFleetRuntimePort,
    ModelDesiredDeployment,
    ModelDesiredState,
    ModelGpuAllocation,
    ModelGpuConflict,
    ModelGpuProcessBinding,
    ModelControlSnapshot,
)



class ModelResourceView:
    def __init__(
        self,
        assets: ModelAssetManagementPort,
        catalog: ModelDeploymentCatalogPort,
        fleet: ModelFleetRuntimePort,
        gpu_observer: GpuRuntimeObserverPort,
    ) -> None:
        self._assets = assets
        self._catalog = catalog
        self._fleet = fleet
        self._gpu_observer = gpu_observer

    def deployment_cut(
        self,
    ) -> tuple[
        tuple[ModelDesiredDeployment, ...],
        tuple,
    ]:
        """Return one control-plane cut without operational GPU telemetry.

        Warm selection needs immutable desired deployments plus live deployment
        status only. GPU telemetry belongs to the later placement cut and must
        not be sampled just to inspect model control state.
        """

        return self._catalog.deployments(), self._fleet.status_all()

    def gpu_allocations(self) -> tuple[ModelGpuAllocation, ...]:
        return tuple(
            ModelGpuAllocation(spec.deployment_id, spec.gpu_devices, spec.desired_state)
            for spec in self._catalog.deployments()
            if spec.gpu_devices
        )

    def gpu_conflicts(self) -> tuple[ModelGpuConflict, ...]:
        owners: dict[str, list[str]] = {}
        for spec in self._catalog.deployments():
            if spec.desired_state is not ModelDesiredState.RUNNING:
                continue
            for device in spec.gpu_devices:
                owners.setdefault(device, []).append(spec.deployment_id)
        return tuple(ModelGpuConflict(device, tuple(sorted(ids))) for device, ids in sorted(owners.items()) if len(ids) > 1)

    def gpu_runtime(self) -> GpuRuntimeSnapshot:
        return self._gpu_observer.snapshot()

    def gpu_candidates(
        self, *, count: int = 1, min_free_memory_mb: int = 0, max_utilization_percent: int = 100
    ):
        if count <= 0:
            raise ValueError("count must be positive")
        if min_free_memory_mb < 0:
            raise ValueError("min_free_memory_mb cannot be negative")
        if not 0 <= max_utilization_percent <= 100:
            raise ValueError("max_utilization_percent must be between 0 and 100")
        snapshot = self.gpu_runtime()
        if not snapshot.available:
            return ()
        candidates = (
            device
            for device in snapshot.devices
            if device.memory_free_mb >= min_free_memory_mb
            and device.utilization_percent <= max_utilization_percent
        )
        return tuple(
            heapq.nsmallest(
                count,
                candidates,
                key=lambda device: (
                    -device.memory_free_mb,
                    device.utilization_percent,
                    device.index,
                ),
            )
        )

    @staticmethod
    def _gpu_process_bindings_from_cut(
        deployments,
        observed: GpuRuntimeSnapshot,
    ) -> tuple[ModelGpuProcessBinding, ...]:
        statuses = {
            status.pid: status
            for status in deployments
            if status.pid is not None
        }
        grouped: dict[int, list[GpuProcessStatus]] = {}
        for process in observed.processes:
            grouped.setdefault(process.pid, []).append(process)
        values: list[ModelGpuProcessBinding] = []
        for pid, status in statuses.items():
            processes = grouped.get(pid, ())
            if not processes:
                continue
            values.append(
                ModelGpuProcessBinding(
                    deployment_id=status.deployment_id,
                    pid=pid,
                    gpu_uuids=tuple(sorted({process.gpu_uuid for process in processes})),
                    used_memory_mb=sum(process.used_memory_mb for process in processes),
                )
            )
        return tuple(sorted(values, key=lambda value: value.deployment_id))

    def gpu_process_bindings(self) -> tuple[ModelGpuProcessBinding, ...]:
        _specs, deployments = self.deployment_cut()
        observed = self.gpu_runtime()
        return self._gpu_process_bindings_from_cut(deployments, observed)

    def snapshot(self) -> ModelControlSnapshot:
        deployment_specs, deployments = self.deployment_cut()
        observed = self.gpu_runtime()
        return ModelControlSnapshot(
            models=self._assets.models(),
            deployment_specs=deployment_specs,
            deployments=deployments,
            gpu_process_bindings=self._gpu_process_bindings_from_cut(
                deployments, observed
            ),
            gpu_allocations=tuple(
                ModelGpuAllocation(spec.deployment_id, spec.gpu_devices, spec.desired_state)
                for spec in deployment_specs
                if spec.gpu_devices
            ),
            gpu_conflicts=self.gpu_conflicts(),
            gpu_runtime=observed,
        )


__all__ = ["ModelResourceView"]
