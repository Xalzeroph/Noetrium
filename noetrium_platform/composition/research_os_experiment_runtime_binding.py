"""Canonical static runtime-binding authority for Research OS Experiments.

Owner systems resolve the concrete Study execution adapter, metric aggregation,
and reconciliation implementation. This composition authority only freezes their
typed identities together with the run-local Artifact-store factory into the
existing ResearchOSExperimentRuntimeBinding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.api import (
    BoundStudyExecutionPort,
    DEFAULT_STUDY_AGGREGATION_REQUIREMENT_ID,
    StudyMetricAggregationPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
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
    requirement_id: str
    aggregation: StudyMetricAggregationPort
    identity_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.requirement_id) is not str
            or not self.requirement_id.strip()
            or self.requirement_id != self.requirement_id.strip()
        ):
            raise ValueError(
                "Experiment aggregation binding requirement_id must be canonical text"
            )
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


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentAggregationProvider:
    requirement_id: str
    aggregation: StudyMetricAggregationPort
    identity_digest: str

    def __post_init__(self) -> None:
        ResearchOSExperimentAggregationBinding(
            self.requirement_id,
            self.aggregation,
            self.identity_digest,
        )


class ResearchOSExperimentAggregationRegistry:
    """Exact Study aggregation authority keyed by scientific requirement id."""

    def __init__(
        self,
        providers: tuple[ResearchOSExperimentAggregationProvider, ...],
    ) -> None:
        if type(providers) is not tuple or not providers:
            raise TypeError(
                "Experiment aggregation registry requires non-empty typed tuple"
            )
        if any(
            type(row) is not ResearchOSExperimentAggregationProvider
            for row in providers
        ):
            raise TypeError(
                "Experiment aggregation registry providers must be typed"
            )
        ordered = tuple(sorted(providers, key=lambda row: row.requirement_id))
        ids = tuple(row.requirement_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError(
                "Experiment aggregation registry requirement ids must be unique"
            )
        self._providers = ordered
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.experiment-aggregation-registry.v1",
                "providers": tuple(
                    (row.requirement_id, row.identity_digest)
                    for row in ordered
                ),
            }
        )

    @classmethod
    def canonical(cls) -> "ResearchOSExperimentAggregationRegistry":
        identity = canonical_digest(
            {
                "schema": "noetrium.study-aggregation-provider.v1",
                "requirement_id": DEFAULT_STUDY_AGGREGATION_REQUIREMENT_ID,
                "algorithm": "mean-variance-standard-error",
                "algorithm_version": "1",
            }
        )
        return cls(
            (
                ResearchOSExperimentAggregationProvider(
                    DEFAULT_STUDY_AGGREGATION_REQUIREMENT_ID,
                    BasicStudyMetricAggregator(),
                    identity,
                ),
            )
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentAggregationBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Experiment aggregation registry requires ResearchOSExperimentClosure"
            )
        requirement_id = closure.definition.aggregation_requirement_id
        matches = tuple(
            row for row in self._providers
            if row.requirement_id == requirement_id
        )
        if len(matches) != 1:
            raise LookupError(
                f"no unique Experiment aggregation provider for {requirement_id!r}"
            )
        provider = matches[0]
        return ResearchOSExperimentAggregationBinding(
            provider.requirement_id,
            provider.aggregation,
            provider.identity_digest,
        )


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


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentRuntimeComponents:
    """Owner-system resolvers consumed by the Research OS composition root."""

    study_execution: ResearchOSExperimentStudyExecutionResolverPort
    aggregation: ResearchOSExperimentAggregationResolverPort
    reconciliation: ResearchOSExperimentReconciliationResolverPort

    def __post_init__(self) -> None:
        if not isinstance(
            self.study_execution,
            ResearchOSExperimentStudyExecutionResolverPort,
        ):
            raise TypeError(
                "Experiment runtime components require Study execution resolver"
            )
        if not isinstance(
            self.aggregation,
            ResearchOSExperimentAggregationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime components require aggregation resolver"
            )
        if not isinstance(
            self.reconciliation,
            ResearchOSExperimentReconciliationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime components require reconciliation resolver"
            )

    def bind(
        self,
        artifacts: ResearchOSExperimentArtifactStoreFactoryPort,
    ) -> "ResearchOSExperimentRuntimeBindingAuthority":
        if not isinstance(
            artifacts,
            ResearchOSExperimentArtifactStoreFactoryPort,
        ):
            raise TypeError(
                "Experiment runtime components require Artifact-store factory"
            )
        return ResearchOSExperimentRuntimeBindingAuthority(
            study_execution=self.study_execution,
            aggregation=self.aggregation,
            artifacts=artifacts,
            reconciliation=self.reconciliation,
        )


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
        if (
            aggregation.requirement_id
            != closure.definition.aggregation_requirement_id
        ):
            raise ValueError(
                "aggregation resolver changed Study aggregation requirement identity"
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
    "ResearchOSExperimentAggregationRegistry",
    "ResearchOSExperimentAggregationProvider",
    "ResearchOSExperimentAggregationResolverPort",
    "ResearchOSExperimentReconciliationResolverPort",
    "ResearchOSExperimentRuntimeComponents",
    "ResearchOSExperimentRuntimeBindingAuthority",
    "ResearchOSExperimentStudyExecutionBinding",
    "ResearchOSExperimentStudyExecutionResolverPort",
]
