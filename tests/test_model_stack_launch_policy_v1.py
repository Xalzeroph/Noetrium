from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    ModelServingPolicy,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from noetrium_platform.capabilities.model.stack.runtime import (
    model_stack_launch_settings,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity


def _stack(*, engine: str = "vllm", engine_args: tuple[str, ...] = ()) -> ModelStackSpec:
    return ModelStackSpec(
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


def test_vllm_typed_stack_fields_render_to_exact_process_settings() -> None:
    stack = replace(
        _stack(engine_args=("--max-num-seqs", "64")),
        reasoning_parser="qwen3",
        tool_call_parser="hermes",
        kv_cache_dtype="fp8",
        attention_backend="FLASH_ATTN",
        scheduler_policy="priority",
        serving_policy=ModelServingPolicy(
            prefix_caching=True,
            prefix_cache_hash_algorithm="sha256",
            chunked_prefill=True,
            max_batch_tokens=4096,
        ),
    )

    settings = model_stack_launch_settings(stack)

    assert settings.environment == (("VLLM_ATTENTION_BACKEND", "FLASH_ATTN"),)
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
        "--prefix-caching-hash-algo",
        "sha256",
        "--enable-chunked-prefill",
        "--max-num-batched-tokens",
        "4096",
        "--max-num-seqs",
        "64",
    )


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
        "--prefix-caching-hash-algo",
        "--enable-chunked-prefill",
        "--no-enable-chunked-prefill",
        "--max-num-batched-tokens",
    ),
)
def test_vllm_serving_policy_owns_performance_flags(flag: str) -> None:
    stack = _stack(engine_args=(flag, "x"))
    with pytest.raises(ValueError, match="platform-owned"):
        model_stack_launch_settings(stack)


def test_model_serving_policy_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires prefix_caching"):
        ModelServingPolicy(prefix_cache_hash_algorithm="sha256")
    with pytest.raises(ValueError, match="max_batch_tokens"):
        ModelServingPolicy(max_batch_tokens=0)
