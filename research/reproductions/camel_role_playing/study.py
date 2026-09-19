from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    MeasurementValueKind,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.camel_ai_society import (
    CAMEL_AI_SOCIETY_BENCHMARK_ID,
    CAMEL_AI_SOCIETY_EVALUATION_SIZE,
    CAMEL_AI_SOCIETY_SPLIT_ID,
)

from .fidelity import CAMEL_ROLE_PLAYING_FIDELITY
from .program import CAMEL_AI_SOCIETY_METHOD_PROGRAM


def camel_ai_society_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    if benchmark.benchmark_id != CAMEL_AI_SOCIETY_BENCHMARK_ID:
        raise ValueError("CAMEL Study requires the paper-native AI Society benchmark")
    selected = benchmark.selected_tasks(CAMEL_AI_SOCIETY_SPLIT_ID)
    if len(selected) != CAMEL_AI_SOCIETY_EVALUATION_SIZE:
        raise ValueError(
            "CAMEL paper agent evaluation requires exactly "
            f"{CAMEL_AI_SOCIETY_EVALUATION_SIZE} tasks"
        )
    return ExperimentTrialProtocolIdentity(
        "camel.neurips-2023.ai-society.agent-eval.v1",
        canonical_digest(
            {
                "program_digest": CAMEL_AI_SOCIETY_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(row.task_id for row in selected),
                "source_commit": f.audited_commit,
                "conversation_population": f.conversation_population,
                "paper_evaluation_sample_size": f.paper_agent_evaluation_sample_size,
                "task_specification": f.paper_task_specification,
                "task_planning": f.paper_task_planning,
                "task_specifier_temperature": f.task_specifier_temperature,
                "default_chat_temperature": f.default_chat_temperature,
                "max_saved_messages": f.max_saved_messages,
                "task_done_token": f.task_done_token,
                "prompt_blobs": (
                    f.assistant_prompt_blob,
                    f.user_prompt_blob,
                    f.task_specify_prompt_blob,
                    f.generate_tasks_prompt_blob,
                ),
                "role_blobs": (
                    f.assistant_roles_blob,
                    f.user_roles_blob,
                ),
                "single_shot_baseline": f.single_shot_baseline_model,
                "pairwise_judges": f.pairwise_judges,
            }
        ),
    )


def _categorical(
    measurement_id: str,
    *,
    semantic_kind: str,
    domain: str,
) -> MeasurementDefinition:
    return MeasurementDefinition(
        measurement_id=measurement_id,
        schema_id="noetrium.measurement.categorical.v1",
        value_kind=MeasurementValueKind.CATEGORICAL,
        semantic_kind=semantic_kind,
        scale="nominal",
        domain=domain,
    )


def _boolean(
    measurement_id: str,
    *,
    semantic_kind: str,
    domain: str,
) -> MeasurementDefinition:
    return MeasurementDefinition(
        measurement_id=measurement_id,
        schema_id="noetrium.measurement.boolean.v1",
        value_kind=MeasurementValueKind.BOOLEAN,
        semantic_kind=semantic_kind,
        scale="binary",
        domain=domain,
    )


def build_camel_ai_society_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    protocol = camel_ai_society_trial_protocol(benchmark)
    shared_model = "model.camel.gpt-3.5-turbo.paper-era"
    return Study(
        project_id="camel-neurips-2023-reproduction",
        study_id="camel-ai-society-agent-eval-100",
        benchmark=benchmark,
        benchmark_split_id=CAMEL_AI_SOCIETY_SPLIT_ID,
        method=StudyParticipant(
            role="camel_role_play",
            kind="multi_agent_method",
            implementation="camel",
            treatment="paper-ai-society-role-playing",
            capabilities=(),
            configurations=(
                "camel.ai-society.paper-era",
                "camel.ai-society.prompt-bundle",
            ),
        ),
        models={
            "camel.task-specifier": StudyModel(
                shared_model,
                prompt="camel.ai-society.task-specify",
            ),
            "camel.task-planner": StudyModel(
                shared_model,
                prompt="camel.ai-society.task-plan",
            ),
            "camel.assistant-agent": StudyModel(
                shared_model,
                prompt="camel.ai-society.assistant-role",
            ),
            "camel.user-agent": StudyModel(
                shared_model,
                prompt="camel.ai-society.user-role",
            ),
            "camel.gpt4-judge": StudyModel(
                "model.camel.gpt-4.paper-evaluator",
                prompt="camel.ai-society.pairwise-judge",
                usage=ModelRoleUsage.EVALUATION,
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "num_messages",
                schema_id="noetrium.measurement.count.v1",
                unit="message",
                semantic_kind="public_transcript_message_count",
                scale="count",
                domain="camel_ai_society",
            ),
            _boolean(
                "task_done",
                semantic_kind="camel_task_done_observed",
                domain="camel_ai_society",
            ),
            _categorical(
                "termination_reason",
                semantic_kind="conversation_termination_reason",
                domain="camel_ai_society",
            ),
            MeasurementDefinition.scalar(
                "repeat_threshold_hits",
                schema_id="noetrium.measurement.count.v1",
                unit="hit",
                semantic_kind="released_repeat_word_threshold_hit",
                scale="count",
                domain="camel_ai_society",
            ),
            _categorical(
                "human_pairwise_outcome",
                semantic_kind="human_pairwise_preference",
                domain="camel_ai_society",
            ),
            _categorical(
                "gpt4_pairwise_outcome",
                semantic_kind="gpt4_pairwise_preference",
                domain="camel_ai_society",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-sample",),
        limits=TrialBudget(
            "camel-ai-society-40-message",
            max_steps=256,
            max_turns=f.max_saved_messages + 3,
            max_model_calls=f.max_saved_messages + 3,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_camel_ai_society_study",
    "camel_ai_society_trial_protocol",
]
