"""Canonical static runtime-binding authority for Research execution Experiments.

Owner systems resolve the concrete Study execution adapter, metric aggregation,
and reconciliation implementation. This composition authority only freezes their
typed identities together with the run-local Artifact-store factory into the
existing ResearchExperimentRuntimeBinding.
"""
from __future__ import annotations
from noetrium_platform.research.experimentation.api.research_compiler import research_plan_study, research_plan_protocol, research_plan_value, research_plan_digest, compile_research_participant_schedule, research_plan_study_identity, research_plan_trial_protocol_identity
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_plan_provider_id,
    study_plan_digest,
    study_protocol_digest,
    BoundStudyExecutionPort,
)
from noetrium_platform.research.experimentation.api.program import require_experiment_compilation, experiment_compilation_plan, experiment_compilation_batches, experiment_compilation_execution_graph, experiment_compilation_batch_digest

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache
from .shared_host_pressure import ResourceCompetitionDemand

from .research_experiment import (
    ResearchExperimentExecutionBindingView,
    ResearchExperimentReconciliationPort,
    ResearchExperimentRuntimeBinding,
    ResearchExperimentRuntimeBindingPort,
    require_experiment_execution_binding,
)


@dataclass(frozen=True, slots=True)
class ResearchExperimentStudyExecutionBinding:
    adapter: BoundStudyExecutionPort
    identity_digest: str
    resource_demand: ResourceCompetitionDemand | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, BoundStudyExecutionPort):
            raise TypeError(
                "Experiment Study execution binding requires BoundStudyExecutionPort"
            )
        require_sha256(
            self.identity_digest,
            "Experiment Study execution binding identity_digest",
        )
        if self.resource_demand is not None and not isinstance(
            self.resource_demand, ResourceCompetitionDemand
        ):
            raise TypeError(
                "Experiment Study execution resource_demand must be ResourceCompetitionDemand"
            )


@runtime_checkable
class ResearchExperimentStudyExecutionResolverPort(Protocol):
    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentStudyExecutionBinding: ...


@runtime_checkable
class ResearchExperimentReconciliationResolverPort(Protocol):
    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentReconciliationPort: ...


@dataclass(frozen=True, slots=True)
class ResearchExperimentReconciliationRegistration:
    provider_identity: str
    trial_protocol_digest: str
    reconciliation: ResearchExperimentReconciliationPort
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
            ResearchExperimentReconciliationPort,
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


class ResearchExperimentReconciliationRegistry:
    """Exact reconciliation authority keyed by Trial provider + protocol."""

    def __init__(
        self,
        registrations: tuple[
            ResearchExperimentReconciliationRegistration, ...
        ],
    ) -> None:
        if type(registrations) is not tuple:
            raise TypeError(
                "Experiment reconciliation registry requires typed tuple"
            )
        if any(
            type(row) is not ResearchExperimentReconciliationRegistration
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
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentReconciliationPort:
        execution = require_experiment_execution_binding(execution)
        assert execution.research_plan is not None
        provider_identity = study_plan_provider_id(
            research_plan_study(execution.research_plan)
        )
        protocol_digest = research_plan_trial_protocol_identity(execution.research_plan).unit_digest
        registration = self._by_key.get(
            (provider_identity, protocol_digest)
        )
        if registration is None:
            raise LookupError(
                "no exact Experiment reconciliation authority for "
                f"provider={provider_identity!r} protocol={protocol_digest}"
            )
        return registration.reconciliation


class ResearchExperimentRuntimeBindingAuthority(
    ResearchExperimentRuntimeBindingPort
):
    """Single static Experiment runtime composition authority."""

    def __init__(
        self,
        *,
        study_execution: ResearchExperimentStudyExecutionResolverPort,
        reconciliation: ResearchExperimentReconciliationResolverPort,
    ) -> None:
        if not isinstance(
            study_execution,
            ResearchExperimentStudyExecutionResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires Study execution resolver"
            )
        if not isinstance(
            reconciliation,
            ResearchExperimentReconciliationResolverPort,
        ):
            raise TypeError(
                "Experiment runtime authority requires reconciliation resolver"
            )
        self._study_execution = study_execution
        self._reconciliation = reconciliation
        self._bindings: SingleFlightCache[
            ResearchExperimentRuntimeBinding
        ] = SingleFlightCache()

    def resolve(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentRuntimeBinding:
        execution = require_experiment_execution_binding(execution)
        binding = self._bindings.get_or_create(
            execution.binding_digest,
            lambda: self._resolve_uncached(execution),
        )
        binding.validate_execution_binding(execution)
        return binding

    def resolve_study_execution(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentStudyExecutionBinding:
        execution = require_experiment_execution_binding(execution)
        binding = self._study_execution.resolve(execution)
        if type(binding) is not ResearchExperimentStudyExecutionBinding:
            raise TypeError(
                "Study execution resolver returned invalid Experiment binding"
            )
        return binding

    def resolve_reconciliation(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentReconciliationPort:
        execution = require_experiment_execution_binding(execution)
        authority = self._reconciliation.resolve(execution)
        if not isinstance(authority, ResearchExperimentReconciliationPort):
            raise TypeError(
                "reconciliation resolver returned invalid Experiment authority"
            )
        require_sha256(
            authority.identity_digest,
            "Experiment reconciliation identity",
        )
        return authority

    def _resolve_uncached(
        self,
        execution: ResearchExperimentExecutionBindingView,
    ) -> ResearchExperimentRuntimeBinding:
        execution = require_experiment_execution_binding(execution)
        study_execution = self.resolve_study_execution(execution)
        reconciliation = self.resolve_reconciliation(execution)

        binding = ResearchExperimentRuntimeBinding(
            execution.binding_digest,
            study_plan_digest(experiment_compilation_plan(execution.experiment_program)),
            research_plan_value(execution.research_plan, "binding_digest"),
            study_execution.adapter,
            reconciliation,
            study_execution.identity_digest,
            reconciliation.identity_digest,
            study_execution.resource_demand,
        )
        binding.validate_execution_binding(execution)
        return binding


__all__ = [
    "ResearchExperimentReconciliationResolverPort",
    "ResearchExperimentReconciliationRegistry",
    "ResearchExperimentReconciliationRegistration",
    "ResearchExperimentRuntimeBindingAuthority",
    "ResearchExperimentStudyExecutionBinding",
    "ResearchExperimentStudyExecutionResolverPort",
]
