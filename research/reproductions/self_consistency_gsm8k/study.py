from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.gsm8k import (
    GSM8K_BENCHMARK_ID,
    GSM8K_SPLIT_COUNTS,
)

from .fidelity import SELF_CONSISTENCY_GSM8K_FIDELITY
from .program import SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM


def self_consistency_gsm8k_trial_protocol(
    benchmark,
):
    f = SELF_CONSISTENCY_GSM8K_FIDELITY
    if benchmark.benchmark_id != GSM8K_BENCHMARK_ID:
        raise ValueError("Self-Consistency study requires GSM8K benchmark")
    selected = benchmark.selected_tasks(f.benchmark_split)
    if len(selected) != GSM8K_SPLIT_COUNTS["test"]:
        raise ValueError(
            "Self-Consistency GSM8K paper lane requires the full 1319-task test split"
        )
    return _rs.study_protocol(
        "self-consistency.iclr-2023.gsm8k.palm540b.v1",
        _rs.canonical_digest(
            {
                "program_digest": SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(row.task_id for row in selected),
                "publication_lane_digest": f.publication.lane_digest,
                "cot_prompt_bundle": "cot.gsm8k.neurips2022.appendix-table20",
                "cot_exemplar_count": f.cot_exemplar_count,
                "reasoning_path_count": f.reasoning_path_count,
                "temperature": f.temperature,
                "top_k": f.top_k,
                "aggregation": f.aggregation,
                "paper_repetitions": f.paper_repetitions,
                "paper_reference_model": f.paper_reference_model,
            }
        ),
    )


@_rs.study_factory('benchmark')
def build_self_consistency_gsm8k_study(
    benchmark,
):
    f = SELF_CONSISTENCY_GSM8K_FIDELITY
    protocol = self_consistency_gsm8k_trial_protocol(benchmark)
    return _rs.study_spec(project_id="self-consistency-iclr-2023-reproduction",
        study_id="self-consistency-gsm8k-palm540b-40path",
        benchmark=benchmark,
        benchmark_split_id=f.benchmark_split,
        method=_rs.study_participant(
            role="reasoner",
            kind="agent_method",
            implementation="self-consistency",
            treatment="cot-40path-answer-marginalization",
            configurations=(
                "cot.gsm8k.neurips2022.appendix-table20",
                "self-consistency.palm540b.t0.7.k40.n40",
            ),
        ),
        models={
            "self-consistency.reasoner": _rs.study_model(
                "model.palm-540b.paper-reference",
                prompt="cot.gsm8k.neurips2022.appendix-table20",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="exact_numeric_answer_success",
                scale="binary",
                domain="gsm8k",
            ),
            _rs.scalar_measurement(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="resource_usage",
                scale="count",
                domain="self_consistency",
            ),
            _rs.scalar_measurement(
                "selected_vote_count",
                schema_id="noetrium.measurement.count.v1",
                unit="vote",
                semantic_kind="answer_consensus_count",
                scale="count",
                domain="self_consistency",
            ),
        ),
        trial=protocol,
        repetitions=f.paper_repetitions,
        seeds=("paper-sampling",),
        limits=_rs.trial_budget(
            "self-consistency-gsm8k-40-paths",
            max_steps=128,
            max_turns=f.reasoning_path_count,
            max_model_calls=f.reasoning_path_count,
        ),
        replay_level='observational',
    )


__all__ = [
    "build_self_consistency_gsm8k_study",
    "self_consistency_gsm8k_trial_protocol",
]
