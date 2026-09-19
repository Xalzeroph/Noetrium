from __future__ import annotations

from noetrium_platform.research.experimentation.run.api import (
    ExperimentRunExecutionPort,
    RunArtifactStorePort,
)
from noetrium_platform.research.experimentation.run.runtime import ExperimentRunApplication
from noetrium_platform.research.experimentation.study.composition import (
    build_run_study_publication,
)
from noetrium_platform.research.experimentation.study.runtime import (
    BasicStudyMetricAggregator,
)


def build_default_experiment_run_application(
    artifacts: RunArtifactStorePort,
) -> ExperimentRunExecutionPort:
    """Compose compiled-plan run execution with publication authorities."""

    return ExperimentRunApplication(
        aggregation=BasicStudyMetricAggregator(),
        publication=build_run_study_publication(artifacts),
    )


__all__ = ["build_default_experiment_run_application"]
