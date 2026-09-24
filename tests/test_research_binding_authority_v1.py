from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.api import ProjectModelBinding
from noetrium_platform.capabilities.participant.api import (
    ParticipantProviderProfile,
    ParticipantRequirement,
    ProjectParticipantBinding,
)
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthority,
    ResearchBindingAuthorityError,
    ResearchBindingRequirementMissing,
    ResearchBindingResolutionContext,
    ResearchCapabilityBindingRegistration,
    ResearchCapabilityBindingRegistry,
    ResearchModelRoleBindingRegistration,
    ResearchModelRoleBindingRegistry,
    ResearchParticipantBindingRegistration,
    ResearchParticipantBindingRegistry,
    ResearchProjectManifestRegistry,
    ResearchProjectManifestRequirement,
)
from noetrium_platform.foundation.governance.architecture.api import (
    BindingDiagnostic,
    BindingDiagnosticCode,
    BindingDiagnosticSeverity,
    BindingProof,
    BindingResolution,
    CompositionSubject,
)
from noetrium_platform.foundation.governance.system_registry.api import (
    SystemIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
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
    ResearchManifestRequirementsUnresolved,
    resolve_research_requirements,
)
from research.reproductions.fleet import _research_binding_gap
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TaskDefinition,
    TrialBudget,
)


_IMPLEMENTATION = ParticipantImplementationIdentity(
    "method",
    "demo-method",
    "1",
    "1",
    "1",
    "1" * 64,
)
_RUNTIME = ParticipantSessionRuntimeIdentity(
    "demo-runtime",
    "1",
    "1",
    "2" * 64,
)


def _definition():
    benchmark = BenchmarkTaskSet(
        "demo-benchmark",
        "1",
        "3" * 64,
        "demo.task.v1",
        (
            TaskDefinition(
                "task-1",
                "1",
                "demo",
                "demo.task.v1",
                "4" * 64,
            ),
        ),
    )
    return Study(
        project_id="demo-project",
        study_id="demo-study",
        benchmark=benchmark,
        method=StudyParticipant(
            role="agent",
            kind="method",
            implementation="demo-method",
            treatment="full",
        ),
        models={
            "solver": StudyModel(
                "model.generate",
                prompt="prompt.solver",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "score",
                schema_id="measurement.score.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="continuous",
                domain="demo",
            ),
        ),
        trial=ExperimentTrialProtocolIdentity("demo.trial", "5" * 64),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget("demo-budget", max_steps=8, max_seconds=60.0),
        trial_provider_requirement_id="trial.provider",
    ).build()


def _manifest() -> ProjectManifest:
    return ProjectManifest(
        ProjectSpec(
            ProjectIdentity("demo-project", "1"),
            "demo-program",
            "Demo Project",
        ),
        "template-1",
        ProjectToolProvenance("noetrium", "1", "6" * 64),
        capability_requirements=(
            ProjectCapabilityRequirement(
                "trial.provider",
                "experimentation",
                "trial",
                1,
                "7" * 64,
            ),
            ProjectCapabilityRequirement(
                "model.generate",
                "model",
                "generation",
                1,
                "8" * 64,
            ),
        ),
        provider_bindings=(
            ProjectProviderBinding(
                "trial-binding",
                "trial.provider",
                "trial.provider",
                "1",
                "9" * 64,
            ),
            ProjectProviderBinding(
                "model-binding",
                "model.generate",
                "model.provider",
                "1",
                "a" * 64,
            ),
        ),
        method_requirements=(
            ProjectMethodRequirement(
                "demo-method",
                "full",
                _IMPLEMENTATION.digest(),
            ),
        ),
        configuration_refs=(
            ProjectConfigurationReference(
                "prompt.solver",
                "artifact://prompt/solver",
                "b" * 64,
            ),
        ),
        study_ids=("demo-study",),
    )


class _Manifests:
    def resolve(self, definition):
        assert definition.project_id == "demo-project"
        return _manifest()


