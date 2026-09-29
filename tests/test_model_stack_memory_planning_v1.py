from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.stack.api import (
    vllm_gpu_memory_utilization_for_target_bytes,
)
from noetrium_platform.composition.model_stack_materialization import (
    _GIB,
    _kv_cache_budget_bytes,
    _model_runtime_vram_budget_bytes,
)


def _qwen3_config(root: Path) -> None:
    (root / "config.json").write_text(
        json.dumps(
            {
                "hidden_size": 4096,
                "head_dim": 128,
                "max_position_embeddings": 40960,
                "num_attention_heads": 32,
                "num_hidden_layers": 36,
                "num_key_value_heads": 8,
                "torch_dtype": "bfloat16",
            }
        ),
        encoding="utf-8",
    )


def test_qwen3_full_context_vram_budget_is_geometry_derived(tmp_path: Path) -> None:
    _qwen3_config(tmp_path)
    raw_kv = 40960 * 36 * 8 * 128 * 2 * 2
    expected_kv = (raw_kv * 9 + 7) // 8

    assert _kv_cache_budget_bytes(
        tmp_path,
        context_length=40960,
        dtype="bfloat16",
        tensor_parallel=1,
    ) == expected_kv
    assert _model_runtime_vram_budget_bytes(
        tmp_path,
        total_asset_bytes=16 * _GIB,
        context_length=40960,
        dtype="bfloat16",
        tensor_parallel=1,
    ) == 16 * _GIB + expected_kv + 4 * _GIB


def test_tensor_parallel_reduces_weight_and_kv_budget(tmp_path: Path) -> None:
    _qwen3_config(tmp_path)
    one = _model_runtime_vram_budget_bytes(
        tmp_path,
        total_asset_bytes=16 * _GIB,
        context_length=40960,
        dtype="bfloat16",
        tensor_parallel=1,
    )
    two = _model_runtime_vram_budget_bytes(
        tmp_path,
        total_asset_bytes=16 * _GIB,
        context_length=40960,
        dtype="bfloat16",
        tensor_parallel=2,
    )
    assert two < one
    assert two > 8 * _GIB


def test_memory_utilization_rounds_up_absolute_global_target() -> None:
    external = 20 * _GIB
    reservation = 15 * _GIB
    total = 48 * _GIB
    target = external + reservation
    fraction = vllm_gpu_memory_utilization_for_target_bytes(target, total)
    assert fraction is not None
    assert fraction * total >= target
    assert fraction * total - target <= total / 1_000_000 + 1

    assert (
        vllm_gpu_memory_utilization_for_target_bytes(
            47 * _GIB,
            48 * _GIB,
        )
        is None
    )


def test_kv_planning_fails_closed_without_attention_geometry(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "max_position_embeddings": 40960,
                "torch_dtype": "bfloat16",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="attention-head geometry"):
        _kv_cache_budget_bytes(
            tmp_path,
            context_length=40960,
            dtype="bfloat16",
            tensor_parallel=1,
        )
