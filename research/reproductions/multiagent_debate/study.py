from __future__ import annotations

from noetrium.api import canonical_digest
from noetrium.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.gsm8k import (
    GSM8K_BENCHMARK_ID,
    GSM8K_SPLIT_COUNTS,
)

from .fidelity import MULTIAGENT_DEBATE_FIDELITY
from .program import MULTIAGENT_DEBATE_METHOD_PROGRAM


_GSM8K_SPLIT = "test"


def multiagent_debate_gsm8k_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    f = MULTIAGENT_DEBATE_FIDELITY
    if benchmark.benchmark_id != GSM8K_BENCHMARK_ID:
        raise ValueError("multi-agent debate study requires GSM8K")
    selected = benchmark.selected_tasks(_GSM8K_SPLIT)
    if len(selected) != GSM8K_SPLIT_COUNTS[_GSM8K_SPLIT]:
        raise ValueError(
            "multi-agent debate GSM8K lane requires the complete test split"
        )
    return ExperimentTrialProtocolIdentity(
        "multiagent-debate.gsm8k.paper-era.v1",
        canonical_digest(
            {
                "program_digest": MULTIAGENT_DEBATE_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(row.task_id for row in selected),
                "source_commit": f.audited_commit,
                "agent_count": f.default_agent_count,
                "round_count": f.default_round_count,
                "independent_agent_contexts": f.independent_agent_contexts,
                "round_information_semantics": f.round_information_semantics,
                "peer_responses_are_injected_as_user_information": (
                    f.peer_responses_are_injected_as_user_information
                ),
                "reference_model": f.model_at_audited_gsm_script,
                "final_answer_format": f.final_answer_format,
            }
        ),
    )


def build_multiagent_debate_gsm8k_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    f = MULTIAGENT_DEBATE_FIDELITY
    protocol = multiagent_debate_gsm8k_trial_protocol(benchmark)
    model_id = "model.multiagent-debate.gpt-3.5-turbo-0301"
    return Study(
        project_id="multiagent-debate-reproduction",
        study_id="multiagent-debate-gsm8k-3-agent-2-round",
        benchmark=benchmark,
        benchmark_split_id=_GSM8K_SPLIT,
        method=StudyParticipant(
            role="debate",
            kind="multi_agent_method",
            implementation="multiagent-debate",
            treatment="three-agent-two-round-paper-era",
            capabilities=(),
            configurations=(
                "multiagent-debate.independent-contexts",
                "multiagent-debate.previous-round-peer-snapshot",
                "multiagent-debate.boxed-answer",
            ),
        ),
        models={
            "multiagent-debate.agent-0": StudyModel(
                model_id,
                prompt="multiagent-debate.gsm8k.paper-era",
            ),
            "multiagent-debate.agent-1": StudyModel(
                model_id,
                prompt="multiagent-debate.gsm8k.paper-era",
            ),
            "multiagent-debate.agent-2": StudyModel(
                model_id,
                prompt="multiagent-debate.gsm8k.paper-era",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="exact_numeric_answer_success",
                scale="binary",
                domain="gsm8k",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="resource_usage",
                scale="count",
                domain="multiagent_debate",
            ),
            MeasurementDefinition.scalar(
                "debate_round_count",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="debate_round_count",
                scale="count",
                domain="multiagent_debate",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-era",),
        limits=TrialBudget(
            "multiagent-debate-3x2",
            max_steps=20,
            max_turns=6,
            max_model_calls=6,
            max_working_seconds=600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_multiagent_debate_gsm8k_study",
    "multiagent_debate_gsm8k_trial_protocol",
]
