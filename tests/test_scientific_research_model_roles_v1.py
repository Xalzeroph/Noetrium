from __future__ import annotations

from noetrium_platform.capabilities.model.api.project import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelBinding,
)
from noetrium_platform.foundation.governance.architecture.api import BindingProof, CompositionSubject
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, Sha256Digest, canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectIdentity,
    ProjectManifest,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)
from noetrium_platform.research.experimentation.binding import (
    ResearchBindingContribution,
    ResearchBindingRequirements,
    ResearchCapabilityBinding,
    ResearchModelRoleBinding,
    ResearchModelRoleRequirement,
)
from noetrium_platform.research.experimentation.api import (
    compile_research_plan,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    ReplayLevel,
    ResearchStudyDefinition,
    StudyExecutionPolicy,
    TaskDefinition,
    TrialBudget,
)


def _definition() -> ResearchStudyDefinition:
    benchmark = BenchmarkTaskSet(
        "benchmark", "1", "b" * 64, "task.v1",
        (TaskDefinition("task-1", "1", "generic", "task.v1", "a" * 64),),
    )
    requirements = ResearchBindingRequirements(
        "trial-provider",
        model_roles=(
            ResearchModelRoleRequirement("action", "model-action"),
            ResearchModelRoleRequirement("reflection", "model-reflection"),
        ),
    )
    return ResearchStudyDefinition(
        "project-1", "experiment-1", "study-1", "workload-1", (), ("seed-1",), 1,
        MeasurementProtocol(
            "metrics", (MeasurementDefinition("score", "scalar-v1", MeasurementValueKind.SCALAR),)
        ),
        benchmark, None, requirements,
        ExperimentTrialProtocolIdentity("trial.agent", "f" * 64),
        None,
        StudyExecutionPolicy.serial_shared_v1(
            trial_budget=TrialBudget("standard", max_steps=10),
            replay_level=ReplayLevel.EXACT,
            repetition_timeout_seconds=3600.0,
        ),
    )


def _manifest() -> ProjectManifest:
    requirements = (
        ProjectCapabilityRequirement("trial-provider", "experimentation", "trial", 1, "1" * 64),
        ProjectCapabilityRequirement("model-action", "model", "generation", 1, "2" * 64),
        ProjectCapabilityRequirement("model-reflection", "model", "generation", 1, "3" * 64),
    )
    return ProjectManifest(
        ProjectSpec(ProjectIdentity("project-1", "1"), "program", "Project"),
        "template-1", ProjectToolProvenance("tool", "1", "4" * 64),
        capability_requirements=requirements,
        provider_bindings=(
            ProjectProviderBinding("trial-binding", "trial-provider", "trial.provider", "1", "5" * 64),
            ProjectProviderBinding("action-binding", "model-action", "model.action", "1", "6" * 64),
            ProjectProviderBinding("reflection-binding", "model-reflection", "model.reflection", "1", "7" * 64),
        ),
        study_ids=("study-1",),
    )


def _subject(manifest: ProjectManifest) -> CompositionSubject:
    return CompositionSubject.project_subject(manifest.identity.project_id, manifest.identity.version)


def _capability_binding(manifest: ProjectManifest, resolution, requirement_id: str, provider_id: str, generation: str) -> ResearchCapabilityBinding:
    requirement = resolution.capability_requirement(requirement_id)
    return ResearchCapabilityBinding(
        requirement_id,
        BindingProof(
            owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
            subject=_subject(manifest),
            requirement_digest=Sha256Digest(canonical_digest(requirement)),
            provider_identity=provider_id,
            provider_profile_digest=Sha256Digest("8" * 64),
            binding_generation=generation,
        ),
    )


