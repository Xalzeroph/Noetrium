from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.substrate.api import ScopeIdentity


def sglang_deployment(
    *,
    deployment_id: str,
    scope: ScopeIdentity,
    model_id: str,
    python_environment_id: str,
    cwd: Path,
    port: int,
    host: str = "127.0.0.1",
    tensor_parallel: int = 1,
    gpu_devices: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDeploymentSpec:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("SGLang deployment port must be Resource-assigned")
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
    port: int,
    host: str = "127.0.0.1",
    tensor_parallel: int = 1,
    data_parallel: int = 1,
    pipeline_parallel: int = 1,
    data_parallel_rpc_port: int | None = None,
    gpu_devices: tuple[str, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDeploymentSpec:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("vLLM deployment port must be Resource-assigned")
    for name, value in (
        ("tensor_parallel", tensor_parallel),
        ("data_parallel", data_parallel),
        ("pipeline_parallel", pipeline_parallel),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"vLLM {name} must be a positive integer")
    required_devices = tensor_parallel * data_parallel * pipeline_parallel
    if len(gpu_devices) != required_devices:
        raise ValueError(
            "vLLM requires exact platform-owned gpu_devices matching "
            "tensor_parallel * data_parallel * pipeline_parallel"
        )
    if data_parallel == 1:
        if data_parallel_rpc_port is not None:
            raise ValueError("vLLM data_parallel_rpc_port requires data_parallel > 1")
    else:
        if (
            type(data_parallel_rpc_port) is not int
            or not 1 <= data_parallel_rpc_port <= 65535
            or data_parallel_rpc_port == port
        ):
            raise ValueError(
                "vLLM data parallel requires a distinct Resource-assigned RPC port"
            )
    reserved_flags = (
        "--model",
        "--host",
        "--port",
        "--tensor-parallel-size",
        "-tp",
        "--data-parallel-size",
        "-dp",
        "--pipeline-parallel-size",
        "-pp",
        "--data-parallel-rpc-port",
        "-dpp",
        "--device-ids",
    )
    for argument in extra_args:
        if any(
            argument == flag or argument.startswith(flag + "=")
            for flag in reserved_flags
        ):
            raise ValueError(
                f"vLLM topology/endpoint argument is platform-owned: {argument}"
            )
    parallel_args = (
        "--tensor-parallel-size",
        str(tensor_parallel),
        *(
            ("--data-parallel-size", str(data_parallel))
            if data_parallel != 1
            else ()
        ),
        *(
            ("--pipeline-parallel-size", str(pipeline_parallel))
            if pipeline_parallel != 1
            else ()
        ),
        *(
            ("--data-parallel-rpc-port", str(data_parallel_rpc_port))
            if data_parallel_rpc_port is not None
            else ()
        ),
    )
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
            *parallel_args,
            *extra_args,
        ),
        cwd=cwd,
        python_environment_id=python_environment_id,
        gpu_devices=gpu_devices,
        readiness_url=f"http://{host}:{port}/health",
    )


__all__ = ["sglang_deployment", "vllm_deployment"]
