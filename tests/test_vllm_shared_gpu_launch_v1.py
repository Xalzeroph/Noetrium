from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.capabilities.model.deployment.runtime.launch_materializer import (
    ModelLaunchMaterializer,
    _model_readiness_timeout_s,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE


class _GpuObserver:
    def __init__(self, snapshot: GpuRuntimeSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> GpuRuntimeSnapshot:
        return self._snapshot


def _spec(
    reservations: tuple[int, ...],
) -> ModelDeploymentSpec:
    return ModelDeploymentSpec(
        deployment_id="deployment",
        scope=PLATFORM_SCOPE,
        service_id="model:deployment",
        model_id="Qwen3-8B",
        engine="vllm",
        container_digest="a" * 64,
        executable="/usr/local/bin/vllm",
        argv=(
            "/usr/local/bin/vllm",
            "serve",
            "{model_path}",
            "--gpu-memory-utilization",
            "0.1",
        ),
        cwd=Path("/tmp"),
        gpu_devices=("gpu-a", "gpu-b"),
        gpu_memory_reservation_bytes=reservations,
    )


def _snapshot(
    *,
    used_a_mb: int = 20_000,
    used_b_mb: int = 22_000,
) -> GpuRuntimeSnapshot:
    return GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus(
                "0", "gpu-a", "RTX 4090", 48_000, used_a_mb,
                48_000 - used_a_mb, 10,
            ),
            GpuDeviceStatus(
                "1", "gpu-b", "RTX 4090", 48_000, used_b_mb,
                48_000 - used_b_mb, 10,
            ),
        ),
    )


def test_vllm_launch_target_includes_external_occupancy_and_reservation() -> None:
    mib = 1024 * 1024
    materializer = ModelLaunchMaterializer(
        object(),
        gpu_runtime_observer=_GpuObserver(_snapshot()),
    )
    argv = materializer._materialize_vllm_gpu_memory_target(
        _spec((14_000 * mib, 12_000 * mib)),
        [
            "/usr/local/bin/vllm",
            "serve",
            "/model",
            "--gpu-memory-utilization",
            "0.1",
        ],
    )
    index = argv.index("--gpu-memory-utilization")
    fraction = float(argv[index + 1])
    assert fraction == pytest.approx(34_000 / 48_000, abs=1e-6)
    assert argv.count("--gpu-memory-utilization") == 1


def test_vllm_launch_fails_closed_above_global_memory_ceiling() -> None:
    mib = 1024 * 1024
    materializer = ModelLaunchMaterializer(
        object(),
        gpu_runtime_observer=_GpuObserver(
            _snapshot(used_a_mb=44_000, used_b_mb=44_000)
        ),
    )
    with pytest.raises(RuntimeError, match="global GPU memory ceiling"):
        materializer._materialize_vllm_gpu_memory_target(
            _spec((4_000 * mib, 4_000 * mib)),
            ["/usr/local/bin/vllm", "serve", "/model"],
        )


def test_vllm_cold_start_deadline_has_shared_host_safety_margin() -> None:
    gib = 1024**3
    timeout = _model_readiness_timeout_s(
        configured_timeout_s=120.0,
        artifact_bytes=16 * gib,
        engine="vllm",
    )
    assert timeout >= 780.0


def test_non_model_engine_preserves_configured_readiness_timeout() -> None:
    assert _model_readiness_timeout_s(
        configured_timeout_s=37.0,
        artifact_bytes=16 * 1024**3,
        engine="other",
    ) == 37.0
