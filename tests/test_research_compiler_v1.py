from dataclasses import replace

import pytest

from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchBindingRequirements,
    ResearchCapabilityBinding,
    ResearchParticipantBinding,
    ResearchParticipantRequirement,
    ResearchModelRoleRequirement,
    ResearchMethodHost,
    compile_research_plan,
    diff_research_plans,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    FactorLevelSpec,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    ResearchRevision,
    ReplayLevel,
    ResearchStudyDefinition,
    StudyExecutionPolicy,
    StudyFactorSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TrialBudget,
)
from noetrium_platform.foundation.governance.architecture.api import BindingProof, CompositionSubject
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.capabilities.participant.api.project import (
    ParticipantProviderProfile,
    ParticipantRequirement,
    ProjectParticipantBinding,
)
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.foundation.kernel.kernel import Sha256Digest, canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectIdentity,
    ProjectManifest,
    ProjectMethodRequirement,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)

CFG = "c" * 64
EMPTY_CFG = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
def _benchmark(tag: str = "a") -> BenchmarkTaskSet:
    task = TaskDefinition("task-1", "1", "generic", "task.v1", tag * 64)
    return BenchmarkTaskSet("benchmark", "1", "b" * 64, "task.v1", (task,))


def _measurements(schema: str = "trace-v1") -> MeasurementProtocol:
    return MeasurementProtocol(
        "measurements-v2",
        (
            MeasurementDefinition("score", "scalar-v1", MeasurementValueKind.SCALAR),
            MeasurementDefinition("trace", schema, MeasurementValueKind.STRUCTURED),
        ),
    )


def _binding_requirements() -> ResearchBindingRequirements:
    return ResearchBindingRequirements(
        "trial-provider",
        participants=(
            ResearchParticipantRequirement("actor", "actor", "method", "actor"),
            ResearchParticipantRequirement(
                "evaluator", "evaluator", "method", "evaluator", depends_on_roles=("actor",)
            ),
            ResearchParticipantRequirement(
                "critic", "critic", "method", "critic", depends_on_roles=("evaluator",)
            ),
        ),
    )


def _implementation_identity(kind: str, artifact_digit: str = "a") -> ParticipantImplementationIdentity:
    return ParticipantImplementationIdentity(
        kind, f"{kind}-impl", "1", "1", "1", artifact_digit * 64
    )


def _manifest(provider_id: str = "provider-v1", *, artifact_digit: str = "a") -> ProjectManifest:
    requirement = ProjectCapabilityRequirement(
        "trial-provider", "experimentation", "trial", 1, "1" * 64
    )
    return ProjectManifest(
        ProjectSpec(ProjectIdentity("project-1", "1"), "program", "Project"),
        "template-1",
        ProjectToolProvenance("tool", "1", "2" * 64),
        capability_requirements=(requirement,),
        provider_bindings=(
            ProjectProviderBinding(
                "trial-binding", "trial-provider", provider_id, "1", "3" * 64
            ),
        ),
        method_requirements=(
            ProjectMethodRequirement("method", "actor", _implementation_identity("actor", artifact_digit).digest()),
            ProjectMethodRequirement("method", "evaluator", _implementation_identity("evaluator", artifact_digit).digest()),
            ProjectMethodRequirement("method", "critic", _implementation_identity("critic", artifact_digit).digest()),
        ),
        study_ids=("study-1",),
    )


def _project_subject(manifest: ProjectManifest) -> CompositionSubject:
    return CompositionSubject.project_subject(
        manifest.identity.project_id, manifest.identity.version
    )


def _trial_binding(
    manifest: ProjectManifest,
    resolution,
) -> ResearchCapabilityBinding:
    requirement = resolution.capability_requirement("trial-provider")
    provider = manifest.provider_bindings[0]
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
        subject=_project_subject(manifest),
        requirement_digest=Sha256Digest(canonical_digest(requirement)),
        provider_identity=provider.provider_identity,
        provider_profile_digest=Sha256Digest("4" * 64),
        binding_generation="generation-1",
    )
    return ResearchCapabilityBinding("trial-provider", proof)


