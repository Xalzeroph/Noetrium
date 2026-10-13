from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.deployment.api import ModelDesiredDeployment
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import NoetriumUnit


_SGLANG_EXECUTABLE = "/usr/bin/python3"
_SGLANG_ARGV_PREFIX = ("-m", "sglang.launch_server")
_VLLM_EXECUTABLE = "/usr/local/bin/vllm"
_VLLM_ARGV_PREFIX = ("serve", "{model_path}")
_VLLM_FIXED_ARGS = ("--disable-log-requests",)


def model_deployment_template_digest(engine: str) -> str:
    key = str(engine).strip().lower()
    if key == "vllm":
        payload = {
            "engine": key,
            "executable": _VLLM_EXECUTABLE,
            "argv_prefix": _VLLM_ARGV_PREFIX,
            "fixed_args": _VLLM_FIXED_ARGS,
            "served_model_flag": "--served-model-name",
            "host_flag": "--host",
            "port_flag": "--port",
            "tensor_parallel_flag": "--tensor-parallel-size",
            "data_parallel_flag": "--data-parallel-size",
            "pipeline_parallel_flag": "--pipeline-parallel-size",
            "data_parallel_rpc_port_flag": "--data-parallel-rpc-port",
        }
    elif key == "sglang":
        payload = {
            "engine": key,
            "executable": _SGLANG_EXECUTABLE,
            "argv_prefix": _SGLANG_ARGV_PREFIX,
            "model_path_flag": "--model-path",
            "host_flag": "--host",
            "port_flag": "--port",
            "tensor_parallel_flag": "--tp-size",
        }
    else:
        raise ValueError(f"unsupported model deployment template engine: {engine!r}")
    return canonical_digest({
        "schema": "noetrium.model-deployment-launch-template.v1",
        "template": payload,
    })


def sglang_deployment(
    *,
    deployment_id: str,
    scope: NoetriumUnit,
    model_id: str,
    container_digest: str,
    cwd: Path,
    port: int,
    host: str = "127.0.0.1",
    tensor_parallel: int = 1,
    gpu_devices: tuple[str, ...] = (),
    gpu_memory_reservation_bytes: tuple[int, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDesiredDeployment:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("SGLang deployment port must be Resource-assigned")
    return ModelDesiredDeployment(
        deployment_id=deployment_id,
        scope=scope,
        service_id=f"model:{deployment_id}",
        model_id=model_id,
        engine="sglang",
        container_digest=container_digest,
        executable=_SGLANG_EXECUTABLE,
        argv=(
            _SGLANG_EXECUTABLE,
            *_SGLANG_ARGV_PREFIX,
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
        gpu_devices=gpu_devices,
        gpu_memory_reservation_bytes=gpu_memory_reservation_bytes,
        readiness_url=f"http://{host}:{port}/health",
    )


def vllm_deployment(
    *,
    deployment_id: str,
    scope: NoetriumUnit,
    model_id: str,
    container_digest: str,
    cwd: Path,
    port: int,
    host: str = "127.0.0.1",
    tensor_parallel: int = 1,
    data_parallel: int = 1,
    pipeline_parallel: int = 1,
    data_parallel_rpc_port: int | None = None,
    gpu_devices: tuple[str, ...] = (),
    gpu_memory_reservation_bytes: tuple[int, ...] = (),
    extra_args: tuple[str, ...] = (),
) -> ModelDesiredDeployment:
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
        "--served-model-name",
        "--gpu-memory-utilization",
        "--device-memory-utilization",
        "--disable-log-requests",
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
    return ModelDesiredDeployment(
        deployment_id=deployment_id,
        scope=scope,
        service_id=f"model:{deployment_id}",
        model_id=model_id,
        engine="vllm",
        container_digest=container_digest,
        executable=_VLLM_EXECUTABLE,
        argv=(
            _VLLM_EXECUTABLE,
            *_VLLM_ARGV_PREFIX,
            "--served-model-name",
            model_id,
            "--host",
            host,
            "--port",
            str(port),
            *_VLLM_FIXED_ARGS,
            *parallel_args,
            *extra_args,
        ),
        cwd=cwd,
        gpu_devices=gpu_devices,
        gpu_memory_reservation_bytes=gpu_memory_reservation_bytes,
        readiness_url=f"http://{host}:{port}/health",
    )


__all__ = ["model_deployment_template_digest", "sglang_deployment", "vllm_deployment"]
