"""Single composition root for repository reproduction fleet authorities.

Deployment code supplies owner-system resolvers only. Paper packages never wire
Research OS, benchmark discovery, research binding aggregation, or fleet
execution themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

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
from .authority_requirements import (
    ReproductionFleetCapabilityRequirementManifest,
    ReproductionFleetOwnerRequirementManifest,
    ReproductionFleetPrerequisiteManifest,
    compile_materialized_fleet_capability_requirements,
    compile_materialized_fleet_owner_requirements,
    compile_repository_fleet_prerequisites,
)
from .fleet import (
    ReproductionBenchmarkResolverPort,
    ReproductionFleetAuthorityAudit,
    ReproductionFleetExecutionAuthorities,
    ReproductionFleetMaterialization,
    audit_materialized_reproduction_fleet_authorities,
    materialize_repository_execution_fleet,
)
from .research_os import (
    ReproductionCapabilityRequirementResolverPort,
    ReproductionCapabilitySelectionRegistry,
)



@dataclass(frozen=True, slots=True)
class ReproductionFleetPrerequisiteAuthorities:
    """Owner-materialized authority needed to make exact Studies exist."""

    benchmark_resolutions: BenchmarkResolutionRegistry
    reproduction_capabilities: ReproductionCapabilitySelectionRegistry | None = None

    def __post_init__(self) -> None:
        if type(self.benchmark_resolutions) is not BenchmarkResolutionRegistry:
            raise TypeError(
                "fleet prerequisite authorities require BenchmarkResolutionRegistry"
            )
        if (
            self.reproduction_capabilities is not None
            and type(self.reproduction_capabilities)
            is not ReproductionCapabilitySelectionRegistry
        ):
            raise TypeError(
                "fleet prerequisite capabilities must be "
                "ReproductionCapabilitySelectionRegistry"
            )

    @property
    def authority_digest(self) -> str:
        return canonical_digest(
            {
                "schema": "noetrium.reproduction-fleet-prerequisite-authorities.v1",
                "benchmark_registry_digest": self.benchmark_resolutions.identity_digest,
                "reproduction_capability_registry_digest": (
                    None
                    if self.reproduction_capabilities is None
                    else self.reproduction_capabilities.identity_digest
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetOwnerAuthorities:
    """Typed execution-owner registries after ProjectManifest materialization."""

    research_capabilities: ResearchCapabilityBindingRegistry
    participants: ResearchParticipantBindingRegistry
    models: ResearchModelRoleBindingRegistry
    trial_providers: ResearchOSExperimentTrialProviderRegistry
    reconciliation: ResearchOSExperimentReconciliationRegistry
    aggregation: ResearchOSExperimentAggregationRegistry | None = None

    def __post_init__(self) -> None:
        expected = (
            (
                "research_capabilities",
                self.research_capabilities,
                ResearchCapabilityBindingRegistry,
            ),
            ("participants", self.participants, ResearchParticipantBindingRegistry),
            ("models", self.models, ResearchModelRoleBindingRegistry),
            (
                "trial_providers",
                self.trial_providers,
                ResearchOSExperimentTrialProviderRegistry,
            ),
            (
                "reconciliation",
                self.reconciliation,
                ResearchOSExperimentReconciliationRegistry,
            ),
        )
        for field_name, value, kind in expected:
            if type(value) is not kind:
                raise TypeError(
                    f"fleet owner authorities {field_name} must be {kind.__name__}"
                )
        if (
            self.aggregation is not None
            and type(self.aggregation)
            is not ResearchOSExperimentAggregationRegistry
        ):
            raise TypeError(
                "fleet owner authorities aggregation must be "
                "ResearchOSExperimentAggregationRegistry"
            )

    @property
    def authority_digest(self) -> str:
        aggregation = (
            ResearchOSExperimentAggregationRegistry.canonical()
            if self.aggregation is None
            else self.aggregation
        )
        return canonical_digest(
            {
                "schema": "noetrium.reproduction-fleet-owner-authorities.v1",
                "research_capability_registry_digest": (
                    self.research_capabilities.identity_digest
                ),
                "participant_registry_digest": self.participants.identity_digest,
                "model_registry_digest": self.models.identity_digest,
                "trial_provider_registry_digest": self.trial_providers.identity_digest,
                "aggregation_registry_digest": aggregation.identity_digest,
                "reconciliation_registry_digest": self.reconciliation.identity_digest,
            }
        )


class ReproductionFleetAuthorityMaterializationError(RuntimeError):
    """Exact owner registries did not close every materialized fleet lane."""

    def __init__(
        self,
        audit: ReproductionFleetAuthorityAudit,
        *,
        prerequisite_manifest_digest: str,
        owner_requirement_manifest_digest: str,
        capability_requirement_manifest_digest: str,
    ) -> None:
        if type(audit) is not ReproductionFleetAuthorityAudit:
            raise TypeError(
                "fleet authority materialization error requires typed audit"
            )
        require_sha256(
            prerequisite_manifest_digest,
            "fleet authority materialization prerequisite manifest",
        )
        require_sha256(
            owner_requirement_manifest_digest,
            "fleet authority materialization owner requirement manifest",
        )
        require_sha256(
            capability_requirement_manifest_digest,
            "fleet authority materialization capability requirement manifest",
        )
        self.audit = audit
        self.prerequisite_manifest_digest = prerequisite_manifest_digest
        self.owner_requirement_manifest_digest = owner_requirement_manifest_digest
        self.capability_requirement_manifest_digest = (
            capability_requirement_manifest_digest
        )
        self.error_digest = canonical_digest(
            {
                "schema": "noetrium.reproduction-fleet-authority-materialization-error.v1",
                "prerequisite_manifest_digest": prerequisite_manifest_digest,
                "owner_requirement_manifest_digest": owner_requirement_manifest_digest,
                "capability_requirement_manifest_digest": (
                    capability_requirement_manifest_digest
                ),
                "audit_digest": audit.audit_digest,
                "blocker_count": audit.blocker_count,
                "gap_count": audit.gap_count,
            }
        )
        super().__init__(
            "fleet owner authority materialization is incomplete: "
            f"blockers={audit.blocker_count}, gaps={audit.gap_count}"
        )


@runtime_checkable
class ReproductionFleetAuthorityMaterializerPort(Protocol):
    """Owner-system materialization seam for zero-glue fleet launch.

    Implementations may inspect only their own authoritative provider/resource
    state. They receive content-addressed requirement manifests and must return
    exact typed registries; provider selection heuristics do not belong here.
    """

    def materialize_prerequisites(
        self,
        requirements: ReproductionFleetPrerequisiteManifest,
    ) -> ReproductionFleetPrerequisiteAuthorities: ...

    def materialize_manifests(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        fleet: ReproductionFleetMaterialization,
    ) -> ResearchProjectManifestRegistry: ...

    def materialize_execution_owners(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        capability_requirements: ReproductionFleetCapabilityRequirementManifest,
        fleet: ReproductionFleetMaterialization,
        manifests: ResearchProjectManifestRegistry,
    ) -> ReproductionFleetOwnerAuthorities: ...


@dataclass(frozen=True, slots=True)
class MaterializedReproductionFleetExecutionAuthorities:
    prerequisites: ReproductionFleetPrerequisiteManifest
    prerequisite_authorities: ReproductionFleetPrerequisiteAuthorities
    fleet: ReproductionFleetMaterialization
    owner_requirements: ReproductionFleetOwnerRequirementManifest
    manifests: ResearchProjectManifestRegistry
    capability_requirements: ReproductionFleetCapabilityRequirementManifest
    owner_authorities: ReproductionFleetOwnerAuthorities
    execution_authorities: ReproductionFleetExecutionAuthorities
    materialization_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.prerequisites) is not ReproductionFleetPrerequisiteManifest:
            raise TypeError("materialized fleet authorities require prerequisites")
        if (
            type(self.prerequisite_authorities)
            is not ReproductionFleetPrerequisiteAuthorities
        ):
            raise TypeError(
                "materialized fleet authorities require prerequisite authorities"
            )
        if type(self.fleet) is not ReproductionFleetMaterialization:
            raise TypeError("materialized fleet authorities require fleet")
        if (
            type(self.owner_requirements)
            is not ReproductionFleetOwnerRequirementManifest
        ):
            raise TypeError(
                "materialized fleet authorities require owner requirements"
            )
        if type(self.manifests) is not ResearchProjectManifestRegistry:
            raise TypeError(
                "materialized fleet authorities require ProjectManifest registry"
            )
        if (
            type(self.capability_requirements)
            is not ReproductionFleetCapabilityRequirementManifest
        ):
            raise TypeError(
                "materialized fleet authorities require capability requirements"
            )
        if type(self.owner_authorities) is not ReproductionFleetOwnerAuthorities:
            raise TypeError(
                "materialized fleet authorities require execution-owner authorities"
            )
        if (
            self.capability_requirements.materialization_digest
            != self.fleet.materialization_digest
            or self.capability_requirements.project_manifest_registry_digest
            != self.manifests.identity_digest
        ):
            raise ValueError(
                "capability requirement manifest does not belong to fleet/manifest cut"
            )
        if (
            type(self.execution_authorities)
            is not ReproductionFleetExecutionAuthorities
        ):
            raise TypeError(
                "materialized fleet authorities require execution authorities"
            )
        if (
            self.owner_requirements.materialization_digest
            != self.fleet.materialization_digest
        ):
            raise ValueError(
                "owner requirement manifest does not belong to materialized fleet"
            )
        object.__setattr__(
            self,
            "materialization_digest",
            canonical_digest(
                {
                    "schema": "noetrium.materialized-fleet-execution-authorities.v1",
                    "prerequisite_manifest_digest": self.prerequisites.manifest_digest,
                    "prerequisite_authority_digest": (
                        self.prerequisite_authorities.authority_digest
                    ),
                    "fleet_materialization_digest": self.fleet.materialization_digest,
                    "owner_requirement_manifest_digest": (
                        self.owner_requirements.manifest_digest
                    ),
                    "project_manifest_registry_digest": self.manifests.identity_digest,
                    "capability_requirement_manifest_digest": (
                        self.capability_requirements.manifest_digest
                    ),
                    "owner_authority_digest": self.owner_authorities.authority_digest,
                    "execution_authority_manifest_digest": (
                        self.execution_authorities.authority_manifest_digest
                    ),
                }
            ),
        )


def materialize_repository_fleet_execution_authorities(
    materializer: ReproductionFleetAuthorityMaterializerPort,
) -> MaterializedReproductionFleetExecutionAuthorities:
    """requirements -> owner materialization -> fleet -> owner registries -> authority."""

    if not isinstance(materializer, ReproductionFleetAuthorityMaterializerPort):
        raise TypeError(
            "fleet authority materialization requires "
            "ReproductionFleetAuthorityMaterializerPort"
        )

    prerequisites = compile_repository_fleet_prerequisites()
    prerequisite_authorities = materializer.materialize_prerequisites(
        prerequisites
    )
    if (
        type(prerequisite_authorities)
        is not ReproductionFleetPrerequisiteAuthorities
    ):
        raise TypeError(
            "fleet prerequisite materializer returned invalid authority bundle"
        )

    benchmark_authority = RepositoryBenchmarkAuthority.discover(
        prerequisite_authorities.benchmark_resolutions
    )
    fleet = materialize_repository_execution_fleet(
        benchmark_authority,
        capability_resolver=(
            prerequisite_authorities.reproduction_capabilities
        ),
    )
    owner_requirements = compile_materialized_fleet_owner_requirements(fleet)
    manifests = materializer.materialize_manifests(
        owner_requirements,
        fleet,
    )
    if type(manifests) is not ResearchProjectManifestRegistry:
        raise TypeError(
            "fleet ProjectManifest materializer returned invalid registry"
        )
    capability_requirements = compile_materialized_fleet_capability_requirements(
        fleet,
        manifests,
    )
    owner_authorities = materializer.materialize_execution_owners(
        owner_requirements,
        capability_requirements,
        fleet,
        manifests,
    )
    if type(owner_authorities) is not ReproductionFleetOwnerAuthorities:
        raise TypeError(
            "fleet execution-owner materializer returned invalid authority bundle"
        )

    execution_authorities = (
        compose_repository_fleet_execution_authorities_from_registries(
            manifests=manifests,
            research_capabilities=owner_authorities.research_capabilities,
            participants=owner_authorities.participants,
            models=owner_authorities.models,
            trial_providers=owner_authorities.trial_providers,
            experiment_reconciliation=owner_authorities.reconciliation,
            experiment_aggregation=owner_authorities.aggregation,
            reproduction_capabilities=(
                prerequisite_authorities.reproduction_capabilities
            ),
            benchmark_resolutions=(
                prerequisite_authorities.benchmark_resolutions
            ),
            benchmarks=benchmark_authority,
        )
    )
    audit = audit_materialized_reproduction_fleet_authorities(
        fleet,
        research_bindings=execution_authorities.research_bindings,
        experiment_runtime_components=(
            execution_authorities.experiment_runtime_components
        ),
        authority_manifest_digest=(
            execution_authorities.authority_manifest_digest
        ),
    )
    if audit.blocker_count or audit.gap_count:
        raise ReproductionFleetAuthorityMaterializationError(
            audit,
            prerequisite_manifest_digest=prerequisites.manifest_digest,
            owner_requirement_manifest_digest=owner_requirements.manifest_digest,
            capability_requirement_manifest_digest=(
                capability_requirements.manifest_digest
            ),
        )

    return MaterializedReproductionFleetExecutionAuthorities(
        prerequisites,
        prerequisite_authorities,
        fleet,
        owner_requirements,
        manifests,
        capability_requirements,
        owner_authorities,
        execution_authorities,
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
    benchmark_authority_digest: str
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
            "benchmark_authority_digest",
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
                    "schema": "noetrium.reproduction-fleet-authority-manifest.v3",
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
                    "benchmark_authority_digest": self.benchmark_authority_digest,
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
    benchmark_authority_digest: str,
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
        benchmark_authority_digest=benchmark_authority_digest,
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
    require_sha256(
        benchmark_authority.authority_digest,
        "fleet benchmark authority_digest",
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

    benchmark_authority = (
        RepositoryBenchmarkAuthority.discover(benchmark_resolutions)
        if benchmarks is None
        else benchmarks
    )
    if not isinstance(benchmark_authority, ReproductionBenchmarkResolverPort):
        raise TypeError(
            "registry fleet authority benchmarks must satisfy "
            "ReproductionBenchmarkResolverPort"
        )
    require_sha256(
        benchmark_authority.authority_digest,
        "registry fleet benchmark authority_digest",
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
        benchmark_authority_digest=benchmark_authority.authority_digest,
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
        benchmarks=benchmark_authority,
        authority_manifest_digest=authority_manifest.manifest_digest,
    )


__all__ = [
    "MaterializedReproductionFleetExecutionAuthorities",
    "ReproductionFleetAuthorityManifest",
    "ReproductionFleetAuthorityMaterializationError",
    "ReproductionFleetAuthorityMaterializerPort",
    "ReproductionFleetOwnerAuthorities",
    "ReproductionFleetPrerequisiteAuthorities",
    "compose_repository_fleet_execution_authorities",
    "compose_repository_fleet_execution_authorities_from_registries",
    "materialize_repository_fleet_execution_authorities",
]
