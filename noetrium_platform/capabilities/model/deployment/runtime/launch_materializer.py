from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.model.asset.api import ModelAssetManagementPort
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.substrate.api import ServiceLaunchContract


_GIB = 1024**3
_MODEL_ENGINE_COLD_START_BASE_SECONDS = 120.0
_MODEL_ENGINE_COLD_START_SECONDS_PER_GIB = 20.0
_MODEL_ENGINE_COLD_START_MAX_SECONDS = 1800.0


def _model_readiness_timeout_s(
    *,
    configured_timeout_s: float,
    artifact_bytes: int,
    engine: str,
) -> float:
    """Derive a finite cold-start budget from immutable model size.

    GPU model servers must not share one fixed readiness deadline: loading,
    compilation and warmup scale materially with checkpoint size. Explicit
    larger deployment budgets remain authoritative; the derived budget is
    bounded so a genuinely stuck service still fails closed.
    """

    if artifact_bytes < 0:
        raise ValueError("model artifact bytes must be non-negative")
    if engine not in {"vllm", "sglang"}:
        return float(configured_timeout_s)
    gib = max(1, (int(artifact_bytes) + _GIB - 1) // _GIB)
    derived = (
        _MODEL_ENGINE_COLD_START_BASE_SECONDS
        + _MODEL_ENGINE_COLD_START_SECONDS_PER_GIB * gib
    )
    return max(
        float(configured_timeout_s),
        min(_MODEL_ENGINE_COLD_START_MAX_SECONDS, derived),
    )


class ModelLaunchMaterializer:
    """Materializes mutable deployment intent into one exact service launch contract."""

    def __init__(
        self,
        assets: ModelAssetManagementPort,
        *,
        base_environment: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._assets = assets
        self._base_environment = tuple(base_environment)

    def materialize(self, spec: ModelDeploymentSpec) -> tuple[ServiceLaunchContract, tuple[tuple[str, str], ...]]:
        asset = self._assets.model(spec.model_id)
        stats = self._assets.model_stats(spec.model_id)
        readiness_timeout_s = _model_readiness_timeout_s(
            configured_timeout_s=spec.readiness_timeout_s,
            artifact_bytes=stats.bytes,
            engine=spec.engine,
        )
        environment = dict(self._base_environment)
        environment.update(spec.environment)
        executable = spec.executable
        argv = list(spec.argv)
        replacements = {
            "{model_path}": str(asset.path),
            "{model_id}": asset.model_id,
            "{deployment_id}": spec.deployment_id,
        }
        argv = [self._replace_tokens(item, replacements) for item in argv]
        if not argv or argv[0] != executable:
            argv = [executable, *argv]
        environment_items = tuple(sorted((str(k), str(v)) for k, v in environment.items()))
        environment_digest = canonical_digest(environment_items)
        artifact_digest = canonical_digest(
            {
                "model_id": asset.model_id,
                "path": asset.path,
                "mode": asset.mode,
                "storage_pool": asset.storage_pool,
            }
        )
        runtime_identity_digest = canonical_digest(
            {
                "engine": spec.engine,
                "container_digest": spec.container_digest,
                "gpu_devices": spec.gpu_devices,
                "executable": executable,
            }
        )
        cwd = str(spec.cwd.expanduser().resolve())
        generation = canonical_digest(
            {
                "deployment_id": spec.deployment_id,
                "service_id": spec.service_id,
                "engine": spec.engine,
                "executable": executable,
                "argv": tuple(argv),
                "cwd": cwd,
                "environment_digest": environment_digest,
                "artifact_digest": artifact_digest,
                "runtime_identity_digest": runtime_identity_digest,
                "readiness_url": spec.readiness_url,
            }
        )[:24]
        return (
            ServiceLaunchContract(
                service_id=spec.service_id,
                generation=generation,
                executable=executable,
                argv=tuple(argv),
                cwd=cwd,
                environment_digest=environment_digest,
                artifact_digest=artifact_digest,
                runtime_identity_digest=runtime_identity_digest,
                readiness_timeout_s=readiness_timeout_s,
                stop_timeout_s=spec.stop_timeout_s,
                heartbeat_interval_s=spec.heartbeat_interval_s,
            ),
            environment_items,
        )

    @staticmethod
    def _replace_tokens(value: str, replacements: dict[str, str]) -> str:
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value


__all__ = ["ModelLaunchMaterializer"]