class _Capabilities:
    def resolve(self, requirement, context):
        provider = {
            "trial.provider": "trial.provider",
            "model.generate": "model.provider",
        }[requirement.requirement_id]
        proof = BindingProof(
            owner=CompositionSubject.system_subject(
                SystemIdentity("experimentation")
            ),
            subject=context.resolution.project_subject,
            requirement_digest=Sha256Digest(canonical_digest(requirement)),
            provider_identity=provider,
            provider_profile_digest=Sha256Digest("c" * 64),
            binding_generation=f"capability-{requirement.requirement_id}",
        )
        return (BindingResolution.bound(object(), proof),)


class _Participants:
    def resolve(self, requirement, context):
        assert requirement.role == "agent"
        domain_requirement = ParticipantRequirement(
            requirement.role,
            _IMPLEMENTATION,
        )
        profile = ParticipantProviderProfile(
            "participant.provider",
            ("method",),
        )
        runtime_binding = ParticipantRuntimeBinding(
            requirement.role,
            _IMPLEMENTATION,
            _RUNTIME,
        )
        binding = ProjectParticipantBinding.from_runtime(
            domain_requirement,
            profile,
            runtime_binding,
        )
        proof = BindingProof(
            owner=CompositionSubject.system_subject(SystemIdentity("participant")),
            subject=context.resolution.project_subject,
            requirement_digest=Sha256Digest(binding.requirement_digest),
            provider_identity=profile.provider_id,
            provider_profile_digest=Sha256Digest(profile.digest()),
            binding_generation=f"participant-{_RUNTIME.digest()}",
        )
        return BindingResolution.bound(binding, proof)


class _Models:
    def resolve(self, requirement, context):
        assert requirement.role == "solver"
        binding = ProjectModelBinding(
            requirement_digest="d" * 64,
            provider_id="model.provider",
            provider_profile_digest="e" * 64,
            role="solver",
            model=ImmutableModelIdentity(
                logical_name="demo-model",
                model_id="demo-model",
                revision="revision-1",
                engine="test",
                engine_version="1",
                dtype="bf16",
                quantization=None,
                context_length=8192,
                tokenizer_revision="tokenizer-1",
            ),
            deployment_id="demo-deployment",
            deployment_generation="f" * 64,
            model_stack_digest="1" * 64,
            qualification_certificate_digest="2" * 64,
            runtime_qualification_digest="3" * 64,
            host_identity_digest="4" * 64,
            prompt_generation_id="prompt-generation-1",
            prompt_id="prompt.solver",
            prompt_digest="5" * 64,
            capabilities=("generation",),
            runtime_canary_evidence_digests=("6" * 64,),
            request_tokenization_digest="7" * 64,
        )
        proof = BindingProof(
            owner=CompositionSubject.system_subject(SystemIdentity("model")),
            subject=context.resolution.project_subject,
            requirement_digest=Sha256Digest(binding.requirement_digest),
            provider_identity=binding.provider_id,
            provider_profile_digest=Sha256Digest(
                binding.provider_profile_digest
            ),
            binding_generation=f"model-{binding.deployment_generation}",
        )
        return (BindingResolution.bound(binding, proof),)


def test_research_binding_authority_closes_trial_participant_and_model() -> None:
    authority = ResearchBindingAuthority(
        _Manifests(),
        _Capabilities(),
        _Participants(),
        _Models(),
    )
    definition = _definition()

    resolution, contribution = authority.resolve(definition)

    assert resolution.project_manifest_digest == _manifest().semantic_digest
    assert tuple(
        row.requirement_id for row in contribution.capability_bindings
    ) == ("trial.provider", "model.generate")
    assert tuple(
        row.role for row in contribution.participant_bindings
    ) == ("agent",)
    assert tuple(
        row.role for row in contribution.model_role_bindings
    ) == ("solver",)
    assert len(contribution.contribution_digest) == 64