def _participant_binding(
    manifest: ProjectManifest,
    role: str,
    kind: str,
    *,
    artifact_digit: str = "a",
) -> ResearchParticipantBinding:
    implementation = _implementation_identity(kind, artifact_digit)
    runtime = ParticipantSessionRuntimeIdentity(
        f"runtime.{kind}", "1", "1", "b" * 64
    )
    requirement = ParticipantRequirement(role, implementation, "d" * 64)
    profile = ParticipantProviderProfile(f"participant.{role}", (kind,))
    runtime_binding = ParticipantRuntimeBinding(role, implementation, runtime, "d" * 64)
    domain_binding = ProjectParticipantBinding.from_runtime(
        requirement, profile, runtime_binding
    )
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("participant")),
        subject=_project_subject(manifest),
        requirement_digest=Sha256Digest(domain_binding.requirement_digest),
        provider_identity=profile.provider_id,
        provider_profile_digest=Sha256Digest(profile.digest()),
        binding_generation=f"participant-{runtime.digest()}",
    )
    return ResearchParticipantBinding(role, domain_binding, proof)


def _resolved_binding(
    definition: ResearchStudyDefinition,
    *,
    provider_id: str = "provider-v1",
    participant_kinds: tuple[str, str, str] = ("actor", "evaluator", "critic"),
    artifact_digit: str = "a",
):
    manifest = _manifest(provider_id, artifact_digit=artifact_digit)
    resolution = resolve_research_requirements(definition, manifest)
    roles = ("actor", "evaluator", "critic")
    participants = tuple(
        _participant_binding(manifest, role, kind, artifact_digit=artifact_digit)
        for role, kind in zip(roles, participant_kinds, strict=True)
    )
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        (_trial_binding(manifest, resolution),),
        participants,
    )
    return manifest, resolution, binding

def _definition(
    *,
    measurements: MeasurementProtocol | None = None,
    seeds: tuple[str, ...] = ("seed-a", "seed-b"),
    benchmark: BenchmarkTaskSet | None = None,
    budget: TrialBudget | None = None,
) -> ResearchStudyDefinition:
    factors = (
        StudyFactorSpec(
            "memory",
            (
                FactorLevelSpec("off", False, control=True),
                FactorLevelSpec("on", True),
            ),
        ),
        StudyFactorSpec(
            "model",
            (
                FactorLevelSpec("base", "base", control=True),
                FactorLevelSpec("enhanced", "enhanced"),
            ),
        ),
    )
    return ResearchStudyDefinition(
        "project-1", "experiment-1", "study-1", "workload-1",
        factors, seeds, 2, measurements or _measurements(),
        benchmark or _benchmark(), None, _binding_requirements(),
        ExperimentTrialProtocolIdentity("trial.agent", CFG),
        ResearchRevision("revision-1", "d" * 64),
        StudyExecutionPolicy.serial_shared_v1(
            trial_budget=budget or TrialBudget("standard", max_steps=12, max_seconds=180.0),
            replay_level=ReplayLevel.EXACT,
            repetition_timeout_seconds=3600.0,
        ),
    )


def _compile(
    definition: ResearchStudyDefinition,
    *,
    provider_id: str = "provider-v1",
    artifact_digit: str = "a",
):
    _, resolution, binding = _resolved_binding(
        definition, provider_id=provider_id, artifact_digit=artifact_digit
    )
    return compile_research_plan(definition, resolution, binding)


def test_public_method_host_matches_direct_compiler() -> None:
    definition = _definition()
    manifest, _, binding = _resolved_binding(definition)
    hosted = ResearchMethodHost().compile_method(definition, manifest, binding)
    assert hosted == _compile(definition)


def test_compiler_expands_factor_seed_repetition_task_matrix_and_schedule() -> None:
    plan = _compile(_definition())
    assert len(plan.interventions) == 4
    assert sum(row.control for row in plan.interventions) == 1
    assert len(plan.experiment_plan.assignments) == 16
    assert {row.seed for row in plan.experiment_plan.assignments} == {"seed-a", "seed-b"}
    assert {row.task_id for row in plan.experiment_plan.assignments} == {"task-1"}
    assert plan.protocol.metric_names == ("score",)
    assert plan.participant_schedule.waves == (("actor",), ("evaluator",), ("critic",))
    assert plan.research_semantics.study_plan_digest == plan.experiment_plan.plan_digest
    assert plan.research_semantics.measurement_protocol_digest == plan.measurement_protocol.semantic_digest
    assert plan.research_semantics.participant_schedule.applicable is True
    assert plan.trial_protocol_identity == ExperimentTrialProtocolIdentity("trial.agent", CFG)


