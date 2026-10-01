"""Built-in zero-configuration owner authority materializer.

This module derives internal ProjectManifest IR from already-frozen Study and
ResearchProgram objects.  It never asks the user to repeat research declarations.
Only platform-owned generic capabilities are repository-bound.  Missing external model,
environment, benchmark-verifier or paper-era assets remain proof-backed blocking
diagnostics so unrelated lanes may continue.
"""
from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.composition.research_binding_authority import (
    ResearchCapabilityBindingRegistration,
    ResearchCapabilityBindingRegistry,
    ResearchModelRoleBindingRegistration,
    ResearchModelRoleBindingRegistry,
    ResearchParticipantBindingRegistration,
    ResearchParticipantBindingRegistry,
    ResearchProjectManifestRegistry,
)
from noetrium_platform.composition.research_method_participant_binding import (
    exact_method_programs,
    exact_method_requirement_implementation_digest,
    resolve_exact_method_participant,
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
from noetrium_platform.foundation.governance.system_registry.api import (
    SystemIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    Sha256Digest,
    canonical_digest,
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

from .authority_requirements import (
    ReproductionFleetCapabilityRequirementManifest,
    ReproductionFleetOwnerRequirementManifest,
)
from .benchmark_input_materializer import (
    materialize_repository_benchmark_inputs,
)
from .execution_authority import (
    ReproductionFleetOwnerAuthorities,
    ReproductionFleetPrerequisiteAuthorities,
)
from .fleet import ReproductionFleetMaterialization

_WORKLOAD_TRIAL_PROVIDER = "noetrium.auto.workload"
_PROVIDER_VERSION = "1"


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
                "schema": "noetrium.repository-capability-requirement.v1",
                "requirement_id": requirement_id,
                "program_digest": program_digest,
            }
        ),
    )


def _method_programs(lane) -> dict[str, object]:
    return exact_method_programs(lane.program)


def _method_requirement_implementation_digest(
    study,
    research_program,
    *,
    method_id: str,
    treatment_id: str,
    program_digest: str,
) -> str:
    matches = tuple(
        row
        for row in study.binding_requirements.participants
        if row.method_id == method_id and row.treatment_id == treatment_id
    )
    if len(matches) == 1:
        return exact_method_requirement_implementation_digest(
            research_program,
            matches[0],
        )
    return canonical_digest(
        {
            "schema": "noetrium.unresolved-method-requirement.v1",
            "program_digest": program_digest,
            "method_id": method_id,
            "treatment_id": treatment_id,
        }
    )


def _repository_manifest(lane) -> ProjectManifest:
    study = lane.study
    keys = research_manifest_requirement_keys(study)
    program_digest = lane.program.program_digest
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
                _WORKLOAD_TRIAL_PROVIDER,
                _PROVIDER_VERSION,
                canonical_digest(
                    {
                        "schema": "noetrium.repository-trial-provider-binding.v1",
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
            _method_requirement_implementation_digest(
                study,
                lane.program,
                method_id=method_id,
                treatment_id=treatment_id,
                program_digest=program_digest,
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
    version = "repository-" + program_digest[:16]
    return ProjectManifest(
        ProjectSpec(
            ProjectIdentity(study.project_id, version),
            lane.program.program_id,
            study.project_id,
        ),
        "repository-runtime-v1",
        ProjectToolProvenance(
            "noetrium",
            "0.44.0",
            canonical_digest(
                {
                    "schema": "noetrium.repository-project-manifest.v1",
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
class RepositoryCapabilityOwnerResolver:
    def resolve(self, requirement, context):
        requirement_digest = canonical_digest(requirement)
        trial_id = context.definition.binding_requirements.trial_provider_requirement_id
        if requirement.requirement_id == trial_id:
            profile_digest = canonical_digest({
                "schema": "noetrium.workload-trial-provider.v1",
                "provider": _WORKLOAD_TRIAL_PROVIDER,
            })
            proof = BindingProof(
                owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
                subject=context.resolution.project_subject,
                requirement_digest=Sha256Digest(requirement_digest),
                provider_identity=_WORKLOAD_TRIAL_PROVIDER,
                provider_profile_digest=Sha256Digest(profile_digest),
                binding_generation="workload-trial-" + context.definition.definition_digest[:16],
            )
            return (BindingResolution.bound({"provider": _WORKLOAD_TRIAL_PROVIDER}, proof),)
        return (_diagnostic(
            owner=requirement.namespace,
            subject=context.resolution.project_subject,
            requirement_digest=requirement_digest,
            code="runtime.provider_unavailable",
            summary=f"no qualified runtime provider is available for {requirement.requirement_id}",
        ),)


@dataclass(frozen=True, slots=True)
class RepositoryModelOwnerResolver:
    def resolve(self, requirement, context):
        return (_diagnostic(
            owner="model",
            subject=context.resolution.project_subject,
            requirement_digest=requirement.requirement_digest,
            code="model.qualified_binding_unavailable",
            summary=f"no qualified model deployment satisfies role {requirement.role}",
        ),)

@dataclass(frozen=True, slots=True)
class RepositoryTrialProviderResolver:
    def resolve(self, closure):
        raise LookupError("no workload Trial provider authority has been materialized")


@dataclass(frozen=True, slots=True)
class RepositoryReconciliationResolver:
    def resolve(self, closure):
        raise LookupError("no reconciliation authority has been materialized")


def build_repository_fleet_authority_materializer(context):
    from .owner_materializer import (
        RepositoryFleetAuthorityMaterializer,
        RepositoryFleetOwnerSources,
    )
    sources = RepositoryFleetOwnerSources(
        manifest_factory=_repository_manifest,
        capabilities=RepositoryCapabilityOwnerResolver(),
        models=RepositoryModelOwnerResolver(),
        trial_providers=RepositoryTrialProviderResolver(),
        reconciliation=RepositoryReconciliationResolver(),
    )
    return RepositoryFleetAuthorityMaterializer(
        sources,
        benchmark_resolutions=materialize_repository_benchmark_inputs(
            context.authority_inputs,
            content=context.content,
        ),
    )


__all__ = [
    "RepositoryCapabilityOwnerResolver",
    "RepositoryModelOwnerResolver",
    "RepositoryReconciliationResolver",
    "RepositoryTrialProviderResolver",
    "build_repository_fleet_authority_materializer",
]
