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
from research.benchmarks.osworld import OSWORLD_BENCHMARK_ID

from .fidelity import UI_TARS_DESKTOP_V001_FIDELITY
from .program import UI_TARS_DESKTOP_V001_METHOD_PROGRAM

UI_TARS_OSWORLD_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "ui-tars.desktop-v001.osworld.v1",
    canonical_digest(
        {
            "program_digest": UI_TARS_DESKTOP_V001_METHOD_PROGRAM.program_digest,
            "source_commit": UI_TARS_DESKTOP_V001_FIDELITY.audited_commit,
            "release_version": UI_TARS_DESKTOP_V001_FIDELITY.release_version,
            "coordinate_factor": UI_TARS_DESKTOP_V001_FIDELITY.coordinate_factor,
            "max_loop_count": UI_TARS_DESKTOP_V001_FIDELITY.max_loop_count,
            "max_retained_images": UI_TARS_DESKTOP_V001_FIDELITY.max_retained_images,
            "screenshot_retry_count": UI_TARS_DESKTOP_V001_FIDELITY.screenshot_retry_count,
            "screenshot_failure_limit": UI_TARS_DESKTOP_V001_FIDELITY.screenshot_failure_limit,
        }
    ),
)


def build_ui_tars_osworld_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != OSWORLD_BENCHMARK_ID:
        raise ValueError("UI-TARS Desktop study requires OSWorld")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("UI-TARS OSWorld study requires a non-empty split")

    return Study(
        project_id="ui-tars-desktop-v001-reproduction",
        study_id=f"ui-tars-desktop-v001-osworld-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="ui-tars-desktop-v001",
            treatment="desktop-0.0.1",
            capabilities=("environment.query", "environment.act"),
            configurations=("ui-tars.desktop-v001.prompt",),
        ),
        models={
            "agent": StudyModel(
                "model.ui-tars.vlm",
                prompt="ui-tars.desktop-v001.prompt",
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
                "loop_count",
                schema_id="noetrium.measurement.count.v1",
                unit="loop",
                semantic_kind="resource_usage",
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
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="model_usage",
                scale="count",
                domain="osworld",
            ),
            MeasurementDefinition.scalar(
                "snapshot_error_count",
                schema_id="noetrium.measurement.count.v1",
                unit="error",
                semantic_kind="environment_observation_failure",
                scale="count",
                domain="osworld",
            ),
        ),
        trial=UI_TARS_OSWORLD_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "ui-tars-desktop-v001-host-safety",
            max_steps=4096,
            max_turns=UI_TARS_DESKTOP_V001_FIDELITY.max_loop_count,
            max_model_calls=UI_TARS_DESKTOP_V001_FIDELITY.max_loop_count,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "UI_TARS_OSWORLD_TRIAL_PROTOCOL",
    "build_ui_tars_osworld_study",
]