def test_compiler_accepts_non_scalar_measurements_without_fake_numeric_metric() -> None:
    measurements = MeasurementProtocol(
        "structured-only",
        (MeasurementDefinition("trajectory", "trajectory-v1", MeasurementValueKind.SEQUENCE),),
    )
    plan = _compile(_definition(measurements=measurements))
    assert plan.protocol.metric_names == ()
    assert len(plan.experiment_plan.assignments) == 16


def test_facet_diff_separates_measurement_seed_and_budget_changes() -> None:
    base = _compile(_definition())
    measurement = _compile(_definition(measurements=_measurements("trace-v2")))
    measurement_diff = diff_research_plans(base, measurement)
    assert "measurement_semantics" in measurement_diff.changed_facets
    assert measurement_diff.scientific_design_changed is True
    assert measurement_diff.measurement_semantics_changed is True
    assert measurement_diff.checkpoint_compatible is True

    seed = _compile(_definition(seeds=("seed-a", "seed-c")))
    seed_diff = diff_research_plans(base, seed)
    assert "assignments" in seed_diff.changed_facets
    assert seed_diff.scientific_design_changed is True
    assert seed_diff.checkpoint_compatible is False

    budget = _compile(
        _definition(budget=TrialBudget("standard", max_steps=24, max_seconds=180.0))
    )
    budget_diff = diff_research_plans(base, budget)
    assert budget_diff.scientific_design_changed is False
    assert budget_diff.execution_plan_changed is True
    assert "execution_policy" in budget_diff.changed_facets


def test_provider_replacement_changes_binding_not_scientific_design() -> None:
    definition = _definition()
    left = _compile(definition, provider_id="provider-v1")
    right = _compile(definition, provider_id="provider-v2")
    diff = diff_research_plans(left, right)
    assert left.scientific_design_digest == right.scientific_design_digest
    assert left.participant_design_digest == right.participant_design_digest
    assert left.binding_requirement_digest == right.binding_requirement_digest
    assert left.binding_digest != right.binding_digest
    assert diff.scientific_design_changed is False
    assert diff.binding_changed is True
    assert "provider_binding" in diff.changed_facets


def test_requirement_resolution_and_binding_drift_fail_closed() -> None:
    definition = _definition()
    manifest, resolution, binding = _resolved_binding(definition)

    wrong_subject = CompositionSubject.project_subject("other-project", "1")
    bad_proof = replace(binding.capability_bindings[0].proof, subject=wrong_subject)
    bad_capability = replace(binding.capability_bindings[0], proof=bad_proof)
    with pytest.raises(ValueError, match="another project subject"):
        compile_research_plan(
            definition, resolution, replace(binding, capability_bindings=(bad_capability,))
        )

    wrong_provider = replace(
        binding.capability_bindings[0].proof, provider_identity="provider-other"
    )
    with pytest.raises(ValueError, match="provider selection"):
        compile_research_plan(
            definition, resolution,
            replace(binding, capability_bindings=(replace(binding.capability_bindings[0], proof=wrong_provider),)),
        )

def test_compiler_is_deterministic_for_identical_author_definition_and_binding() -> None:
    definition = _definition()
    left = _compile(definition)
    right = _compile(definition)
    assert left.research_plan_digest == right.research_plan_digest
    assert left.experiment_plan.plan_digest == right.experiment_plan.plan_digest
    assert left.research_semantics == right.research_semantics


def test_benchmark_split_order_is_execution_order_and_changes_assignment_projection() -> None:
    tasks = (
        TaskDefinition("task-a", "1", "generic", "task.v1", "1" * 64),
        TaskDefinition("task-b", "1", "generic", "task.v1", "2" * 64),
    )
    forward = BenchmarkTaskSet("benchmark", "1", "3" * 64, "task.v1", tasks, splits=(TaskSetSplit("train", ("task-a", "task-b")),))
    reverse = BenchmarkTaskSet("benchmark", "1", "3" * 64, "task.v1", tasks, splits=(TaskSetSplit("train", ("task-b", "task-a")),))
    left = _compile(replace(_definition(benchmark=forward), benchmark_split_id="train"))
    right = _compile(replace(_definition(benchmark=reverse), benchmark_split_id="train"))
    assert [row.task_id for row in left.experiment_plan.assignments[:2]] != [row.task_id for row in right.experiment_plan.assignments[:2]]
    assert left.experiment_plan.assignment_digest != right.experiment_plan.assignment_digest


