"""Canonical static runtime-binding authority for Research OS Experiments.

Owner systems resolve the concrete Study execution adapter, metric aggregation,
and reconciliation implementation. This composition authority only freezes their
typed identities together with the run-local Artifact-store factory into the
existing ResearchOSExperimentRuntimeBinding.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BoundStudyExecutionPort,
    DEFAULT_STUDY_AGGREGATION_REQUIREMENT_ID,
    StudyMetricAggregationPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
)

from .research_os_experiment import (
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
class ResearchOSExperimentReconciliationRegistration:
    provider_identity: str
    trial_protocol_digest: str
    reconciliation: ResearchOSExperimentReconciliationPort
    registration_digest: str = ""

    def __post_init__(self) -> None:
        if (
            type(self.provider_identity) is not str
            or not self.provider_identity.strip()
            or self.provider_identity != self.provider_identity.strip()
        ):
            raise ValueError(
                "Experiment reconciliation provider_identity must be canonical text"
            )
        require_sha256(
            self.trial_protocol_digest,
            "Experiment reconciliation trial_protocol_digest",
        )
        if not isinstance(
            self.reconciliation,
            ResearchOSExperimentReconciliationPort,
        ):
            raise TypeError(
                "Experiment reconciliation registration requires typed authority"
            )
        require_sha256(
            self.reconciliation.identity_digest,
            "Experiment reconciliation authority identity",
        )
        expected = canonical_digest(
            {
                "provider_identity": self.provider_identity,
                "trial_protocol_digest": self.trial_protocol_digest,
                "reconciliation_identity_digest": (
                    self.reconciliation.identity_digest
                ),
            }
        )
        if self.registration_digest:
            if self.registration_digest != expected:
                raise ValueError(
                    "Experiment reconciliation registration digest drifted"
                )
        else:
            object.__setattr__(self, "registration_digest", expected)


class ResearchOSExperimentReconciliationRegistry:
    """Exact reconciliation authority keyed by Trial provider + protocol."""

    def __init__(
        self,
        registrations: tuple[
            ResearchOSExperimentReconciliationRegistration, ...
        ],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Experiment reconciliation registry requires typed tuple"
            )
        if any(
            type(row) is not ResearchOSExperimentReconciliationRegistration
            for row in registrations
        ):
            raise TypeError(
                "Experiment reconciliation registry registrations must be typed"
            )
        keys = tuple(
            (row.provider_identity, row.trial_protocol_digest)
            for row in registrations
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Experiment reconciliation registry contains duplicate authority"
            )
        self._registrations = tuple(
            sorted(registrations, key=lambda row: row.registration_digest)
        )
        self._by_key = {
            (row.provider_identity, row.trial_protocol_digest): row
            for row in self._registrations
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.experiment-reconciliation-registry.v1",
                "registrations": tuple(
                    row.registration_digest for row in self._registrations
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentReconciliationPort:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Experiment reconciliation registry requires "
                "ResearchOSExperimentClosure"
            )
        provider_ids = {
            row.provider_id
            for row in closure.research_plan.experiment_plan.bindings
        }
        if len(provider_ids) != 1:
            raise ValueError(
                "Experiment closure must select exactly one Trial provider "
                "for reconciliation"
            )
        provider_identity = next(iter(provider_ids))
        protocol_digest = closure.research_plan.trial_protocol_identity.digest()
        registration = self._by_key.get(
            (provider_identity, protocol_digest)
        )
        if registration is None:
            raise LookupError(
                "no exact Experiment reconciliation authority for "
                f"provider={provider_identity!r} protocol={protocol_digest}"
            )
        return registration.reconciliation


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

    def bind(self) -> "ResearchOSExperimentRuntimeBindingAuthority":
        return ResearchOSExperimentRuntimeBindingAuthority(
            study_execution=self.study_execution,
            aggregation=self.aggregation,
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
            reconciliation,
            ResearchOSExperimentReconciliationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires reconciliation resolver"
            )
        self._study_execution = study_execution
        self._aggregation = aggregation
        self._reconciliation = reconciliation
        self._cache_lock = Lock()
        self._bindings: dict[str, ResearchOSExperimentRuntimeBinding] = {}
        self._binding_locks: dict[str, Lock] = {}

    def _binding_lock(self, closure_digest: str) -> Lock:
        with self._cache_lock:
            lock = self._binding_locks.get(closure_digest)
            if lock is None:
                lock = Lock()
                self._binding_locks[closure_digest] = lock
            return lock

    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentRuntimeBinding:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "Experiment runtime authority requires ResearchOSExperimentClosure"
            )

        closure_digest = closure.closure_digest
        with self._cache_lock:
            cached = self._bindings.get(closure_digest)
        if cached is not None:
            cached.validate_closure(closure)
            return cached

        with self._binding_lock(closure_digest):
            with self._cache_lock:
                cached = self._bindings.get(closure_digest)
            if cached is not None:
                cached.validate_closure(closure)
                return cached

            return self._resolve_uncached(closure)

    def _resolve_uncached(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentRuntimeBinding:
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
            reconciliation,
            study_execution.identity_digest,
            aggregation.identity_digest,
            reconciliation.identity_digest,
        )
        binding.validate_closure(closure)
        with self._cache_lock:
            current = self._bindings.get(closure.closure_digest)
            if (
                current is not None
                and current.runtime_binding_digest != binding.runtime_binding_digest
            ):
                raise RuntimeError(
                    "Experiment runtime binding identity drifted during materialization"
                )
            self._bindings[closure.closure_digest] = binding
        return binding


__all__ = [
    "ResearchOSExperimentAggregationBinding",
    "ResearchOSExperimentAggregationRegistry",
    "ResearchOSExperimentAggregationProvider",
    "ResearchOSExperimentAggregationResolverPort",
    "ResearchOSExperimentReconciliationResolverPort",
    "ResearchOSExperimentReconciliationRegistry",
    "ResearchOSExperimentReconciliationRegistration",
    "ResearchOSExperimentRuntimeComponents",
    "ResearchOSExperimentRuntimeBindingAuthority",
    "ResearchOSExperimentStudyExecutionBinding",
    "ResearchOSExperimentStudyExecutionResolverPort",
]
