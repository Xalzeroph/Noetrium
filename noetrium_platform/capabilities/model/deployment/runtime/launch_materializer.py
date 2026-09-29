from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.model.asset.api import ModelAssetManagementPort
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.capabilities.model.stack.api import (
    MAX_VLLM_GPU_MEMORY_UTILIZATION,
    vllm_gpu_memory_utilization_for_target_bytes,
)
from noetrium_platform.infrastructure.resources.compute.api import GpuRuntimeObserverPort
from noetrium_platform.substrate.api import ServiceLaunchContract

_GIB = 1024**3
# Model-service readiness is a safety deadline, not a throughput target.
# Cold starts on shared hosts can spend substantial time in weight I/O,
# compilation, KV-cache construction and CUDA-graph capture after the bytes
# have already been admitted. Keep a model-size-scaled margin large enough
# that a healthy service is not torn down just as it becomes ready.
_MODEL_ENGINE_COLD_START_BASE_SECONDS = 300.0
_MODEL_ENGINE_COLD_START_SECONDS_PER_GIB = 30.0
_MODEL_ENGINE_COLD_START_MAX_SECONDS = 3600.0

def _model_readiness_timeout_s(*, configured_timeout_s: float, artifact_bytes: int, engine: str) -> float:
    if artifact_bytes < 0:
        raise ValueError("model artifact bytes must be non-negative")
    if engine not in {"vllm", "sglang"}:
        return float(configured_timeout_s)
    gib = max(1, (int(artifact_bytes) + _GIB - 1) // _GIB)
    derived = _MODEL_ENGINE_COLD_START_BASE_SECONDS + _MODEL_ENGINE_COLD_START_SECONDS_PER_GIB * gib
    return max(float(configured_timeout_s), min(_MODEL_ENGINE_COLD_START_MAX_SECONDS, derived))

@dataclass(frozen=True, slots=True)
class _StaticLaunchInputs:
    readiness_timeout_s: float
    environment_items: tuple[tuple[str, str], ...]
    environment_digest: str
    artifact_digest: str
    runtime_identity_digest: str
    executable: str
    argv: tuple[str, ...]
    cwd: str

class ModelLaunchMaterializer:
    """Materialize one exact model-service launch from desired intent."""

    def __init__(
        self,
        assets: ModelAssetManagementPort,
        *,
        gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
        base_environment: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._assets = assets
        self._gpu_runtime_observer = gpu_runtime_observer
        self._base_environment = tuple(base_environment)

    def _resolve_static_launch_inputs(self, spec: ModelDeploymentSpec) -> _StaticLaunchInputs:
        asset = self._assets.model(spec.model_id)
        stats = self._assets.model_stats(spec.model_id)
        environment = dict(self._base_environment)
        environment.update(spec.environment)
        executable = spec.executable
        replacements = {
            "{model_path}": str(asset.path),
            "{model_id}": asset.model_id,
            "{deployment_id}": spec.deployment_id,
        }
        argv = [self._replace_tokens(item, replacements) for item in spec.argv]
        if not argv or argv[0] != executable:
            argv = [executable, *argv]
        environment_items = tuple(sorted((str(k), str(v)) for k, v in environment.items()))
        return _StaticLaunchInputs(
            readiness_timeout_s=_model_readiness_timeout_s(
                configured_timeout_s=spec.readiness_timeout_s,
                artifact_bytes=stats.bytes,
                engine=spec.engine,
            ),
            environment_items=environment_items,
            environment_digest=canonical_digest(environment_items),
            artifact_digest=canonical_digest({
                "model_id": asset.model_id,
                "path": asset.path,
                "mode": asset.mode,
                "storage_pool": asset.storage_pool,
            }),
            runtime_identity_digest=canonical_digest({
                "engine": spec.engine,
                "container_digest": spec.container_digest,
                "gpu_devices": spec.gpu_devices,
                "executable": executable,
            }),
            executable=executable,
            argv=tuple(argv),
            cwd=str(spec.cwd.expanduser().resolve()),
        )

    def validate_materialization_inputs(self, spec: ModelDeploymentSpec) -> None:
        self._resolve_static_launch_inputs(spec)

    def matches_applied(self, spec: ModelDeploymentSpec, contract: ServiceLaunchContract) -> bool:
        resolved = self._resolve_static_launch_inputs(spec)
        desired_argv = resolved.argv
        applied_argv = contract.argv
        if spec.engine == "vllm" and spec.gpu_devices:
            desired_argv = tuple(self._without_vllm_gpu_memory_target(desired_argv))
            applied_argv = tuple(self._without_vllm_gpu_memory_target(applied_argv))
        return (
            contract.service_id == spec.service_id
            and contract.executable == resolved.executable
            and applied_argv == desired_argv
            and contract.cwd == resolved.cwd
            and contract.environment_digest == resolved.environment_digest
            and contract.artifact_digest == resolved.artifact_digest
            and contract.runtime_identity_digest == resolved.runtime_identity_digest
            and contract.readiness_timeout_s == resolved.readiness_timeout_s
            and contract.stop_timeout_s == spec.stop_timeout_s
            and contract.heartbeat_interval_s == spec.heartbeat_interval_s
        )

    def materialize(self, spec: ModelDeploymentSpec) -> tuple[ServiceLaunchContract, tuple[tuple[str, str], ...]]:
        resolved = self._resolve_static_launch_inputs(spec)
        argv = list(resolved.argv)
        if spec.engine == "vllm" and spec.gpu_devices:
            argv = self._materialize_vllm_gpu_memory_target(spec, argv)
        generation = canonical_digest({
            "deployment_id": spec.deployment_id,
            "service_id": spec.service_id,
            "engine": spec.engine,
            "executable": resolved.executable,
            "argv": tuple(argv),
            "cwd": resolved.cwd,
            "environment_digest": resolved.environment_digest,
            "artifact_digest": resolved.artifact_digest,
            "runtime_identity_digest": resolved.runtime_identity_digest,
            "readiness_url": spec.readiness_url,
        })[:24]
        return (
            ServiceLaunchContract(
                service_id=spec.service_id,
                generation=generation,
                executable=resolved.executable,
                argv=tuple(argv),
                cwd=resolved.cwd,
                environment_digest=resolved.environment_digest,
                artifact_digest=resolved.artifact_digest,
                runtime_identity_digest=resolved.runtime_identity_digest,
                readiness_timeout_s=resolved.readiness_timeout_s,
                stop_timeout_s=spec.stop_timeout_s,
                heartbeat_interval_s=spec.heartbeat_interval_s,
            ),
            resolved.environment_items,
        )

    def _materialize_vllm_gpu_memory_target(self, spec: ModelDeploymentSpec, argv: list[str]) -> list[str]:
        reservations = spec.gpu_memory_reservation_bytes
        if len(reservations) != len(spec.gpu_devices) or any(value <= 0 for value in reservations):
            raise RuntimeError("vLLM shared launch requires exact positive per-device VRAM reservations")
        observer = self._gpu_runtime_observer
        if observer is None:
            raise RuntimeError("vLLM shared launch requires GPU runtime observation")
        snapshot = observer.snapshot()
        if not snapshot.available:
            raise RuntimeError("vLLM shared launch GPU runtime is unavailable: " + (snapshot.detail or "unknown"))
        by_uuid = {row.uuid: row for row in snapshot.devices}
        fractions: list[float] = []
        for gpu_id, reservation in zip(spec.gpu_devices, reservations, strict=True):
            device = by_uuid.get(gpu_id)
            if device is None:
                raise RuntimeError("vLLM shared launch cannot observe allocated GPU: " + gpu_id)
            total_bytes = device.memory_total_mb * 1024 * 1024
            occupied_bytes = device.memory_used_mb * 1024 * 1024
            # vLLM 0.8.x derives available KV bytes as
            # total*utilization - peak_memory, and its peak-memory accounting
            # includes allocations from other processes on the same GPU as
            # non-Torch memory. Encode the global target observed at launch so
            # the process receives exactly its scheduler-owned reservation.
            # The resulting launch contract is frozen; later status/reconcile
            # must compare against that applied contract rather than
            # re-materializing this occupancy-sensitive target.
            fraction = vllm_gpu_memory_utilization_for_target_bytes(
                occupied_bytes + reservation,
                total_bytes,
            )
            if fraction is None:
                raise RuntimeError(
                    "vLLM shared launch exceeds global GPU memory ceiling: "
                    f"gpu={gpu_id} occupied_bytes={occupied_bytes} "
                    f"reservation_bytes={reservation} total_bytes={total_bytes} "
                    f"max_fraction={MAX_VLLM_GPU_MEMORY_UTILIZATION}"
                )
            fractions.append(fraction)
        return self._with_vllm_gpu_memory_target(argv, max(fractions))

    @staticmethod
    def _without_vllm_gpu_memory_target(argv: tuple[str, ...] | list[str]) -> list[str]:
        names = {"--gpu-memory-utilization", "--device-memory-utilization"}
        values = list(argv)
        rewritten: list[str] = []
        index = 0
        while index < len(values):
            token = values[index]
            if token in names:
                if index + 1 >= len(values):
                    raise ValueError("vLLM gpu-memory-utilization argument requires a value")
                index += 2
                continue
            if any(token.startswith(name + "=") for name in names):
                index += 1
                continue
            rewritten.append(token)
            index += 1
        return rewritten

    @classmethod
    def _with_vllm_gpu_memory_target(cls, argv: tuple[str, ...] | list[str], utilization: float) -> list[str]:
        value = f"{float(utilization):.6f}".rstrip("0").rstrip(".")
        rewritten = cls._without_vllm_gpu_memory_target(argv)
        rewritten.extend(("--gpu-memory-utilization", value))
        return rewritten

    @staticmethod
    def _replace_tokens(value: str, replacements: dict[str, str]) -> str:
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value

__all__ = ["ModelLaunchMaterializer"]
