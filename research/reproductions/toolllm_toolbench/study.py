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
from research.benchmarks.toolbench import (
    TOOLBENCH_BENCHMARK_ID,
    TOOLBENCH_PAPER_CODE_COMMIT,
    TOOLBENCH_TOOLEVAL_COMMIT,
)

from .fidelity import TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY
from .program import build_toolllm_toolbench_method_program


def toolllm_toolbench_trial_protocol(
    capability_ids: tuple[str, ...],
    *,
    retrieval_mode: str,
) -> ExperimentTrialProtocolIdentity:
    program = build_toolllm_toolbench_method_program(
        capability_ids,
        retrieval_mode=retrieval_mode,
    )
    return ExperimentTrialProtocolIdentity(
        f"toolllm.toolbench.{retrieval_mode}.v1",
        canonical_digest(
            {
                "program_digest": program.program_digest,
                "source_commit": TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.audited_commit,
                "toolbench_code_commit": TOOLBENCH_PAPER_CODE_COMMIT,
                "tooleval_commit": TOOLBENCH_TOOLEVAL_COMMIT,
                "retrieval_mode": retrieval_mode,
                "capability_ids": capability_ids,
                "single_chain_max_step": (
                    TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.single_chain_max_step
                ),
                "tree_beam_size": (
                    TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.tree_beam_size
                ),
                "max_query_count": (
                    TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.max_query_count
                ),
                "with_filter": TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.with_filter,
            }
        ),
    )


def build_toolllm_toolbench_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
    capability_ids: tuple[str, ...],
    retrieval_mode: str = "oracle",
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != TOOLBENCH_BENCHMARK_ID:
        raise ValueError("ToolLLM study requires ToolBench")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("ToolLLM ToolBench study requires a non-empty split")
    program = build_toolllm_toolbench_method_program(
        capability_ids,
        retrieval_mode=retrieval_mode,
    )
    semantic_capabilities = (
        ("data.semantic-similarity",)
        if retrieval_mode == "retrieved-top5"
        else ()
    )
    method_capabilities = (*semantic_capabilities, *capability_ids)

    return Study(
        project_id="toolllm-iclr-reproduction",
        study_id=f"toolllm-toolbench-{split_id}-{retrieval_mode}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="toolllm",
            kind="agent_method",
            implementation="toolllm-paper-era-dfsdt",
            treatment=retrieval_mode,
            capabilities=method_capabilities,
            configurations=(
                "toolllm.dfsdt.paper-era",
                f"toolllm.api-binding.{retrieval_mode}",
            ),
        ),
        models={
            "toolllm.dfsdt-policy": StudyModel(
                "model.toolllm.policy",
                prompt="toolllm.dfsdt.function-calling.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="tool_eval_pass",
                scale="binary",
                domain="toolbench",
            ),
            MeasurementDefinition.scalar(
                "tool_eval_win",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="pairwise_preference",
                scale="ratio",
                domain="toolbench",
            ),
            MeasurementDefinition.scalar(
                "query_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="toolbench",
            ),
            MeasurementDefinition.scalar(
                "tool_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="tool_call",
                semantic_kind="tool_usage",
                scale="count",
                domain="toolbench",
            ),
            MeasurementDefinition.scalar(
                "give_up_count",
                schema_id="noetrium.measurement.count.v1",
                unit="restart",
                semantic_kind="search_restart",
                scale="count",
                domain="toolbench",
            ),
        ),
        trial=toolllm_toolbench_trial_protocol(
            capability_ids,
            retrieval_mode=retrieval_mode,
        ),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            f"toolllm-paper-era-{retrieval_mode}",
            max_steps=4096,
            max_model_calls=TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY.max_query_count,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_toolllm_toolbench_study",
    "toolllm_toolbench_trial_protocol",
]