def _model_binding(
    manifest: ProjectManifest,
    *,
    role: str,
    requirement_id: str,
    provider_id: str,
    model_id: str,
    stack_digit: str,
    deployment_digit: str,
) -> ResearchModelRoleBinding:
    domain_requirement = ModelCapabilityRequirement(
        role=role,
        capability_id="generation",
        input_schema_id="model.generation.input.v1",
        output_schema_id="model.generation.output.v1",
    )
    profile = ModelProviderProfile(provider_id, ("generation",))
    binding = ProjectModelBinding(
        requirement_digest=domain_requirement.digest(), provider_id=provider_id,
        provider_profile_digest=profile.digest(), role=role,
        model=ImmutableModelIdentity(
            logical_name=model_id, model_id=model_id, revision="rev-1",
            engine="engine", engine_version="1", dtype="bf16", quantization=None,
            context_length=8192, tokenizer_revision="tok-1",
        ),
        deployment_id=f"deployment-{role}", deployment_generation=deployment_digit * 64,
        model_stack_digest=stack_digit * 64, qualification_certificate_digest="9" * 64,
        runtime_qualification_digest="a" * 64, host_identity_digest="b" * 64,
        prompt_generation_id=None, prompt_id=None, prompt_digest=None,
        capabilities=profile.capabilities, runtime_canary_evidence_digests=("c" * 64,),
        capability_id="generation", input_schema_id="model.generation.input.v1",
        output_schema_id="model.generation.output.v1",
    )
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("model")),
        subject=_subject(manifest), requirement_digest=Sha256Digest(binding.requirement_digest),
        provider_identity=binding.provider_id,
        provider_profile_digest=Sha256Digest(binding.provider_profile_digest),
        binding_generation=f"model-{binding.deployment_generation}",
    )
    return ResearchModelRoleBinding(requirement_id, binding, proof, role)


def _compile(*, reflection_model_id: str, reflection_stack_digit: str):
    definition = _definition()
    manifest = _manifest()
    resolution = resolve_research_requirements(definition, manifest)
    capabilities = (
        _capability_binding(manifest, resolution, "trial-provider", "trial.provider", "trial-generation"),
        _capability_binding(manifest, resolution, "model-action", "model.action", "action-generation"),
        _capability_binding(manifest, resolution, "model-reflection", "model.reflection", "reflection-generation"),
    )
    action = _model_binding(
        manifest, role="action", requirement_id="model-action", provider_id="model.action",
        model_id="action-model", stack_digit="d", deployment_digit="1",
    )
    reflection = _model_binding(
        manifest, role="reflection", requirement_id="model-reflection", provider_id="model.reflection",
        model_id=reflection_model_id, stack_digit=reflection_stack_digit, deployment_digit="2",
    )
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        capabilities,
        model_role_bindings=(action, reflection),
    )
    return binding, compile_research_plan(definition, resolution, binding)


def test_named_model_roles_are_part_of_scientific_binding_identity() -> None:
    left_binding, left = _compile(reflection_model_id="reflection-a", reflection_stack_digit="e")
    right_binding, right = _compile(reflection_model_id="reflection-b", reflection_stack_digit="f")
    assert left.experiment.model_roles_digest != right.experiment.model_roles_digest
    assert tuple((row.role, row.model_stack_digest) for row in left.experiment.model_roles) == (
        ("action", "d" * 64),
        ("reflection", "e" * 64),
    )
    assert tuple((row.role, row.model_stack_digest) for row in right.experiment.model_roles) == (
        ("action", "d" * 64),
        ("reflection", "f" * 64),
    )
    assert left.experiment.model_roles_digest == canonical_digest(
        tuple(row.role_digest for row in left.experiment.model_roles)
    )
    assert left_binding.contribution_digest != right_binding.contribution_digest
    assert left.binding_digest != right.binding_digest
    assert left.research_plan_digest != right.research_plan_digest


def test_model_role_order_is_canonical_without_primary_projection() -> None:
    reflection = ResearchModelRoleRequirement("reflection", "model-reflection")
    value = ResearchModelRoleRequirement("value", "model-value")
    left = ResearchBindingRequirements(
        "trial-provider", model_roles=(ResearchModelRoleRequirement("action", "model-action"), value, reflection)
    )
    right = ResearchBindingRequirements(
        "trial-provider", model_roles=(reflection, ResearchModelRoleRequirement("action", "model-action"), value)
    )
    assert left.requirements_digest == right.requirements_digest
    assert tuple(row.role for row in left.model_roles) == ("action", "reflection", "value")
    assert left.model_role("action").requirement_id == "model-action"
