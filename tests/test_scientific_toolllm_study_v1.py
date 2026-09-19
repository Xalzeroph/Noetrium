from __future__ import annotations

import hashlib

from research.benchmarks.toolbench import (
    ToolBenchTaskRecord,
    build_toolbench_task_set,
)
from research.reproductions.toolllm_toolbench.study import (
    build_toolllm_toolbench_study,
    toolllm_toolbench_trial_protocol,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _benchmark(mode: str):
    return build_toolbench_task_set(
        (
            ToolBenchTaskRecord(
                query_id="q1",
                subset_id="I1-Inst",
                content_digest=_digest("task"),
                oracle_api_set_digest=_digest("apis"),
                oracle_api_count=2,
            ),
        ),
        dataset_revision="paper-cut",
        dataset_content_sha256=_digest("dataset"),
        api_binding_mode=mode,
    )


def test_toolllm_toolbench_oracle_study_freezes_program_and_tooleval_metrics() -> None:
    capabilities = ("weather_for_alpha", "news_for_beta")
    study = build_toolllm_toolbench_study(
        _benchmark("oracle"),
        split_id="I1-Inst",
        capability_ids=capabilities,
        retrieval_mode="oracle",
    )
    assert study.benchmark.benchmark_id == "toolbench"
    assert study.trial_protocol_identity.protocol_id == "toolllm.toolbench.oracle.v1"
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == (
        "give_up_count",
        "query_count",
        "task_success",
        "tool_call_count",
        "tool_eval_win",
    )
    method = next(
        row
        for row in study.binding_requirements.participants
        if row.role == "toolllm"
    )
    assert method.capability_requirement_ids == capabilities


def test_toolllm_retrieval_study_adds_semantic_capability_and_changes_protocol() -> None:
    capabilities = ("weather_for_alpha", "news_for_beta")
    oracle = toolllm_toolbench_trial_protocol(
        capabilities,
        retrieval_mode="oracle",
    )
    retrieved = toolllm_toolbench_trial_protocol(
        capabilities,
        retrieval_mode="retrieved-top5",
    )
    assert oracle.digest() != retrieved.digest()

    study = build_toolllm_toolbench_study(
        _benchmark("retrieved-top5"),
        split_id="I1-Inst",
        capability_ids=capabilities,
        retrieval_mode="retrieved-top5",
    )
    method = next(
        row
        for row in study.binding_requirements.participants
        if row.role == "toolllm"
    )
    assert method.capability_requirement_ids == (
        "data.semantic-similarity",
        "weather_for_alpha",
        "news_for_beta",
    )
    assert (
        study.trial_protocol_identity.protocol_id
        == "toolllm.toolbench.retrieved-top5.v1"
    )
