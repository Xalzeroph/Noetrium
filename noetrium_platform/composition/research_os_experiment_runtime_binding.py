"""Canonical static runtime-binding authority for Research OS Experiments.

Owner systems resolve the concrete Study execution adapter, metric aggregation,
and reconciliation implementation. This composition authority only freezes their
typed identities together with the run-local Artifact-store factory into the
existing ResearchOSExperimentRuntimeBinding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.research.experimentation.lifecycle.api import (
    BoundStudyExecutionPort,
    StudyMetricAggregationPort,
)

from .research_os_experiment import (
    ResearchOSExperimentArtifactStoreFactoryPort,
    ResearchOSExperimentClosure,
    ResearchOSExperimentReconciliationPort,
    ResearchOSExperimentRuntimeBinding,
    ResearchOSExperimentRuntimeBindingPort,
)


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentStudyExecutionBinding:
    adapter: BoundStudyExecutionPort
    identity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, BoundStudyExecutionPort):
            raise TypeError(
                "Experiment Study execution binding requires BoundStudyExecutionPort"
            )
        require_sha256(
            self.identity_digest,
            "Experiment Study execution binding identity_digest",
        )


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentAggregationBinding:
    aggregation: StudyMetricAggregationPort
    identity_digest: str

    def __post_init__(self) -> None:
        if not callable(getattr(self.aggregation, "aggregate", None)):
            raise TypeError(
                "Experiment aggregation binding requires StudyMetricAggregationPort"
            )
        require_sha256(
            self.identity_digest,
            "Experiment aggregation binding identity_digest",
        )


@runtime_checkable
class ResearchOSExperimentStudyExecutionResolverPort(Protocol):
    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentStudyExecutionBinding: ...


@runtime_checkable
class ResearchOSExperimentAggregationResolverPort(Protocol):
    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentAggregationBinding: ...


@runtime_checkable
class ResearchOSExperimentReconciliationResolverPort(Protocol):
    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentReconciliationPort: ...


class ResearchOSExperimentRuntimeBindingAuthority(
    ResearchOSExperimentRuntimeBindingPort
):
    """Single static Experiment runtime composition authority."""

    def __init__(
        self,
        *,
        study_execution: ResearchOSExperimentStudyExecutionResolverPort,
        aggregation: ResearchOSExperimentAggregationResolverPort,
        artifacts: ResearchOSExperimentArtifactStoreFactoryPort,
        reconciliation: ResearchOSExperimentReconciliationResolverPort,
    ) -> None:
        if not isinstance(
            study_execution,
            ResearchOSExperimentStudyExecutionResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires Study execution resolver"
            )
        if not isinstance(
            aggregation,
            ResearchOSExperimentAggregationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires aggregation resolver"
            )
        if not isinstance(
            artifacts,
            ResearchOSExperimentArtifactStoreFactoryPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires Artifact-store factory"
            )
        if not isinstance(
            reconciliation,
            ResearchOSExperimentReconciliationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires reconciliation resolver"
            )
        require_sha256(
            artifacts.identity_digest,
            "Experiment Artifact-store factory identity",
        )
        self._study_execution = study_execution
        self._aggregation = aggregation
        self._artifacts = artifacts
        self._reconciliation = reconciliation

    @property
    def artifact_store_factory(self) -> ResearchOSExperimentArtifactStoreFactoryPort:
        return self._artifacts

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentRuntimeBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Experiment runtime authority requires ResearchOSExperimentClosure"
            )

        study_execution = self._study_execution.resolve(closure)
        if type(study_execution) is not ResearchOSExperimentStudyExecutionBinding:
            raise TypeError(
                "Study execution resolver returned invalid Experiment binding"
            )

        aggregation = self._aggregation.resolve(closure)
        if type(aggregation) is not ResearchOSExperimentAggregationBinding:
            raise TypeError(
                "aggregation resolver returned invalid Experiment binding"
            )

        reconciliation = self._reconciliation.resolve(closure)
        if not isinstance(
            reconciliation,
            ResearchOSExperimentReconciliationPort,
        ):
            raise TypeError(
                "reconciliation resolver returned invalid Experiment authority"
            )
        require_sha256(
            reconciliation.identity_digest,
            "Experiment reconciliation identity",
        )

        binding = ResearchOSExperimentRuntimeBinding(
            closure.closure_digest,
            closure.experiment_program.plan.plan_digest,
            closure.research_plan.binding_digest,
            study_execution.adapter,
            aggregation.aggregation,
            self._artifacts,
            reconciliation,
            study_execution.identity_digest,
            aggregation.identity_digest,
            self._artifacts.identity_digest,
            reconciliation.identity_digest,
        )
        binding.validate_closure(closure)
        return binding


__all__ = [
    "ResearchOSExperimentAggregationBinding",
    "ResearchOSExperimentAggregationResolverPort",
    "ResearchOSExperimentReconciliationResolverPort",
    "ResearchOSExperimentRuntimeBindingAuthority",
    "ResearchOSExperimentStudyExecutionBinding",
    "ResearchOSExperimentStudyExecutionResolverPort",
]
