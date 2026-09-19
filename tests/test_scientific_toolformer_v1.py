from __future__ import annotations

from hashlib import sha256

import pytest

from research.benchmarks.toolformer_eval import (
    TOOLFORMER_BENCHMARK_ID,
    ToolformerEvalRecord,
    build_toolformer_eval_task_set,
)
from research.reproductions.toolformer import (
    TOOLFORMER_FIDELITY,
    ToolformerCallLosses,
    build_toolformer_method_program,
    build_toolformer_study,
    toolformer_keep_call,
    toolformer_normalized_future_weights,
)


def _benchmark():
    records = (
        ToolformerEvalRecord(
            "ASDiv",
            "toolformer:asdiv:001",
            "Solve the arithmetic problem.",
            sha256(b"asdiv-001").hexdigest(),
        ),
        ToolformerEvalRecord(
            "T-REx",
            "toolformer:trex:001",
            "Complete the missing fact.",
            sha256(b"trex-001").hexdigest(),
        ),
    )
    return build_toolformer_eval_task_set(
        records,
        dataset_content_sha256=sha256(b"toolformer-eval-cut").hexdigest(),
    )


def test_toolformer_filtering_matches_paper_loss_criterion() -> None:
    losses = ToolformerCallLosses(
        no_call=3.0,
        call_without_result=2.5,
        call_with_result=1.0,
    )
    assert losses.loss_without_result == 2.5
    assert losses.utility == 1.5
    assert toolformer_keep_call(losses, filtering_threshold=1.0)
    assert not toolformer_keep_call(losses, filtering_threshold=2.0)


def test_toolformer_future_weights_follow_paper_decay() -> None:
    weights = toolformer_normalized_future_weights(6)
    assert sum(weights) == pytest.approx(1.0)
    assert weights == pytest.approx(
        (1.0 / 3.0, 0.8 / 3.0, 0.6 / 3.0, 0.4 / 3.0, 0.2 / 3.0, 0.0)
    )
    assert TOOLFORMER_FIDELITY.training_batch_size == 128
    assert TOOLFORMER_FIDELITY.learning_rate == 1e-5


def test_toolformer_enabled_and_disabled_are_distinct_programs() -> None:
    capabilities = (
        "tool.question-answering",
        "tool.wikipedia-search",
        "tool.calculator",
        "tool.calendar",
        "tool.machine-translation",
    )
    enabled = build_toolformer_method_program(capabilities, tools_enabled=True)
    disabled = build_toolformer_method_program(capabilities, tools_enabled=False)
    assert enabled.program_digest != disabled.program_digest
    assert enabled.required_capabilities == capabilities
    assert disabled.required_capabilities == ()


def test_toolformer_study_binds_zero_shot_cut_and_disabled_baseline() -> None:
    benchmark = _benchmark()
    assert benchmark.benchmark_id == TOOLFORMER_BENCHMARK_ID
    capabilities = ("tool.calculator", "tool.question-answering")
    enabled = build_toolformer_study(
        benchmark,
        split_id="paper-zero-shot",
        tool_capability_ids=capabilities,
        tools_enabled=True,
    )
    disabled = build_toolformer_study(
        benchmark,
        split_id="paper-zero-shot",
        tool_capability_ids=capabilities,
        tools_enabled=False,
    )
    assert enabled.benchmark.cut_digest == benchmark.cut_digest
    assert enabled.trial_protocol_identity.protocol_id == (
        "toolformer.neurips2023.tools-enabled.v1"
    )
    assert disabled.trial_protocol_identity.protocol_id == (
        "toolformer.neurips2023.tools-disabled.v1"
    )
    assert enabled.trial_protocol_identity.configuration_digest != (
        disabled.trial_protocol_identity.configuration_digest
    )
