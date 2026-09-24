"""Single composition root for repository reproduction fleet authorities.

Deployment code supplies owner-system resolvers only. Paper packages never wire
Research OS, benchmark discovery, research binding aggregation, or fleet
execution themselves.
"""
from __future__ import annotations

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
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentAggregationRegistry,
    ResearchOSExperimentAggregationResolverPort,
    ResearchOSExperimentReconciliationResolverPort,
    ResearchOSExperimentRuntimeComponents,
    ResearchOSExperimentStudyExecutionResolverPort,
)

from .benchmark_authority import RepositoryBenchmarkAuthority
from .fleet import (
    ReproductionBenchmarkResolverPort,
    ReproductionFleetExecutionAuthorities,
)
from .research_os import ReproductionCapabilityRequirementResolverPort


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
    benchmarks: ReproductionBenchmarkResolverPort | None = None,
) -> ReproductionFleetExecutionAuthorities:
    """Build the one canonical authority bundle consumed by the fleet launcher.

    The default benchmark authority admits only exact source-contained cuts.
    Benchmarks requiring external immutable data must be supplied by an explicit
    benchmark authority; they never fall back to synthetic or guessed cuts.
    """

    benchmark_authority = (
        RepositoryBenchmarkAuthority.discover()
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
    )



def compose_repository_fleet_execution_authorities_from_registries(
    *,
    manifests: ResearchProjectManifestRegistry,
    research_capabilities: ResearchCapabilityBindingRegistry,
    participants: ResearchParticipantBindingRegistry,
    models: ResearchModelRoleBindingRegistry,
    trial_providers: ResearchOSExperimentTrialProviderRegistry,
    experiment_reconciliation: ResearchOSExperimentReconciliationResolverPort,
    experiment_aggregation: ResearchOSExperimentAggregationResolverPort | None = None,
    reproduction_capabilities: (
        ReproductionCapabilityRequirementResolverPort | None
    ) = None,
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
    ):
        if type(value) is not expected:
            raise TypeError(
                f"registry fleet authority {field_name} must be {expected.__name__}"
            )

    return compose_repository_fleet_execution_authorities(
        manifests=manifests,
        research_capabilities=research_capabilities,
        participants=participants,
        models=models,
        experiment_reconciliation=experiment_reconciliation,
        experiment_trial_providers=trial_providers,
        experiment_aggregation=experiment_aggregation,
        reproduction_capabilities=reproduction_capabilities,
        benchmarks=benchmarks,
    )


__all__ = [
    "compose_repository_fleet_execution_authorities",
    "compose_repository_fleet_execution_authorities_from_registries",
]