class _UnavailableModels(_Models):
    def resolve(self, requirement, context):
        diagnostic = BindingDiagnostic(
            code=BindingDiagnosticCode("model.unavailable"),
            severity=BindingDiagnosticSeverity.ERROR,
            blocking=True,
            owner=CompositionSubject.system_subject(SystemIdentity("model")),
            subject=context.resolution.project_subject,
            requirement_digest=Sha256Digest("8" * 64),
            summary="qualified model is unavailable",
            provider_identity="model.provider",
        )
        return (BindingResolution.diagnosed((diagnostic,)),)


def test_research_binding_authority_preserves_blocking_owner_diagnostics() -> None:
    authority = ResearchBindingAuthority(
        _Manifests(),
        _Capabilities(),
        _Participants(),
        _UnavailableModels(),
    )

    with pytest.raises(ResearchBindingAuthorityError) as captured:
        authority.resolve(_definition())

    error = captured.value
    assert error.stage == "model"
    assert error.requirement_id == "solver"
    assert tuple(row.code.value for row in error.diagnostics) == (
        "model.unavailable",
    )
    assert len(error.error_digest) == 64



def test_project_manifest_registry_resolves_exact_study_coverage() -> None:
    registry = ResearchProjectManifestRegistry((_manifest(),))
    resolved = registry.resolve(_definition())
    assert resolved == _manifest()
    assert len(registry.identity_digest) == 64


def test_project_manifest_registry_rejects_ambiguous_project_study_versions() -> None:
    first = _manifest()
    second = ProjectManifest(
        ProjectSpec(
            ProjectIdentity("demo-project", "2"),
            "demo-program",
            "Demo Project",
        ),
        first.template_revision,
        first.provenance,
        first.capability_requirements,
        first.provider_bindings,
        first.method_requirements,
        first.configuration_refs,
        first.study_ids,
    )
    with pytest.raises(ValueError, match="ambiguous Study coverage"):
        ResearchProjectManifestRegistry((first, second))



def test_binding_registries_close_study_without_custom_resolver_logic() -> None:
    definition = _definition()
    manifest = _manifest()
    requirement_resolution = resolve_research_requirements(
        definition,
        manifest,
    )
    context = ResearchBindingResolutionContext.create(
        definition,
        manifest,
        requirement_resolution,
    )

    capability_owner = _Capabilities()
    capability_registry = ResearchCapabilityBindingRegistry(
        tuple(
            ResearchCapabilityBindingRegistration(
                manifest.semantic_digest,
                requirement.requirement_id,
                canonical_digest(requirement),
                capability_owner.resolve(requirement, context),
            )
            for requirement in requirement_resolution.capability_requirements
        )
    )

    participant_owner = _Participants()
    participant_registry = ResearchParticipantBindingRegistry(
        tuple(
            ResearchParticipantBindingRegistration(
                manifest.semantic_digest,
                requirement.requirement_digest,
                participant_owner.resolve(requirement, context),
            )
            for requirement in definition.binding_requirements.participants
        )
    )

    model_owner = _Models()
    model_registry = ResearchModelRoleBindingRegistry(
        tuple(
            ResearchModelRoleBindingRegistration(
                manifest.semantic_digest,
                requirement.requirement_digest,
                model_owner.resolve(requirement, context),
            )
            for requirement in definition.binding_requirements.model_roles
        )
    )

    authority = ResearchBindingAuthority(
        ResearchProjectManifestRegistry((manifest,)),
        capability_registry,
        participant_registry,
        model_registry,
    )
    resolved, contribution = authority.resolve(definition)

    assert resolved.resolution_digest == requirement_resolution.resolution_digest
    assert tuple(
        row.requirement_id for row in contribution.capability_bindings
    ) == ("trial.provider", "model.generate")
    assert tuple(
        row.role for row in contribution.participant_bindings
    ) == ("agent",)
    assert tuple(
        row.role for row in contribution.model_role_bindings
    ) == ("solver",)
    assert len(capability_registry.identity_digest) == 64
    assert len(participant_registry.identity_digest) == 64
    assert len(model_registry.identity_digest) == 64



