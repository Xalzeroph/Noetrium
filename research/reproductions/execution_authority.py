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
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentRuntimeBindingPort,
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
    experiment_bindings: ResearchOSExperimentRuntimeBindingPort,
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
    return ReproductionFleetExecutionAuthorities(
        benchmark_resolver=benchmark_authority,
        research_bindings=research_bindings,
        experiment_bindings=experiment_bindings,
        capability_resolver=reproduction_capabilities,
    )


__all__ = ["compose_repository_fleet_execution_authorities"]
