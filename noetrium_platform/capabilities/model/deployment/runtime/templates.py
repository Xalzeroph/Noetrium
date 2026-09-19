from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.foundation.scope.api import ScopeIdentity


def sglang_deployment(
    *,
    deployment_id: str,
    scope: ScopeIdentity,
    model_id: str,
    python_environment_id: str,
    cwd: Path,
    host: str = "127.0.0.1",
    port: int = 30000,
    tensor_parallel: int = 1,
    gpu_devices: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDeploymentSpec:
    return ModelDeploymentSpec(
        deployment_id=deployment_id,
        scope=scope,
        service_id=f"model:{deployment_id}",
        model_id=model_id,
        engine="sglang",
        executable="{python}",
        argv=(
            "{python}",
            "-m",
            "sglang.launch_server",
            "--model-path",
            "{model_path}",
            "--host",
            host,
            "--port",
            str(port),
            "--tp-size",
            str(tensor_parallel),
            *extra_args,
        ),
        cwd=cwd,
        python_environment_id=python_environment_id,
        gpu_devices=gpu_devices,
        readiness_url=f"http://{host}:{port}/health",
    )


def vllm_deployment(
    *,
    deployment_id: str,
    scope: ScopeIdentity,
    model_id: str,
    python_environment_id: str,
    cwd: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    tensor_parallel: int = 1,
    gpu_devices: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDeploymentSpec:
    return ModelDeploymentSpec(
        deployment_id=deployment_id,
        scope=scope,
        service_id=f"model:{deployment_id}",
        model_id=model_id,
        engine="vllm",
        executable="{python}",
        argv=(
            "{python}",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            "{model_path}",
            "--host",
            host,
            "--port",
            str(port),
            "--tensor-parallel-size",
            str(tensor_parallel),
            *extra_args,
        ),
        cwd=cwd,
        python_environment_id=python_environment_id,
        gpu_devices=gpu_devices,
        readiness_url=f"http://{host}:{port}/health",
    )


__all__ = ["sglang_deployment", "vllm_deployment"]