def test_fleet_gap_classifies_missing_manifest_by_canonical_requirement() -> None:
    definition = _definition()
    requirement = ResearchProjectManifestRequirement.from_study(definition)
    unrelated = ProjectManifest(
        ProjectSpec(
            ProjectIdentity("other-project", "1"),
            "demo-program",
            "Other Project",
        ),
        "template-1",
        ProjectToolProvenance("noetrium", "1", "6" * 64),
        study_ids=("other-study",),
    )
    registry = ResearchProjectManifestRegistry((unrelated,))
    with pytest.raises(ResearchBindingRequirementMissing) as captured:
        registry.resolve(definition)

    gap = _research_binding_gap(definition, captured.value)

    assert gap.stage == "project_manifest"
    assert gap.requirement_key == "demo-project:demo-study"
    assert gap.requirement_digest == requirement.requirement_digest
    assert gap.error_type == "ResearchBindingRequirementMissing"
    assert len(gap.gap_digest) == 64


def test_fleet_gap_preserves_structured_model_owner_diagnostics() -> None:
    authority = ResearchBindingAuthority(
        _Manifests(),
        _Capabilities(),
        _Participants(),
        _UnavailableModels(),
    )
    definition = _definition()
    with pytest.raises(ResearchBindingAuthorityError) as captured:
        authority.resolve(definition)

    gap = _research_binding_gap(definition, captured.value)
    model_requirement = definition.binding_requirements.model_role("solver")

    assert gap.stage == "model"
    assert gap.requirement_key == "solver"
    assert gap.requirement_digest == model_requirement.requirement_digest
    assert gap.error_type == "ResearchBindingAuthorityError"
    assert gap.diagnostics == tuple(
        row.machine_digest for row in captured.value.diagnostics
    )
    assert len(gap.gap_digest) == 64



def test_incomplete_project_manifest_raises_typed_coverage_error() -> None:
    definition = _definition()
    complete = _manifest()
    incomplete = ProjectManifest(
        complete.project,
        complete.template_revision,
        complete.provenance,
        capability_requirements=(
            complete.capability_requirements[0],
        ),
        provider_bindings=(
            complete.provider_bindings[0],
        ),
        method_requirements=complete.method_requirements,
        configuration_refs=complete.configuration_refs,
        study_ids=complete.study_ids,
    )

    with pytest.raises(ResearchManifestRequirementsUnresolved) as captured:
        resolve_research_requirements(definition, incomplete)

    error = captured.value
    assert error.missing_capability_requirement_ids == ("model.generate",)
    assert error.missing_method_requirement_keys == ()
    assert error.missing_configuration_ref_ids == ()
    assert len(error.keys.keys_digest) == 64
    assert len(error.error_digest) == 64

    gap = _research_binding_gap(definition, error)
    requirement = ResearchProjectManifestRequirement.from_study(definition)
    assert gap.stage == "project_manifest"
    assert gap.requirement_digest == requirement.requirement_digest


def test_missing_capability_registry_is_not_misclassified_as_manifest() -> None:
    definition = _definition()
    manifest = _manifest()
    resolution = resolve_research_requirements(definition, manifest)
    context = ResearchBindingResolutionContext.create(
        definition,
        manifest,
        resolution,
    )
    requirement = resolution.capability_requirements[0]
    registry = ResearchCapabilityBindingRegistry(())

    with pytest.raises(ResearchBindingRequirementMissing) as captured:
        registry.resolve(requirement, context)

    gap = _research_binding_gap(definition, captured.value)
    assert gap.stage == "capability"
    assert gap.requirement_key == requirement.requirement_id
    assert gap.requirement_digest == canonical_digest(requirement)
    assert len(gap.gap_digest) == 64
