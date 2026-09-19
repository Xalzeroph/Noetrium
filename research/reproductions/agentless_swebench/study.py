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
from research.benchmarks.swe_bench import SWEBENCH_BENCHMARK_ID

from .fidelity import AGENTLESS_FIDELITY
from .program import AGENTLESS_METHOD_PROGRAM


AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "agentless.fse2025.swe-bench-lite.v1",
    canonical_digest({
        "program_digest": AGENTLESS_METHOD_PROGRAM.program_digest,
        "source_commit": AGENTLESS_FIDELITY.audited_commit,
        "release": AGENTLESS_FIDELITY.release,
        "stages": AGENTLESS_FIDELITY.stages,
        "localization_levels": AGENTLESS_FIDELITY.localization_levels,
        "benchmark_subset": AGENTLESS_FIDELITY.benchmark_subset,
        "benchmark_task_count": AGENTLESS_FIDELITY.benchmark_task_count,
        "autonomous_agent_loop": False,
    }),
)


def build_agentless_swebench_lite_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != SWEBENCH_BENCHMARK_ID:
        raise ValueError("Agentless study requires SWE-bench")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("Agentless study requires a non-empty SWE-bench split")
    return Study(
        project_id="agentless-fse2025-reproduction",
        study_id=f"agentless-swe-bench-lite-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="workflow",
            kind="software_repair_method",
            implementation="agentless-v1.5.0",
            treatment="localize-repair-validate",
            capabilities=("software.command",),
            configurations=(
                "agentless.hierarchical-localization",
                "agentless.patch-sampling",
                "agentless.patch-validation",
            ),
        ),
        models={
            "file_localizer": StudyModel(
                "model.agentless.file-localizer",
                prompt="agentless.localization.files",
            ),
            "symbol_localizer": StudyModel(
                "model.agentless.symbol-localizer",
                prompt="agentless.localization.symbols",
            ),
            "edit_localizer": StudyModel(
                "model.agentless.edit-localizer",
                prompt="agentless.localization.edits",
            ),
            "repair": StudyModel(
                "model.agentless.repair",
                prompt="agentless.repair",
            ),
            "validation": StudyModel(
                "model.agentless.validation",
                prompt="agentless.validation",
            ),
            "rerank": StudyModel(
                "model.agentless.rerank",
                prompt="agentless.rerank",
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
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="agentless",
            ),
            MeasurementDefinition.scalar(
                "validation_count",
                schema_id="noetrium.measurement.count.v1",
                unit="validation_batch",
                semantic_kind="validation_usage",
                scale="count",
                domain="agentless",
            ),
        ),
        trial=AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "agentless-fse2025",
            max_steps=32,
            max_model_calls=16,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL",
    "build_agentless_swebench_lite_study",
]
