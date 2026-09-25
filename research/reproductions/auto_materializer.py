"""Built-in zero-configuration owner authority materializer.

This module derives internal ProjectManifest IR from already-frozen Study and
ResearchProgram objects.  It never asks the user to repeat research declarations.
Only platform-owned generic capabilities are auto-bound.  Missing external model,
environment, benchmark-verifier or paper-era assets remain proof-backed blocking
diagnostics so unrelated lanes may continue.
"""
from __future__ import annotations

from dataclasses import dataclass

from noetrium import api
from noetrium_platform.composition.research_binding_authority import (
    ResearchCapabilityBindingRegistration,
    ResearchCapabilityBindingRegistry,
    ResearchModelRoleBindingRegistration,
    ResearchModelRoleBindingRegistry,
    ResearchParticipantBindingRegistration,
    ResearchParticipantBindingRegistry,
    ResearchProjectManifestRegistry,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentAggregationRegistry,
    ResearchOSExperimentReconciliationRegistry,
)
from noetrium_platform.composition.research_os_experiment_trial_execution import (
    ResearchOSExperimentTrialProviderRegistry,
)
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingRemediationCategory,
    BindingResolution,
    CompositionSubject,
)
from noetrium_platform.foundation.kernel.kernel import (
    Sha256Digest,
    canonical_digest,
)
from noetrium_platform.foundation.governance.system_registry.api import (
    SystemIdentity,
)
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectConfigurationReference,
    ProjectIdentity,
    ProjectManifest,
    ProjectMethodRequirement,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)
