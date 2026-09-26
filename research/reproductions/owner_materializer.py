"""Canonical owner-registry materialization for repository fleet execution.

This module contains no provider-selection policy and no execution loop. It
projects exact owner-system resolver results into immutable fleet registries,
with Portfolio remaining authoritative for ProjectManifest truth.
"""
from __future__ import annotations

from dataclasses import dataclass

from noetrium import api
from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
    ResearchBindingResolutionContext,
    ResearchCapabilityBindingRegistration,
    ResearchCapabilityBindingRegistry,
    ResearchCapabilityBindingResolverPort,
    ResearchModelRoleBindingRegistration,
    ResearchModelRoleBindingRegistry,
    ResearchModelRoleBindingResolverPort,
    ResearchParticipantBindingRegistration,
    ResearchParticipantBindingRegistry,
    ResearchParticipantBindingResolverPort,
    ResearchProjectManifestRegistry,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentReconciliationRegistration,
    ResearchOSExperimentReconciliationRegistry,
    ResearchOSExperimentReconciliationResolverPort,
)
from noetrium_platform.composition.research_os_experiment_trial_execution import (
    ResearchOSExperimentTrialProviderRegistration,
    ResearchOSExperimentTrialProviderRegistry,
    ResearchOSExperimentTrialProviderResolverPort,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import PortfolioCatalogPort
from noetrium_platform.research.experimentation.api import (
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistry,
)

from .authority_requirements import (
    ReproductionFleetCapabilityRequirementManifest,
    ReproductionFleetOwnerRequirementManifest,
)
from .execution_authority import (
    ReproductionFleetOwnerAuthorities,
    ReproductionFleetPrerequisiteAuthorities,
)
from .fleet import (
    ReproductionFleetExperimentClosureProvider,
    ReproductionFleetMaterialization,
)
from .research_os import ReproductionCapabilitySelectionRegistry


def _dedupe_by_key(rows, *, key, digest, label: str):
    by_key = {}
    for row in rows:
        current = by_key.get(key(row))
        if current is None:
            by_key[key(row)] = row
            continue
        if digest(current) != digest(row):
            raise ValueError(f"{label} has conflicting exact authority for {key(row)!r}")
    return tuple(
        by_key[item]
        for item in sorted(by_key)
    )


@dataclass(frozen=True, slots=True)
class RepositoryFleetOwnerSources:
    """Owner-system resolvers consumed by the generic repository materializer."""

    portfolio: PortfolioCatalogPort
    capabilities: ResearchCapabilityBindingResolverPort
    participants: ResearchParticipantBindingResolverPort
    models: ResearchModelRoleBindingResolverPort
    trial_providers: ResearchOSExperimentTrialProviderResolverPort
    reconciliation: ResearchOSExperimentReconciliationResolverPort

    def __post_init__(self) -> None:
        for field_name, value, port in (
            ("portfolio", self.portfolio, PortfolioCatalogPort),
            (
                "capabilities",
                self.capabilities,
                ResearchCapabilityBindingResolverPort,
            ),
            (
                "participants",
                self.participants,
                ResearchParticipantBindingResolverPort,
            ),
            ("models", self.models, ResearchModelRoleBindingResolverPort),
            (
                "trial_providers",
                self.trial_providers,
                ResearchOSExperimentTrialProviderResolverPort,
            ),
            (
                "reconciliation",
                self.reconciliation,
                ResearchOSExperimentReconciliationResolverPort,
            ),
        ):
            if not isinstance(value, port):
                raise TypeError(
                    f"repository fleet owner source {field_name} must satisfy typed port"
                )


class RepositoryFleetAuthorityMaterializer:
    """Freeze owner-system truth into the canonical three-stage fleet registries."""

    def __init__(
        self,
        sources: RepositoryFleetOwnerSources,
        *,
        benchmark_resolutions: BenchmarkResolutionRegistry | None = None,
        reproduction_capabilities: ReproductionCapabilitySelectionRegistry | None = None,
    ) -> None:
        if type(sources) is not RepositoryFleetOwnerSources:
            raise TypeError(
                "repository fleet materializer requires RepositoryFleetOwnerSources"
            )
        if (
            benchmark_resolutions is not None
            and type(benchmark_resolutions) is not BenchmarkResolutionRegistry
        ):
            raise TypeError(
                "repository fleet benchmark_resolutions must be BenchmarkResolutionRegistry"
            )
        if (
            reproduction_capabilities is not None
            and type(reproduction_capabilities)
            is not ReproductionCapabilitySelectionRegistry
        ):
            raise TypeError(
                "repository fleet reproduction_capabilities must be typed registry"
            )
        self._sources = sources
        self._benchmark_resolutions = (
            BenchmarkResolutionRegistry()
            if benchmark_resolutions is None
            else benchmark_resolutions
        )
        self._reproduction_capabilities = reproduction_capabilities

    def materialize_prerequisites(self, requirements):
        # Requirement identity is consumed by the caller's staged materialization.
        # This layer contributes only already-proven Benchmark/reproduction closure.
        if not hasattr(requirements, "manifest_digest"):
            raise TypeError("fleet prerequisite requirements must be typed")
        return ReproductionFleetPrerequisiteAuthorities(
            self._benchmark_resolutions,
            self._reproduction_capabilities,
        )

    @staticmethod
    def _lanes_by_program(
        fleet: ReproductionFleetMaterialization,
    ) -> dict[str, object]:
        rows = {lane.program.program_id: lane for lane in fleet.lanes}
        if len(rows) != len(fleet.lanes):
            raise ValueError("materialized fleet program ids must be unique")
        return rows

    def materialize_manifests(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        fleet: ReproductionFleetMaterialization,
    ) -> ResearchProjectManifestRegistry:
        if type(requirements) is not ReproductionFleetOwnerRequirementManifest:
            raise TypeError("fleet manifest materialization requires owner manifest")
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError("fleet manifest materialization requires materialized fleet")
        if requirements.materialization_digest != fleet.materialization_digest:
            raise ValueError("fleet owner requirements belong to another materialization")

        requirement_by_program = {
            row.program_id: row
            for row in requirements.requirements
            if row.stage == "project_manifest"
        }
        if len(requirement_by_program) != len(fleet.lanes):
            raise ValueError(
                "fleet owner requirements do not exactly cover ProjectManifest lanes"
            )

        manifests = []
        seen = set()
        for lane in fleet.lanes:
            study = lane.study
            requirement = requirement_by_program.get(lane.program.program_id)
            if requirement is None:
                raise ValueError("fleet lane has no ProjectManifest requirement")
            expected_key = f"{study.project_id}:{study.study_id}"
            if (
                requirement.requirement_key != expected_key
                or requirement.study_id != study.study_id
                or requirement.package != lane.definition.package
            ):
                raise ValueError("ProjectManifest owner requirement identity drifted")

            manifest = self._sources.portfolio.project(study.project_id)
            # This validates project/study coverage and every Study-selected
            # capability/method/configuration key without choosing a provider.
            resolve_research_requirements(study, manifest)
            if manifest.semantic_digest in seen:
                continue
            seen.add(manifest.semantic_digest)
            manifests.append(manifest)

        return ResearchProjectManifestRegistry(
            tuple(
                sorted(
                    manifests,
                    key=lambda row: (
                        row.project.identity.project_id,
                        row.project.identity.version,
                        row.semantic_digest,
                    ),
                )
            )
        )

    def _binding_registries(
        self,
        fleet: ReproductionFleetMaterialization,
        manifests: ResearchProjectManifestRegistry,
        capability_requirements: ReproductionFleetCapabilityRequirementManifest,
    ) -> tuple[
        ResearchCapabilityBindingRegistry,
        ResearchParticipantBindingRegistry,
        ResearchModelRoleBindingRegistry,
    ]:
        lanes = self._lanes_by_program(fleet)
        expected_capability_keys = {
            (
                row.program_id,
                row.project_manifest_digest,
                row.requirement_key,
                row.requirement_digest,
            )
            for row in capability_requirements.requirements
        }
        actual_capability_keys = set()

        capability_rows = []
        participant_rows = []
        model_rows = []

        for program_id in sorted(lanes):
            lane = lanes[program_id]
            study = lane.study
            manifest = manifests.resolve(study)
            resolution = resolve_research_requirements(study, manifest)
            context = ResearchBindingResolutionContext.create(
                study,
                manifest,
                resolution,
            )

            for requirement in resolution.capability_requirements:
                requirement_digest = canonical_digest(requirement)
                actual_capability_keys.add(
                    (
                        program_id,
                        manifest.semantic_digest,
                        requirement.requirement_id,
                        requirement_digest,
                    )
                )
                resolved = self._sources.capabilities.resolve(
                    requirement,
                    context,
                )
                if type(resolved) is not tuple:
                    raise TypeError(
                        "Capability owner resolver must return immutable tuple"
                    )
                capability_rows.append(
                    ResearchCapabilityBindingRegistration(
                        manifest.semantic_digest,
                        requirement.requirement_id,
                        requirement_digest,
                        resolved,
                    )
                )

            for requirement in study.binding_requirements.participants:
                resolved = self._sources.participants.resolve(
                    requirement,
                    context,
                )
                participant_rows.append(
                    ResearchParticipantBindingRegistration(
                        manifest.semantic_digest,
                        requirement.requirement_digest,
                        resolved,
                    )
                )

            for requirement in study.binding_requirements.model_roles:
                resolved = self._sources.models.resolve(
                    requirement,
                    context,
                )
                if type(resolved) is not tuple:
                    raise TypeError(
                        "Model owner resolver must return immutable tuple"
                    )
                model_rows.append(
                    ResearchModelRoleBindingRegistration(
                        manifest.semantic_digest,
                        requirement.requirement_digest,
                        resolved,
                    )
                )

        if actual_capability_keys != expected_capability_keys:
            raise ValueError(
                "Capability owner worklist does not match materialized Study truth"
            )

        return (
            ResearchCapabilityBindingRegistry(tuple(capability_rows)),
            ResearchParticipantBindingRegistry(tuple(participant_rows)),
            ResearchModelRoleBindingRegistry(tuple(model_rows)),
        )

    def materialize_execution_owners(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        capability_requirements: ReproductionFleetCapabilityRequirementManifest,
        fleet: ReproductionFleetMaterialization,
        manifests: ResearchProjectManifestRegistry,
    ) -> ReproductionFleetOwnerAuthorities:
        if type(requirements) is not ReproductionFleetOwnerRequirementManifest:
            raise TypeError("fleet execution-owner materialization requires owner manifest")
        if (
            type(capability_requirements)
            is not ReproductionFleetCapabilityRequirementManifest
        ):
            raise TypeError(
                "fleet execution-owner materialization requires capability manifest"
            )
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError("fleet execution-owner materialization requires fleet")
        if type(manifests) is not ResearchProjectManifestRegistry:
            raise TypeError("fleet execution-owner materialization requires manifests")
        if (
            requirements.materialization_digest != fleet.materialization_digest
            or capability_requirements.materialization_digest
            != fleet.materialization_digest
            or capability_requirements.project_manifest_registry_digest
            != manifests.identity_digest
        ):
            raise ValueError("fleet execution-owner inputs belong to different cuts")

        capabilities, participants, models = self._binding_registries(
            fleet,
            manifests,
            capability_requirements,
        )
        research_bindings = ResearchBindingAuthority(
            manifests,
            capabilities,
            participants,
            models,
        )

        revision = api.research_os.ResearchGraphRevision(
            fleet.portfolio.portfolio_id,
            fleet.portfolio.portfolio_digest,
            (),
            "repository fleet owner authority materialization",
        )
        graph = compile_research_portfolio_graph(
            revision,
            fleet.portfolio,
        )
        closures = ReproductionFleetExperimentClosureProvider(
            fleet,
            research_bindings,
        )

        trial_rows = []
        reconciliation_rows = []
        for lane in fleet.lanes:
            node = graph.node(lane.program.program_id + "::reproduction")
            try:
                closure = closures.resolve(
                    graph_id=graph.plan.graph_id,
                    graph_digest=graph.plan.graph_digest,
                    research_revision_digest=revision.revision_digest,
                    node=node,
                )
            except Exception:
                # Partial owner materialization is intentional. The canonical
                # fleet authority audit records the exact Research-binding gap
                # for this lane without preventing independent lanes from
                # reaching preflight/execution.
                continue
            try:
                trial = self._sources.trial_providers.resolve(closure)
            except Exception:
                # Missing/unsupported Trial providers remain absent authority;
                # registry.resolve() will surface one precise LookupError during
                # the per-lane audit.
                continue
            trial_rows.append(
                ResearchOSExperimentTrialProviderRegistration(
                    trial.provider_identity,
                    trial.provider,
                    trial.provider_identity_digest,
                    trial.verifier,
                    trial.verifier_identity_digest,
                )
            )
            protocol_digest = closure.research_plan.trial_protocol_identity.digest()
            provider_ids = {
                row.provider_id
                for row in closure.research_plan.experiment_plan.bindings
            }
            if provider_ids != {trial.provider_identity}:
                # An owner that returns a provider inconsistent with the frozen
                # Research binding is not admitted as partial authority.
                continue
            try:
                reconciliation = self._sources.reconciliation.resolve(closure)
            except Exception:
                continue
            reconciliation_rows.append(
                ResearchOSExperimentReconciliationRegistration(
                    trial.provider_identity,
                    protocol_digest,
                    reconciliation,
                )
            )

        trial_registrations = _dedupe_by_key(
            trial_rows,
            key=lambda row: (
                row.provider_identity,
                row.provider.protocol_identity.digest(),
            ),
            digest=lambda row: row.registration_digest,
            label="Trial provider registry",
        )
        reconciliation_registrations = _dedupe_by_key(
            reconciliation_rows,
            key=lambda row: (
                row.provider_identity,
                row.trial_protocol_digest,
            ),
            digest=lambda row: row.registration_digest,
            label="Experiment reconciliation registry",
        )

        return ReproductionFleetOwnerAuthorities(
            research_capabilities=capabilities,
            participants=participants,
            models=models,
            trial_providers=ResearchOSExperimentTrialProviderRegistry(
                trial_registrations
            ),
            reconciliation=ResearchOSExperimentReconciliationRegistry(
                reconciliation_registrations
            ),
        )


__all__ = [
    "RepositoryFleetAuthorityMaterializer",
    "RepositoryFleetOwnerSources",
]
