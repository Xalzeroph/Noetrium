from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.model.stack.api import (
    DEFAULT_MODEL_SCHEDULER_POLICY,
    ModelArtifactClosure,
    ModelServingPolicy,
    FrozenModelStack,
    RuntimeBuildIdentity,
    model_stack_launch_settings,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _stack(*, engine: str = "vllm", engine_args: tuple[str, ...] = ()) -> FrozenModelStack:
    return FrozenModelStack(
        ImmutableModelIdentity(
            "qwen",
            "qwen3-8b",
            "revision",
            engine,
            "0.8.5" if engine == "vllm" else "test",
            "bfloat16",
            None,
            32768,
        ),
        ModelArtifactClosure("weights", "tokenizer", "config"),
        RuntimeBuildIdentity(
            "container",
            "engine",
            "lock",
            "cuda",
            "nccl",
            "torch",
            "kernels",
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
        engine_args,
    )


def test_model_stack_platform_default_is_priority_and_renders_physically() -> None:
    base = _stack()
    stack = FrozenModelStack(
        identity=base.identity,
        artifacts=base.artifacts,
        runtime=base.runtime,
        tensor_parallel=base.tensor_parallel,
        data_parallel=base.data_parallel,
        expert_parallel=base.expert_parallel,
        pipeline_parallel=base.pipeline_parallel,
        reasoning_parser=base.reasoning_parser,
        tool_call_parser=base.tool_call_parser,
        kv_cache_dtype=base.kv_cache_dtype,
        attention_backend=base.attention_backend,
    )

    assert DEFAULT_MODEL_SCHEDULER_POLICY == "priority"
    assert stack.scheduler_policy == "priority"
    settings = model_stack_launch_settings(stack)
    assert ("VLLM_USE_V1", "0") in settings.environment
    assert (
        "--scheduling-policy",
        "priority",
    ) == settings.engine_args[settings.engine_args.index("--scheduling-policy"):][:2]


def test_vllm_typed_stack_fields_render_to_exact_process_settings() -> None:
    stack = replace(
        _stack(engine_args=("--max-num-seqs", "64")),
        reasoning_parser="qwen3",
        tool_call_parser="hermes",
        kv_cache_dtype="fp8",
        attention_backend="FLASH_ATTN",
        scheduler_policy="priority",
        serving_policy=ModelServingPolicy(
            runtime_tuning_revision="test-v1",
            prefix_caching=True,
            prefix_cache_hash_algorithm="sha256",
            chunked_prefill=True,
            max_batch_tokens=4096,
            kv_cache_memory_bytes=2 * 1024**3,
        ),
    )

    settings = model_stack_launch_settings(stack)

    assert settings.environment == (
        ("NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES", str(2 * 1024**3)),
        ("VLLM_ATTENTION_BACKEND", "FLASH_ATTN"),
        ("VLLM_USE_V1", "0"),
    )
    assert settings.engine_args == (
        "--max-model-len",
        "32768",
        "--dtype",
        "bfloat16",
        "--enable-reasoning",
        "--reasoning-parser",
        "qwen3",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "hermes",
        "--kv-cache-dtype",
        "fp8",
        "--scheduling-policy",
        "priority",
        "--enable-prefix-caching",
        "--enable-prompt-tokens-details",
        "--prefix-caching-hash-algo",
        "sha256",
        "--enable-chunked-prefill",
        "--max-num-batched-tokens",
        "4096",
        "--max-num-seqs",
        "64",
    )




def test_vllm_fcfs_does_not_force_legacy_engine_mode() -> None:
    settings = model_stack_launch_settings(_stack())
    assert ("VLLM_USE_V1", "0") not in settings.environment

@pytest.mark.parametrize(
    "flag",
    (
        "--reasoning-parser",
        "--enable-reasoning",
        "--tool-call-parser",
        "--enable-auto-tool-choice",
        "--kv-cache-dtype",
        "--scheduling-policy",
    ),
)
def test_vllm_typed_launch_authority_rejects_engine_arg_duplicates(flag: str) -> None:
    stack = _stack(engine_args=(flag, "x"))
    with pytest.raises(ValueError, match="platform-owned"):
        model_stack_launch_settings(stack)


def test_sglang_typed_semantics_fail_closed_instead_of_being_ignored() -> None:
    stack = replace(_stack(engine="sglang"), kv_cache_dtype="fp8")
    with pytest.raises(ValueError, match="without a qualified physical renderer"):
        model_stack_launch_settings(stack)


@pytest.mark.parametrize(
    "flag",
    (
        "--enable-prefix-caching",
        "--no-enable-prefix-caching",
        "--enable-prompt-tokens-details",
        "--prefix-caching-hash-algo",
        "--enable-chunked-prefill",
        "--no-enable-chunked-prefill",
        "--max-num-batched-tokens",
        "--kv-cache-memory-bytes",
    ),
)
def test_vllm_serving_policy_owns_performance_flags(flag: str) -> None:
    stack = _stack(engine_args=(flag, "x"))
    with pytest.raises(ValueError, match="platform-owned"):
        model_stack_launch_settings(stack)


def test_model_serving_policy_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires prefix_caching"):
        ModelServingPolicy(runtime_tuning_revision="test-v1", prefix_cache_hash_algorithm="sha256")
    with pytest.raises(ValueError, match="max_batch_tokens"):
        ModelServingPolicy(runtime_tuning_revision="test-v1", max_batch_tokens=0)
    with pytest.raises(ValueError, match="kv_cache_memory_bytes"):
        ModelServingPolicy(
            runtime_tuning_revision="test-v1",
            kv_cache_memory_bytes=0,
        )