from noetrium_platform.research.experimentation.api import (
    research_manifest_requirement_keys,
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
from .fleet import ReproductionFleetMaterialization
from .research_os import ReproductionCapabilitySelectionRegistry


_AUTO_TRIAL_PROVIDER = "noetrium.auto.workload"
_AUTO_PROVIDER_VERSION = "1"


def _requirement_parts(requirement_id: str) -> tuple[str, str]:
    if "." in requirement_id:
        namespace, name = requirement_id.split(".", 1)
        return namespace, name
    return "research", requirement_id


def _capability_requirement(
    requirement_id: str,
    *,
    program_digest: str,
) -> ProjectCapabilityRequirement:
    namespace, name = _requirement_parts(requirement_id)
    return ProjectCapabilityRequirement(
        requirement_id,
        namespace,
        name,
        1,
        canonical_digest(
            {
                "schema": "noetrium.auto-capability-requirement.v1",
                "requirement_id": requirement_id,
                "program_digest": program_digest,
            }
        ),
    )


def _method_program_digests(lane) -> dict[str, str]:
    rows: dict[str, str] = {}
    for definition in lane.program.definitions:
        if definition.kind is not api.ResearchDefinitionKind.METHOD:
            continue
        implementation = definition.implementation
        program_digest = getattr(implementation, "program_digest", None)
        if type(program_digest) is not str or len(program_digest) != 64:
            continue
        method_id = None
        try:
            from noetrium_platform.composition.research_os_lowering import (
                resolve_method_program_implementation,
            )

            resolved = resolve_method_program_implementation(definition)
            method_id = resolved.program.identity.method.method_id
        except BaseException:
            pass
        if isinstance(method_id, str) and method_id:
            rows[method_id] = program_digest
    return rows


def _auto_manifest(lane) -> ProjectManifest:
    study = lane.study
    keys = research_manifest_requirement_keys(study)
    program_digest = lane.program.program_digest
    method_programs = _method_program_digests(lane)
    capabilities = tuple(
        _capability_requirement(row, program_digest=program_digest)
        for row in keys.capability_requirement_ids
    )
    provider_bindings = ()
    trial_requirement = study.binding_requirements.trial_provider_requirement_id
    if trial_requirement in keys.capability_requirement_ids:
        provider_bindings = (
            ProjectProviderBinding(
                "auto.trial",
                trial_requirement,
                _AUTO_TRIAL_PROVIDER,
                _AUTO_PROVIDER_VERSION,
                canonical_digest(
                    {
                        "schema": "noetrium.auto-trial-provider-binding.v1",
                        "program_digest": program_digest,
                        "study_digest": study.definition_digest,
                    }
                ),
            ),
        )
    methods = tuple(
        ProjectMethodRequirement(
            method_id,
            treatment_id,
            method_programs.get(
                method_id,
                canonical_digest(
                    {
                        "schema": "noetrium.unresolved-method-requirement.v1",
                        "program_digest": program_digest,
                        "method_id": method_id,
                        "treatment_id": treatment_id,
                    }
                ),
            ),
        )
        for method_id, treatment_id in keys.method_requirement_keys
    )
    configurations = tuple(
        ProjectConfigurationReference(
            config_id,
            (
                "research-program://"
                + program_digest
                + "/configuration/"
                + config_id
            ),
            canonical_digest(
                {
                    "schema": "noetrium.embedded-program-configuration.v1",
                    "program_digest": program_digest,
                    "configuration_id": config_id,
                }
            ),
        )
        for config_id in keys.configuration_ref_ids
    )
    version = "auto-" + program_digest[:16]
    return ProjectManifest(
        ProjectSpec(
            ProjectIdentity(study.project_id, version),
            lane.program.program_id,
            study.project_id,
        ),
        "auto-runtime-v1",
        ProjectToolProvenance(
            "noetrium",
            "0.44.0",
            canonical_digest(
                {
                    "schema": "noetrium.auto-project-manifest.v1",
                    "program_digest": program_digest,
                }
            ),
        ),
        capability_requirements=capabilities,
        provider_bindings=provider_bindings,
        method_requirements=methods,
        configuration_refs=configurations,
        study_ids=(study.study_id,),
    )


def _diagnostic(
    *,
    owner: str,
    subject: CompositionSubject,
    requirement_digest: str,
    code: str,
    summary: str,
    provider_identity: str | None = None,
) -> BindingResolution:
    return BindingResolution.diagnosed(
        (
            BindingDiagnostic(
                code=BindingDiagnosticCode(code),
                severity=BindingDiagnosticSeverity.ERROR,
                blocking=True,
                owner=CompositionSubject.system_subject(SystemIdentity(owner)),
                subject=subject,
                requirement_digest=Sha256Digest(requirement_digest),
                summary=summary,
                provider_identity=provider_identity,
                remediation=BindingRemediationCategory.OWNER_ACTION,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class AutoRepositoryFleetAuthorityMaterializer:
    """Built-in materializer used when no operator override is supplied."""

    context: object

    def materialize_prerequisites(self, requirements):
        if not hasattr(requirements, "manifest_digest"):
            raise TypeError("auto fleet prerequisite requirements must be typed")
        return ReproductionFleetPrerequisiteAuthorities(
            BenchmarkResolutionRegistry(),
            None,
        )

    def materialize_manifests(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        fleet: ReproductionFleetMaterialization,
    ) -> ResearchProjectManifestRegistry:
        if type(requirements) is not ReproductionFleetOwnerRequirementManifest:
            raise TypeError("auto fleet manifest requirements must be typed")
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError("auto fleet manifest materialization requires fleet")
        manifests = tuple(_auto_manifest(lane) for lane in fleet.lanes)
        return ResearchProjectManifestRegistry(manifests)

    def materialize_execution_owners(
        self,
        requirements: ReproductionFleetOwnerRequirementManifest,
        capability_requirements: ReproductionFleetCapabilityRequirementManifest,
        fleet: ReproductionFleetMaterialization,
        manifests: ResearchProjectManifestRegistry,
    ) -> ReproductionFleetOwnerAuthorities:
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError("auto fleet execution owners require fleet")
        capability_rows = []
        participant_rows = []
        model_rows = []

        for lane in fleet.lanes:
            study = lane.study
            manifest = manifests.resolve(study)
            resolution = resolve_research_requirements(study, manifest)
            subject = resolution.project_subject
            trial_id = study.binding_requirements.trial_provider_requirement_id

            for requirement in resolution.capability_requirements:
                requirement_digest = canonical_digest(requirement)
                if requirement.requirement_id == trial_id:
                    profile_digest = canonical_digest(
                        {
                            "schema": "noetrium.auto-workload-trial-provider.v1",
                            "provider": _AUTO_TRIAL_PROVIDER,
                        }
                    )
                    proof = BindingProof(
                        owner=CompositionSubject.system_subject(
                            SystemIdentity("experimentation")
                        ),
                        subject=subject,
                        requirement_digest=Sha256Digest(requirement_digest),
                        provider_identity=_AUTO_TRIAL_PROVIDER,
                        provider_profile_digest=Sha256Digest(profile_digest),
                        binding_generation=(
                            "auto-trial-" + study.definition_digest[:16]
                        ),
                    )
                    resolved = (
                        BindingResolution.bound(
                            {"provider": _AUTO_TRIAL_PROVIDER},
                            proof,
                        ),
                    )
                else:
                    resolved = (
                        _diagnostic(
                            owner=requirement.namespace,
                            subject=subject,
                            requirement_digest=requirement_digest,
                            code="runtime.provider_unavailable",
                            summary=(
                                "no qualified runtime provider is currently "
                                f"available for {requirement.requirement_id}"
                            ),
                        ),
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
                participant_rows.append(
                    ResearchParticipantBindingRegistration(
                        manifest.semantic_digest,
                        requirement.requirement_digest,
                        _diagnostic(
                            owner="participant",
                            subject=subject,
                            requirement_digest=requirement.requirement_digest,
                            code="participant.runtime_unavailable",
                            summary=(
                                "automatic participant runtime binding is not "
                                "closed for this lane"
                            ),
                        ),
                    )
                )

            for requirement in study.binding_requirements.model_roles:
                model_rows.append(
                    ResearchModelRoleBindingRegistration(
                        manifest.semantic_digest,
                        requirement.requirement_digest,
                        (
                            _diagnostic(
                                owner="model",
                                subject=subject,
                                requirement_digest=requirement.requirement_digest,
                                code="model.qualified_binding_unavailable",
                                summary=(
                                    "no qualified model deployment currently "
                                    f"satisfies role {requirement.role}"
                                ),
                            ),
                        ),
                    )
                )

        return ReproductionFleetOwnerAuthorities(
            research_capabilities=ResearchCapabilityBindingRegistry(
                tuple(capability_rows)
            ),
            participants=ResearchParticipantBindingRegistry(
                tuple(participant_rows)
            ),
            models=ResearchModelRoleBindingRegistry(tuple(model_rows)),
            trial_providers=ResearchOSExperimentTrialProviderRegistry(()),
            reconciliation=ResearchOSExperimentReconciliationRegistry(()),
            aggregation=ResearchOSExperimentAggregationRegistry.canonical(),
        )


def build_auto_repository_fleet_authority_materializer(context):
    return AutoRepositoryFleetAuthorityMaterializer(context)


__all__ = [
    "AutoRepositoryFleetAuthorityMaterializer",
    "build_auto_repository_fleet_authority_materializer",
]
