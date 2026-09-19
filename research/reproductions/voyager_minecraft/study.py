from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.voyager_minecraft import (
    VOYAGER_MINECRAFT_BENCHMARK_ID,
    VOYAGER_MINECRAFT_LIFELONG_SPLIT,
    VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
    VOYAGER_MINECRAFT_TRIAL_COUNT,
)

from .chest_memory import VOYAGER_CHEST_MEMORY_PROGRAM
from .curriculum_memory import VOYAGER_QA_MEMORY_PROGRAM
from .fidelity import VOYAGER_AUDITED_COMMIT, VOYAGER_MINECRAFT_FIDELITY
from .program import VOYAGER_MINECRAFT_METHOD_PROGRAM
from .skill_memory import VOYAGER_SKILL_MEMORY_PROGRAM


def voyager_tmlr2024_trial_protocol(
    benchmark: BenchmarkTaskSet,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != VOYAGER_MINECRAFT_BENCHMARK_ID:
        raise ValueError("Voyager protocol requires voyager-minecraft benchmark")
    selected = benchmark.selected_tasks(VOYAGER_MINECRAFT_LIFELONG_SPLIT)
    if len(selected) != VOYAGER_MINECRAFT_TRIAL_COUNT:
        raise ValueError("Voyager protocol requires exactly three paper trials")
    fidelity = VOYAGER_MINECRAFT_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "voyager.tmlr2024.open-world-lifelong.v1",
        canonical_digest({
            "source_commit": VOYAGER_AUDITED_COMMIT,
            "benchmark_cut_digest": benchmark.cut_digest,
            "benchmark_split_id": VOYAGER_MINECRAFT_LIFELONG_SPLIT,
            "trial_task_ids": tuple(row.task_id for row in selected),
            "method_program_digest": (
                VOYAGER_MINECRAFT_METHOD_PROGRAM.program_digest
            ),
            "skill_memory_program_digest": (
                VOYAGER_SKILL_MEMORY_PROGRAM.program_digest
            ),
            "chest_memory_program_digest": (
                VOYAGER_CHEST_MEMORY_PROGRAM.program_digest
            ),
            "qa_memory_program_digest": VOYAGER_QA_MEMORY_PROGRAM.program_digest,
            "max_prompting_iterations": (
                VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS
            ),
            "action_task_max_retries": fidelity.action_task_max_retries,
            "critic_parse_max_retries": fidelity.critic_parse_max_retries,
            "skill_retrieval_top_k": fidelity.skill_retrieval_top_k,
            "initial_task": fidelity.initial_curriculum_task,
            "initial_difficulty": fidelity.initial_difficulty,
            "post_warmup_difficulty": fidelity.post_warmup_difficulty,
            "post_warmup_threshold": (
                fidelity.post_warmup_completed_task_threshold
            ),
            "task_reset_semantics": "reset-rejoin-after-each-task",
            "world_semantics": "independent-fresh-world-per-trial",
            "paper_world_seeds": "unpublished",
        }),
    )


def build_voyager_tmlr2024_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    protocol = voyager_tmlr2024_trial_protocol(benchmark)
    return Study(
        project_id="voyager-tmlr-2024-reproduction",
        study_id="voyager-tmlr-2024-open-world-lifelong",
        benchmark=benchmark,
        benchmark_split_id=VOYAGER_MINECRAFT_LIFELONG_SPLIT,
        method=StudyParticipant(
            role="embodied_lifelong_agent",
            kind="method",
            implementation="voyager",
            treatment="tmlr-2024-paper-release",
            capabilities=(
                "environment.minecraft",
                "execution.program.execute",
                "research.random.bernoulli-mask",
                "memory.skill-library",
                "memory.chest-state",
                "memory.curriculum-qa",
            ),
            configurations=(
                "voyager.max-iterations-160",
                "voyager.skill-top-k-5",
                "voyager.task-reset-rejoin",
                "voyager.curriculum-warmup-15",
            ),
        ),
        models={
            "curriculum": StudyModel(
                "model.voyager.paper-era-gpt4",
                prompt="voyager.curriculum.prompt",
            ),
            "action": StudyModel(
                "model.voyager.paper-era-gpt4",
                prompt="voyager.action.prompt",
            ),
            "critic": StudyModel(
                "model.voyager.paper-era-gpt4",
                prompt="voyager.critic.prompt",
            ),
            "skill_description": StudyModel(
                "model.voyager.paper-era-gpt35",
                prompt="voyager.skill-description.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "unique_item_count",
                schema_id="noetrium.measurement.count.v1",
                unit="item_type",
                semantic_kind="minecraft_unique_item_discovery",
                scale="count",
                domain="voyager_open_world",
            ),
            MeasurementDefinition.scalar(
                "wooden_tool_unlock_iteration",
                schema_id="noetrium.measurement.count.v1",
                unit="prompting_iteration",
                semantic_kind="minecraft_tech_tree_unlock_time",
                scale="count",
                domain="wooden_tool",
            ),
            MeasurementDefinition.scalar(
                "stone_tool_unlock_iteration",
                schema_id="noetrium.measurement.count.v1",
                unit="prompting_iteration",
                semantic_kind="minecraft_tech_tree_unlock_time",
                scale="count",
                domain="stone_tool",
            ),
            MeasurementDefinition.scalar(
                "iron_tool_unlock_iteration",
                schema_id="noetrium.measurement.count.v1",
                unit="prompting_iteration",
                semantic_kind="minecraft_tech_tree_unlock_time",
                scale="count",
                domain="iron_tool",
            ),
            MeasurementDefinition.scalar(
                "diamond_tool_unlock_iteration",
                schema_id="noetrium.measurement.count.v1",
                unit="prompting_iteration",
                semantic_kind="minecraft_tech_tree_unlock_time",
                scale="count",
                domain="diamond_tool",
            ),
            MeasurementDefinition.scalar(
                "travel_distance_blocks",
                schema_id="noetrium.measurement.distance.v1",
                unit="minecraft_block",
                semantic_kind="minecraft_exploration_distance",
                scale="continuous",
                domain="voyager_open_world",
            ),
            MeasurementDefinition.scalar(
                "learned_skill_count",
                schema_id="noetrium.measurement.count.v1",
                unit="skill",
                semantic_kind="executable_skill_library_size",
                scale="count",
                domain="voyager_skill_library",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-world-seeds-unpublished",),
        limits=TrialBudget(
            "voyager-tmlr2024-open-world-budget",
            max_steps=8192,
            max_turns=VOYAGER_MINECRAFT_MAX_PROMPTING_ITERATIONS,
            max_model_calls=4096,
            max_working_seconds=86400.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=86400.0,
    ).build()


__all__ = [
    "build_voyager_tmlr2024_study",
    "voyager_tmlr2024_trial_protocol",
]