def test_exactly_one_trial_requirement_rejects_multiple_proofs() -> None:
    definition = _definition()
    _, resolution, binding = _resolved_binding(definition)
    first = binding.capability_bindings[0]
    second = ResearchCapabilityBinding(
        first.requirement_id, replace(first.proof, binding_generation="generation-2")
    )
    with pytest.raises(ValueError, match="exactly-one capability"):
        compile_research_plan(
            definition, resolution,
            replace(binding, capability_bindings=(first, second)),
        )

def test_non_generation_model_binding_is_proof_backed_without_fake_prompt() -> None:
    from noetrium_platform.research.experimentation.api import ResearchModelRoleBinding
    from noetrium_platform.capabilities.model.api.project import (
        ModelCapabilityRequirement, ModelProviderProfile, ProjectModelBinding,
    )
    from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity

    base = _definition()
    definition = replace(
        base,
        binding_requirements=ResearchBindingRequirements(
            "trial-provider",
            participants=base.binding_requirements.participants,
            model_roles=(ResearchModelRoleRequirement("embedding", "model"),),
        ),
    )
    trial_requirement = ProjectCapabilityRequirement(
        "trial-provider", "experimentation", "trial", 1, "1" * 64
    )
    model_requirement = ProjectCapabilityRequirement(
        "model", "model", "embedding", 1, "2" * 64
    )
    manifest = ProjectManifest(
        ProjectSpec(ProjectIdentity("project-1", "1"), "program", "Project"),
        "template-1", ProjectToolProvenance("tool", "1", "3" * 64),
        capability_requirements=(trial_requirement, model_requirement),
        provider_bindings=(
            ProjectProviderBinding("trial-binding", "trial-provider", "provider-v1", "1", "4" * 64),
            ProjectProviderBinding("model-binding", "model", "model.provider", "1", "5" * 64),
        ),
        method_requirements=(
            ProjectMethodRequirement("method", "actor", _implementation_identity("actor").digest()),
            ProjectMethodRequirement("method", "evaluator", _implementation_identity("evaluator").digest()),
            ProjectMethodRequirement("method", "critic", _implementation_identity("critic").digest()),
        ),
        study_ids=("study-1",),
    )
    resolution = resolve_research_requirements(definition, manifest)
    participant_bindings = tuple(
        _participant_binding(manifest, role, kind)
        for role, kind in (("actor", "actor"), ("evaluator", "evaluator"), ("critic", "critic"))
    )
    domain_requirement = ModelCapabilityRequirement(
        role="scientist", capability_id="embedding",
        input_schema_id="model.embedding.input.v1", output_schema_id="model.embedding.output.v1",
    )
    profile = ModelProviderProfile("model.provider", ("embedding",))
    model_binding = ProjectModelBinding(
        requirement_digest=domain_requirement.digest(), provider_id=profile.provider_id,
        provider_profile_digest=profile.digest(), role=domain_requirement.role,
        model=ImmutableModelIdentity(
            logical_name="model-a", model_id="model-a", revision="rev-1",
            engine="engine", engine_version="1", dtype="bf16", quantization=None,
            context_length=8192, tokenizer_revision="tok-1",
        ),
        deployment_id="deployment-a", deployment_generation="6" * 64,
        model_stack_digest="7" * 64, qualification_certificate_digest="8" * 64,
        runtime_qualification_digest="9" * 64, host_identity_digest="a" * 64,
        prompt_generation_id=None, prompt_id=None, prompt_digest=None,
        capabilities=profile.capabilities, runtime_canary_evidence_digests=("b" * 64,),
        capability_id="embedding", input_schema_id="model.embedding.input.v1",
        output_schema_id="model.embedding.output.v1",
    )
    subject = _project_subject(manifest)
    model_proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("model")), subject=subject,
        requirement_digest=Sha256Digest(model_binding.requirement_digest),
        provider_identity=model_binding.provider_id,
        provider_profile_digest=Sha256Digest(model_binding.provider_profile_digest),
        binding_generation=f"model-{model_binding.deployment_generation}",
    )
    model_capability_proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
        subject=subject, requirement_digest=Sha256Digest(canonical_digest(model_requirement)),
        provider_identity="model.provider", provider_profile_digest=Sha256Digest("c" * 64),
        binding_generation="generation-2",
    )
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        (_trial_binding(manifest, resolution), ResearchCapabilityBinding("model", model_capability_proof)),
        participant_bindings,
        model_role_bindings=(ResearchModelRoleBinding("model", model_binding, model_proof, "embedding"),),
    )
    plan = compile_research_plan(definition, resolution, binding)
    assert len(plan.experiment.model_roles) == 1
    role = plan.experiment.model_roles[0]
    assert role.role == "embedding"
    assert role.requirement_id == "model"
    assert role.provider_id == "model.provider"
    assert role.model_stack_digest == "7" * 64
    assert role.prompt_generation_id is None
    assert plan.experiment.model_roles_digest == canonical_digest((role.role_digest,))


