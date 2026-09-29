from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec, ModelDesiredState
from noetrium_platform.composition.model_management import (
    _MODEL_SERVING_CACHE_ENVIRONMENT,
    _model_serving_cache_keys,
    _model_serving_environment,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE


def _spec(*, port: int, gpu_devices=("GPU-a", "GPU-b"), extra=()):
    return ModelDeploymentSpec(
        deployment_id=f"deployment-{port}",
        scope=PLATFORM_SCOPE,
        service_id=f"model:deployment-{port}",
        model_id="qwen3-8b",
        engine="vllm",
        container_digest="a" * 64,
        executable="/usr/local/bin/vllm",
        argv=(
            "/usr/local/bin/vllm", "serve", "{model_path}",
            "--host", "127.0.0.1", "--port", str(port),
            "--tensor-parallel-size", "2", *extra,
        ),
        cwd=Path("/project"),
        gpu_devices=gpu_devices,
        gpu_memory_reservation_bytes=tuple(1 for _ in gpu_devices),
        desired_state=ModelDesiredState.RUNNING,
    )


def test_model_compile_cache_ignores_dynamic_endpoint_but_topology_cache_tracks_gpus() -> None:
    first_compile, first_topology = _model_serving_cache_keys(_spec(port=40001))
    second_compile, second_topology = _model_serving_cache_keys(_spec(port=40002))
    assert first_compile == second_compile
    assert first_topology == second_topology

    other_compile, other_topology = _model_serving_cache_keys(
        _spec(port=40003, gpu_devices=("GPU-c", "GPU-d"))
    )
    assert other_compile == first_compile
    assert other_topology != first_topology


def test_model_compile_cache_invalidates_on_engine_semantics() -> None:
    first = _model_serving_cache_keys(_spec(port=40001))[0]
    changed = _model_serving_cache_keys(
        _spec(port=40002, extra=("--max-model-len", "8192"))
    )[0]
    assert changed != first


def test_model_serving_cache_environment_is_contract_owned() -> None:
    environment = dict(_model_serving_environment((("HF_HOME", "/models/cache"),)))
    assert environment["HF_HOME"] == "/models/cache"
    for key, value in _MODEL_SERVING_CACHE_ENVIRONMENT:
        assert environment[key] == value

    with pytest.raises(ValueError, match="platform-owned"):
        _model_serving_environment((("VLLM_CACHE_ROOT", "/tmp/ad-hoc"),))
