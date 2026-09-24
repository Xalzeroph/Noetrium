from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
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
from research.benchmarks.osworld import OSWORLD_BENCHMARK_ID

from .fidelity import AGENT_S3_FIDELITY
from .program import AGENT_S3_METHOD_PROGRAM


def agent_s3_osworld_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    f = AGENT_S3_FIDELITY
    if benchmark.benchmark_id != OSWORLD_BENCHMARK_ID:
        raise ValueError("Agent S3 study requires OSWorld")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("Agent S3 OSWorld study requires a non-empty split")
    return ExperimentTrialProtocolIdentity(
        "agent-s3.osworld.v0.3.2.v1",
        canonical_digest(
            {
                "program_digest": AGENT_S3_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "split_id": split_id,
                "task_ids": tuple(row.task_id for row in selected),
                "release": f.release,
                "release_commit": f.release_commit,
                "reflection_enabled": f.default_reflection_enabled,
                "max_trajectory_length": f.default_max_trajectory_length,
                "action_interface": f.action_interface,
                "one_action_per_turn": f.one_action_per_turn,
                "runtime_tool_creation": f.runtime_tool_creation,
                "code_agent_budget": f.code_agent_budget,
                "paper_default_step_limit": f.default_step_limit,
                "paper_default_cost_limit": f.default_cost_limit,
            }
        ),
    )


def build_agent_s3_osworld_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    protocol = agent_s3_osworld_trial_protocol(
        benchmark,
        split_id=split_id,
    )
    return Study(
        project_id="agent-s3-reproduction",
        study_id=f"agent-s3-osworld-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="agent",
            kind="gui_agent_method",
            implementation="agent-s3",
            treatment="v0.3.2-single-worker-reflection",
            capabilities=("environment.act",),
            configurations=(
                "agent-s3.reflection",
                "agent-s3.context-projection",
                "agent-s3.runtime-tool-creation",
            ),
        ),
        models={
            "agent-s3.reflection": StudyModel(
                "model.agent-s3.vlm",
                prompt="agent-s3.reflection.v0.3.2",
            ),
            "agent-s3.worker": StudyModel(
                "model.agent-s3.vlm",
                prompt="agent-s3.worker.v0.3.2",
            ),
            "agent-s3.code-agent": StudyModel(
                "model.agent-s3.code",
                prompt="agent-s3.code-agent.v0.3.2",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="osworld",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="model_usage",
                scale="count",
                domain="osworld",
            ),
            MeasurementDefinition.scalar(
                "device_action_count",
                schema_id="noetrium.measurement.count.v1",
                unit="action",
                semantic_kind="tool_usage",
                scale="count",
                domain="osworld",
            ),
            MeasurementDefinition.scalar(
                "iteration_count",
                schema_id="noetrium.measurement.count.v1",
                unit="iteration",
                semantic_kind="resource_usage",
                scale="count",
                domain="osworld",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "agent-s3-v0.3.2-host-safety",
            max_steps=4096,
            max_turns=256,
            max_model_calls=532,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "agent_s3_osworld_trial_protocol",
    "build_agent_s3_osworld_study",
]