def test_method_implementation_identity_is_bound_into_plan_and_checkpoint_compatibility() -> None:
    definition = _definition()
    left = _compile(definition, artifact_digit="a")
    right = _compile(definition, artifact_digit="e")
    diff = diff_research_plans(left, right)
    assert left.method_implementation_digest != right.method_implementation_digest
    assert left.research_plan_digest != right.research_plan_digest
    assert left.research_semantics.checkpoint_compatibility_digest != right.research_semantics.checkpoint_compatibility_digest
    assert "method_implementation" in diff.changed_facets
    assert diff.implementation_changed is True
    assert diff.checkpoint_compatible is False


def test_compiler_rejects_manifest_runtime_method_implementation_drift() -> None:
    definition = _definition()
    manifest = _manifest(artifact_digit="e")
    resolution = resolve_research_requirements(definition, manifest)
    participants = tuple(
        _participant_binding(manifest, role, kind, artifact_digit="a")
        for role, kind in (
            ("actor", "actor"),
            ("evaluator", "evaluator"),
            ("critic", "critic"),
        )
    )
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        (_trial_binding(manifest, resolution),),
        participants,
    )
    with pytest.raises(ValueError, match="method implementation"):
        compile_research_plan(definition, resolution, binding)


def test_package_local_task_requirements_join_project_binding_closure() -> None:
    base = _definition()
    package = TaskPackageSpec(
        package_schema_id="benchmark.task-package.v1",
        instruction_digest="1" * 64,
        environment_requirement_id="environment.task",
        verifier_requirement_id="verifier.task",
        verifier_environment_requirement_id="environment.verifier",
    )
    benchmark = replace(
        base.benchmark,
        tasks=(replace(base.benchmark.tasks[0], package=package),),
    )
    definition = replace(base, benchmark=benchmark)
    manifest = _manifest()
    manifest = replace(
        manifest,
        capability_requirements=manifest.capability_requirements
        + (
            ProjectCapabilityRequirement(
                "environment.task", "environment", "session", 1, "6" * 64
            ),
            ProjectCapabilityRequirement(
                "verifier.task", "experimentation", "verifier", 1, "7" * 64
            ),
            ProjectCapabilityRequirement(
                "environment.verifier", "environment", "session", 1, "8" * 64
            ),
        ),
    )
    resolution = resolve_research_requirements(definition, manifest)
    assert set(resolution.capability_requirement_ids) == {
        "trial-provider",
        "environment.task",
        "verifier.task",
        "environment.verifier",
    }


def test_package_local_task_requirement_missing_from_project_fails_closed() -> None:
    base = _definition()
    package = TaskPackageSpec(
        package_schema_id="benchmark.task-package.v1",
        instruction_digest="1" * 64,
        verifier_requirement_id="verifier.missing",
    )
    definition = replace(
        base,
        benchmark=replace(
            base.benchmark,
            tasks=(replace(base.benchmark.tasks[0], package=package),),
        ),
    )
    with pytest.raises(ValueError, match="verifier.missing"):
        resolve_research_requirements(definition, _manifest())
