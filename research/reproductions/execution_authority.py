"""Single composition root for repository reproduction fleet authorities.

Deployment code supplies owner-system resolvers only. Paper packages never wire
Research OS, benchmark discovery, research binding aggregation, or fleet
execution themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
    ResearchCapabilityBindingRegistry,
    ResearchCapabilityBindingResolverPort,
    ResearchModelRoleBindingRegistry,
    ResearchModelRoleBindingResolverPort,
    ResearchParticipantBindingRegistry,
    ResearchParticipantBindingResolverPort,
    ResearchProjectManifestRegistry,
    ResearchProjectManifestResolverPort,
)
from noetrium_platform.composition.research_os_experiment_trial_execution import (
    ResearchOSExperimentTrialProviderRegistry,
    ResearchOSExperimentTrialProviderResolverPort,
    ResearchOSExperimentTrialStudyExecutionResolver,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistry,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentAggregationRegistry,
    ResearchOSExperimentAggregationResolverPort,
    ResearchOSExperimentReconciliationRegistry,
    ResearchOSExperimentReconciliationResolverPort,
    ResearchOSExperimentRuntimeComponents,
    ResearchOSExperimentStudyExecutionResolverPort,
)

from .benchmark_authority import RepositoryBenchmarkAuthority
from .fleet import (
    ReproductionBenchmarkResolverPort,
    ReproductionFleetExecutionAuthorities,
)
from .research_os import (
    ReproductionCapabilityRequirementResolverPort,
    ReproductionCapabilitySelectionRegistry,
)



@dataclass(frozen=True, slots=True)
class ReproductionFleetAuthorityManifest:
    """Immutable identity of the complete owner-authority cut used by one fleet."""

    manifest_registry_digest: str
    research_capability_registry_digest: str
    participant_registry_digest: str
    model_registry_digest: str
    trial_provider_registry_digest: str
    aggregation_registry_digest: str
    reconciliation_registry_digest: str
    benchmark_registry_digest: str
    reproduction_capability_registry_digest: str | None = None
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "manifest_registry_digest",
            "research_capability_registry_digest",
            "participant_registry_digest",
            "model_registry_digest",
            "trial_provider_registry_digest",
            "aggregation_registry_digest",
            "reconciliation_registry_digest",
            "benchmark_registry_digest",
        ):
            require_sha256(
                getattr(self, field_name),
                f"fleet authority manifest {field_name}",
            )
        if self.reproduction_capability_registry_digest is not None:
            require_sha256(
                self.reproduction_capability_registry_digest,
                "fleet authority manifest reproduction_capability_registry_digest",
            )
        object.__setattr__(
            self,
            "manifest_digest",
            canonical_digest(
                {
                    "schema": "noetrium.reproduction-fleet-authority-manifest.v2",
                    "manifest_registry_digest": self.manifest_registry_digest,
                    "research_capability_registry_digest": (
                        self.research_capability_registry_digest
                    ),
                    "participant_registry_digest": self.participant_registry_digest,
                    "model_registry_digest": self.model_registry_digest,
                    "trial_provider_registry_digest": self.trial_provider_registry_digest,
                    "aggregation_registry_digest": self.aggregation_registry_digest,
                    "reconciliation_registry_digest": self.reconciliation_registry_digest,
                    "benchmark_registry_digest": self.benchmark_registry_digest,
                    "reproduction_capability_registry_digest": (
                        self.reproduction_capability_registry_digest
                    ),
                }
            ),
        )


def _registry_authority_manifest(
    *,
    manifests: ResearchProjectManifestRegistry,
    research_capabilities: ResearchCapabilityBindingRegistry,
    participants: ResearchParticipantBindingRegistry,
    models: ResearchModelRoleBindingRegistry,
    trial_providers: ResearchOSExperimentTrialProviderRegistry,
    experiment_aggregation: ResearchOSExperimentAggregationRegistry,
    experiment_reconciliation: ResearchOSExperimentReconciliationRegistry,
    benchmark_resolutions: BenchmarkResolutionRegistry | None,
    reproduction_capabilities: ReproductionCapabilitySelectionRegistry | None,
) -> ReproductionFleetAuthorityManifest:
    benchmark_registry = (
        BenchmarkResolutionRegistry()
        if benchmark_resolutions is None
        else benchmark_resolutions
    )
    return ReproductionFleetAuthorityManifest(
        manifest_registry_digest=manifests.identity_digest,
        research_capability_registry_digest=research_capabilities.identity_digest,
        participant_registry_digest=participants.identity_digest,
        model_registry_digest=models.identity_digest,
        trial_provider_registry_digest=trial_providers.identity_digest,
        aggregation_registry_digest=experiment_aggregation.identity_digest,
        reconciliation_registry_digest=experiment_reconciliation.identity_digest,
        benchmark_registry_digest=benchmark_registry.identity_digest,
        reproduction_capability_registry_digest=(
            None
            if reproduction_capabilities is None
            else reproduction_capabilities.identity_digest
        ),
    )


def compose_repository_fleet_execution_authorities(
    *,
    manifests: ResearchProjectManifestResolverPort,
    research_capabilities: ResearchCapabilityBindingResolverPort,
    participants: ResearchParticipantBindingResolverPort,
    models: ResearchModelRoleBindingResolverPort,
    experiment_reconciliation: ResearchOSExperimentReconciliationResolverPort,
    experiment_study_execution: ResearchOSExperimentStudyExecutionResolverPort | None = None,
    experiment_trial_providers: ResearchOSExperimentTrialProviderResolverPort | None = None,
    experiment_aggregation: ResearchOSExperimentAggregationResolverPort | None = None,
    reproduction_capabilities: (
        ReproductionCapabilityRequirementResolverPort | None
    ) = None,
    benchmark_resolutions: BenchmarkResolutionRegistry | None = None,
    benchmarks: ReproductionBenchmarkResolverPort | None = None,
    authority_manifest_digest: str,
) -> ReproductionFleetExecutionAuthorities:
    """Build the one canonical authority bundle consumed by the fleet launcher.

    The default benchmark authority admits only exact source-contained cuts.
    Benchmarks requiring external immutable data must be supplied by an explicit
    benchmark authority; they never fall back to synthetic or guessed cuts.
    """

    require_sha256(
        authority_manifest_digest,
        "fleet authority_manifest_digest",
    )
    if (
        benchmark_resolutions is not None
        and type(benchmark_resolutions) is not BenchmarkResolutionRegistry
    ):
        raise TypeError(
            "fleet benchmark_resolutions must be BenchmarkResolutionRegistry"
        )
    benchmark_authority = (
        RepositoryBenchmarkAuthority.discover(benchmark_resolutions)
        if benchmarks is None
        else benchmarks
    )
    if not isinstance(benchmark_authority, ReproductionBenchmarkResolverPort):
        raise TypeError(
            "fleet authority composition requires ReproductionBenchmarkResolverPort"
        )
    research_bindings = ResearchBindingAuthority(
        manifests,
        research_capabilities,
        participants,
        models,
    )
    if (experiment_study_execution is None) == (experiment_trial_providers is None):
        raise ValueError(
            "fleet authority composition requires exactly one of "
            "experiment_study_execution or experiment_trial_providers"
        )
    resolved_study_execution = (
        experiment_study_execution
        if experiment_study_execution is not None
        else ResearchOSExperimentTrialStudyExecutionResolver(
            experiment_trial_providers
        )
    )
    experiment_runtime_components = ResearchOSExperimentRuntimeComponents(
        study_execution=resolved_study_execution,
        aggregation=(
            ResearchOSExperimentAggregationRegistry.canonical()
            if experiment_aggregation is None
            else experiment_aggregation
        ),
        reconciliation=experiment_reconciliation,
    )
    return ReproductionFleetExecutionAuthorities(
        benchmark_resolver=benchmark_authority,
        research_bindings=research_bindings,
        experiment_runtime_components=experiment_runtime_components,
        capability_resolver=reproduction_capabilities,
        authority_manifest_digest=authority_manifest_digest,
    )



def compose_repository_fleet_execution_authorities_from_registries(
    *,
    manifests: ResearchProjectManifestRegistry,
    research_capabilities: ResearchCapabilityBindingRegistry,
    participants: ResearchParticipantBindingRegistry,
    models: ResearchModelRoleBindingRegistry,
    trial_providers: ResearchOSExperimentTrialProviderRegistry,
    experiment_reconciliation: ResearchOSExperimentReconciliationRegistry,
    experiment_aggregation: ResearchOSExperimentAggregationRegistry | None = None,
    reproduction_capabilities: (
        ReproductionCapabilitySelectionRegistry | None
    ) = None,
    benchmark_resolutions: BenchmarkResolutionRegistry | None = None,
    benchmarks: ReproductionBenchmarkResolverPort | None = None,
) -> ReproductionFleetExecutionAuthorities:
    """Compose the fleet from immutable proof-backed authority registries.

    Owner systems materialize and register their exact facts once. This helper
    contains no provider selection heuristics and delegates to the canonical
    resolver composition above.
    """

    for field_name, value, expected in (
        ("manifests", manifests, ResearchProjectManifestRegistry),
        (
            "research_capabilities",
            research_capabilities,
            ResearchCapabilityBindingRegistry,
        ),
        ("participants", participants, ResearchParticipantBindingRegistry),
        ("models", models, ResearchModelRoleBindingRegistry),
        (
            "trial_providers",
            trial_providers,
            ResearchOSExperimentTrialProviderRegistry,
        ),
        (
            "experiment_reconciliation",
            experiment_reconciliation,
            ResearchOSExperimentReconciliationRegistry,
        ),
    ):
        if type(value) is not expected:
            raise TypeError(
                f"registry fleet authority {field_name} must be {expected.__name__}"
            )

    if (
        experiment_aggregation is not None
        and type(experiment_aggregation)
        is not ResearchOSExperimentAggregationRegistry
    ):
        raise TypeError(
            "registry fleet authority experiment_aggregation must be "
            "ResearchOSExperimentAggregationRegistry"
        )
    resolved_aggregation = (
        ResearchOSExperimentAggregationRegistry.canonical()
        if experiment_aggregation is None
        else experiment_aggregation
    )

    if (
        reproduction_capabilities is not None
        and type(reproduction_capabilities)
        is not ReproductionCapabilitySelectionRegistry
    ):
        raise TypeError(
            "registry fleet authority reproduction_capabilities must be "
            "ReproductionCapabilitySelectionRegistry"
        )

    authority_manifest = _registry_authority_manifest(
        manifests=manifests,
        research_capabilities=research_capabilities,
        participants=participants,
        models=models,
        trial_providers=trial_providers,
        experiment_aggregation=resolved_aggregation,
        experiment_reconciliation=experiment_reconciliation,
        benchmark_resolutions=benchmark_resolutions,
        reproduction_capabilities=reproduction_capabilities,
    )

    return compose_repository_fleet_execution_authorities(
        manifests=manifests,
        research_capabilities=research_capabilities,
        participants=participants,
        models=models,
        experiment_reconciliation=experiment_reconciliation,
        experiment_trial_providers=trial_providers,
        experiment_aggregation=resolved_aggregation,
        reproduction_capabilities=reproduction_capabilities,
        benchmark_resolutions=benchmark_resolutions,
        benchmarks=benchmarks,
        authority_manifest_digest=authority_manifest.manifest_digest,
    )


__all__ = [
    "ReproductionFleetAuthorityManifest",
    "compose_repository_fleet_execution_authorities",
    "compose_repository_fleet_execution_authorities_from_registries",
]
