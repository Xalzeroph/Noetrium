"""Single composition root for repository reproduction fleet authorities.

Deployment code supplies owner-system resolvers only. Paper packages never wire
Research OS, benchmark discovery, research binding aggregation, or fleet
execution themselves.
"""
from __future__ import annotations

from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
    ResearchCapabilityBindingResolverPort,
    ResearchModelRoleBindingResolverPort,
    ResearchParticipantBindingResolverPort,
    ResearchProjectManifestResolverPort,
)
from noetrium_platform.composition.research_os_experiment_trial_execution import (
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


__all__ = ["compose_repository_fleet_execution_authorities"]
