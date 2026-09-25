from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.capabilities.model.deployment.runtime.vllm_resources import (
    reconcile_vllm_compute_requirement,
)
from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    ModelStackSpec,
    RuntimeBuildIdentity,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeRequirement,
    GpuSharingMode,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stack(args: tuple[str, ...]) -> ModelStackSpec:
    return ModelStackSpec(
        ImmutableModelIdentity(
            "qwen",
            "qwen3-8b",
            "revision",
            "vllm",
            "test",
            "bfloat16",
            None,
            32768,
        ),
        ModelArtifactClosure(_h("weights"), _h("tokenizer"), _h("config")),
        RuntimeBuildIdentity(
            _h("container"),
            _h("engine"),
            _h("lock"),
            "cuda",
            "nccl",
            "torch",
            _h("kernels"),
        ),
        1,
        1,
        1,
        1,
        None,
        None,
        None,
        None,
        "fcfs",
        args,
    )


def test_vllm_resource_args_parse_aliases_and_human_capacity() -> None:
    intent = parse_vllm_engine_resource_args(
        (
            "--device-memory-utilization=0.875",
            "--cpu-offload-gb",
            "2.5",
            "--kv-offloading-size",
            "3",
            "--mm-processor-cache-gb=1.25",
            "-asc",
            "2",
            "--max-num-seqs",
            "1K",
            "--max-num-queued-reqs=2k",
        )
    )
    assert intent.gpu_memory_utilization == 0.875
    assert intent.cpu_offload_gb_per_gpu == 2.5
    assert intent.kv_offloading_size_gb == 3.0
    assert intent.mm_processor_cache_gb == 1.25
    assert intent.api_server_count == 2
    assert intent.max_num_seqs == 1024
    assert intent.max_num_queued_requests == 2000


def test_vllm_resource_args_reject_duplicate_memory_aliases() -> None:
    with pytest.raises(ValueError, match="duplicated"):
        parse_vllm_engine_resource_args(
            (
                "--gpu-memory-utilization",
                "0.8",
                "--device-memory-utilization",
                "0.9",
            )
        )


def test_vllm_stack_can_resolve_shared_gpu_memory_without_duplicate_compute_value() -> None:
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024**3,
        gpu_count=1,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    resolved = reconcile_vllm_compute_requirement(
        _stack(("--gpu-memory-utilization", "0.8")),
        requirement,
    )
    assert resolved.required_gpu_memory_fraction == 0.8


def test_vllm_explicit_host_memory_knobs_expand_compute_reservation() -> None:
    base = 2 * 1024**3
    resolved = reconcile_vllm_compute_requirement(
        _stack(
            (
                "--cpu-offload-gb",
                "2.5",
                "--kv-offloading-size",
                "3",
                "--mm-processor-cache-gb",
                "1.25",
                "--api-server-count",
                "2",
            )
        ),
        ComputeRequirement(
            cpu_cores=2,
            memory_bytes=base,
            gpu_count=1,
        ),
    )
    expected_extra = int((2.5 + 3.0 + 1.25 * 3) * 1024**3)
    assert resolved.memory_bytes == base + expected_extra


def test_vllm_explicit_kv_cache_bytes_do_not_reuse_ignored_gpu_fraction_for_shared_placement() -> None:
    requirement = ComputeRequirement(
        cpu_cores=2,
        memory_bytes=1024**3,
        gpu_count=1,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )
    with pytest.raises(ValueError, match="measured total VRAM demand"):
        reconcile_vllm_compute_requirement(
            _stack(
                (
                    "--gpu-memory-utilization",
                    "0.9",
                    "--kv-cache-memory-bytes",
                    "8G",
                )
            ),
            requirement,
        )


def test_vllm_explicit_kv_cache_bytes_accept_measured_total_vram_reservation() -> None:
    resolved = reconcile_vllm_compute_requirement(
        _stack(
            (
                "--gpu-memory-utilization",
                "0.9",
                "--kv-cache-memory-bytes",
                "8G",
            )
        ),
        ComputeRequirement(
            cpu_cores=2,
            memory_bytes=1024**3,
            gpu_count=1,
            required_gpu_free_memory_bytes=24 * 1024**3,
            gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
        ),
    )
    assert resolved.required_gpu_memory_fraction is None
    assert resolved.required_gpu_free_memory_bytes == 24 * 1024**3
