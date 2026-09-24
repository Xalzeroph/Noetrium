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
from research.benchmarks.swe_bench import SWEBENCH_BENCHMARK_ID

from .fidelity import LIVE_SWE_AGENT_FIDELITY
from .program import LIVE_SWE_AGENT_METHOD_PROGRAM


def live_swe_agent_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    f = LIVE_SWE_AGENT_FIDELITY
    if benchmark.benchmark_id != SWEBENCH_BENCHMARK_ID:
        raise ValueError("Live-SWE-agent study requires SWE-bench")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("Live-SWE-agent SWE-bench study requires a non-empty split")
    return ExperimentTrialProtocolIdentity(
        "live-swe-agent.v1.0.0.swe-bench.v1",
        canonical_digest(
            {
                "program_digest": LIVE_SWE_AGENT_METHOD_PROGRAM.program_digest,
                "benchmark_cut_digest": benchmark.cut_digest,
                "split_id": split_id,
                "task_ids": tuple(row.task_id for row in selected),
                "release_tag": f.release_tag,
                "source_commit": f.audited_commit,
                "base_scaffold": f.base_scaffold,
                "one_action_per_turn": f.one_action_per_turn,
                "runtime_tool_creation": f.runtime_tool_creation,
                "trajectory_reflection_before_tool_creation": (
                    f.trajectory_reflection_before_tool_creation
                ),
                "created_tools_are_python_cli_programs": (
                    f.created_tools_are_python_cli_programs
                ),
                "paper_default_step_limit": f.default_step_limit,
                "paper_default_cost_limit": f.default_cost_limit,
            }
        ),
    )


def build_live_swe_agent_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    protocol = live_swe_agent_trial_protocol(
        benchmark,
        split_id=split_id,
    )
    return Study(
        project_id="live-swe-agent-reproduction",
        study_id=f"live-swe-agent-swe-bench-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="agent",
            kind="self_evolving_software_agent",
            implementation="live-swe-agent",
            treatment="v1.0.0-runtime-tool-creation",
            capabilities=("software.command",),
            configurations=(
                "live-swe-agent.mini-swe-agent",
                "live-swe-agent.runtime-tool-creation",
                "live-swe-agent.trajectory-reflection",
            ),
        ),
        models={
            "live-swe-agent.worker": StudyModel(
                "model.live-swe-agent.worker",
                prompt="live-swe-agent.worker.v1.0.0",
            ),
            "live-swe-agent.tool-reflection": StudyModel(
                "model.live-swe-agent.worker",
                prompt="live-swe-agent.tool-reflection.v1.0.0",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_resolved",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="swe-bench",
            ),
            MeasurementDefinition.scalar(
                "turn_count",
                schema_id="noetrium.measurement.count.v1",
                unit="turn",
                semantic_kind="resource_usage",
                scale="count",
                domain="swe-bench",
            ),
            MeasurementDefinition.scalar(
                "command_count",
                schema_id="noetrium.measurement.count.v1",
                unit="command",
                semantic_kind="tool_usage",
                scale="count",
                domain="swe-bench",
            ),
            MeasurementDefinition.scalar(
                "tool_creation_count",
                schema_id="noetrium.measurement.count.v1",
                unit="tool",
                semantic_kind="runtime_self_modification",
                scale="count",
                domain="swe-bench",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "live-swe-agent-v1.0.0-host-safety",
            max_steps=4096,
            max_turns=512,
            max_model_calls=640,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_live_swe_agent_study",
    "live_swe_agent_trial_protocol",
]
