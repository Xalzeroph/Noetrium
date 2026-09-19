"""Side-effect-free compiler from author research facts to typed run facets."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentModelRoleSpec,
    ExperimentParticipantSpec,
    ExperimentParticipantTopology,
    ExperimentSpec,
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet, RunResearchSemanticsReference
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import ProjectManifest, ProjectRequirementCardinality

from noetrium_platform.research.experimentation.binding import ResearchBindingContribution, ResearchRequirementResolution
from noetrium_platform.research.experimentation.study.api.contracts import StudyAssignment, StudyProtocol, StudyVariantSpec, VariantKind
from noetrium_platform.research.experimentation.study.api.design import (
    BenchmarkAssignmentMode,
    FactorSelection,
    ParticipantSchedule,
    ResearchStudyDefinition,
    StudyIntervention,
)
from noetrium_platform.research.experimentation.study.api.benchmark import TaskDefinition
from noetrium_platform.research.experimentation.study.api.measurement import MeasurementProtocol, MeasurementValueKind
from noetrium_platform.research.experimentation.study.api.plan import ExperimentPlan, VariantBinding


def _unique_preserving_order(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def resolve_research_requirements(
    definition: ResearchStudyDefinition,
    project_manifest: ProjectManifest,
) -> ResearchRequirementResolution:
    """Select the exact ProjectManifest facts required by one author definition."""
    if type(definition) is not ResearchStudyDefinition:
        raise TypeError("requirement resolver requires ResearchStudyDefinition")
    if not isinstance(project_manifest, ProjectManifest):
        raise TypeError("requirement resolver requires ProjectManifest")
    if project_manifest.identity.project_id != definition.project_id:
        raise ValueError("research requirements belong to a different project")
    if definition.study_id not in project_manifest.study_ids:
        raise ValueError("research study is not declared by ProjectManifest")
    requirements = definition.binding_requirements
    capability_ids = [requirements.trial_provider_requirement_id]
    method_pairs = []
    configuration_ids = []
    for model_role in requirements.model_roles:
        capability_ids.append(model_role.requirement_id)
        if model_role.prompt_configuration_id is not None:
            configuration_ids.append(model_role.prompt_configuration_id)
    for participant in requirements.participants:
        capability_ids.extend(participant.capability_requirement_ids)
        method_pairs.append((participant.method_id, participant.treatment_id))
        configuration_ids.extend(participant.configuration_ref_ids)

    # Executable benchmark packages own their environment/verifier requirements
    # locally. The Study compiler lifts only those requirement identities into
    # the project binding closure; concrete providers remain late-bound.
    for task in definition.benchmark.selected_tasks(definition.benchmark_split_id):
        package = task.package
        if package is None:
            continue
        for requirement_id in (
            package.environment_requirement_id,
            package.verifier_requirement_id,
            package.verifier_environment_requirement_id,
        ):
            if requirement_id is not None:
                capability_ids.append(requirement_id)

    selected_capability_ids = _unique_preserving_order(capability_ids)
    selected_method_keys = _unique_preserving_order(method_pairs)
    selected_config_ids = _unique_preserving_order(configuration_ids)
    capability_by_id = {row.requirement_id: row for row in project_manifest.capability_requirements}
    method_by_key = {(row.method_id, row.treatment_id): row for row in project_manifest.method_requirements}
    config_by_id = {row.configuration_id: row for row in project_manifest.configuration_refs}
    missing_capabilities = tuple(row for row in selected_capability_ids if row not in capability_by_id)
    missing_methods = tuple(row for row in selected_method_keys if row not in method_by_key)
    missing_configs = tuple(row for row in selected_config_ids if row not in config_by_id)
    if missing_capabilities or missing_methods or missing_configs:
        raise ValueError(
            f"research requirements unresolved: capabilities={missing_capabilities} "
            f"methods={missing_methods} configurations={missing_configs}"
        )
    selected_capabilities = tuple(capability_by_id[row] for row in selected_capability_ids)
    selected_methods = tuple(method_by_key[row] for row in selected_method_keys)
    selected_configs = tuple(config_by_id[row] for row in selected_config_ids)
    selected_capability_set = set(selected_capability_ids)
    selected_provider_bindings = tuple(
        row for row in project_manifest.provider_bindings
        if row.requirement_id in selected_capability_set
    )
    from noetrium_platform.foundation.governance.architecture.api import CompositionSubject
    return ResearchRequirementResolution(
        project_manifest.semantic_digest,
        CompositionSubject.project_subject(
            project_manifest.identity.project_id, project_manifest.identity.version
        ),
        definition.binding_requirement_digest,
        selected_capabilities, selected_methods, selected_configs, selected_provider_bindings,
    )


@dataclass(frozen=True, slots=True)
class ResearchPlanDiff:
    changed_facets: tuple[str, ...]
    scientific_design_changed: bool
    binding_changed: bool
    implementation_changed: bool
    execution_plan_changed: bool
    measurement_semantics_changed: bool
    checkpoint_compatible: bool
    exact_plan_changed: bool
    diff_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.changed_facets) is not tuple:
            raise TypeError("research plan diff changed_facets must be a tuple")
        if len(self.changed_facets) != len(set(self.changed_facets)):
            raise ValueError("research plan diff changed_facets must be unique")
        object.__setattr__(self, "diff_digest", canonical_digest({
            "changed_facets": self.changed_facets,
            "scientific_design_changed": self.scientific_design_changed,
            "binding_changed": self.binding_changed,
            "implementation_changed": self.implementation_changed,
            "execution_plan_changed": self.execution_plan_changed,
            "measurement_semantics_changed": self.measurement_semantics_changed,
            "checkpoint_compatible": self.checkpoint_compatible,
            "exact_plan_changed": self.exact_plan_changed,
        }))


@dataclass(frozen=True, slots=True)
class CompiledResearchPlan:
    definition_digest: str
    scientific_design_digest: str
    participant_design_digest: str
    binding_requirement_digest: str
    requirement_resolution_digest: str
    binding_digest: str
    method_implementation_digest: str
    execution_policy_digest: str
    benchmark_cut_digest: str
    task_definitions: tuple[TaskDefinition, ...]
    interventions: tuple[StudyIntervention, ...]
    protocol: StudyProtocol
    experiment_plan: ExperimentPlan
    experiment: ExperimentSpec
    measurement_protocol: MeasurementProtocol
    participant_schedule: ParticipantSchedule | None
    trial_protocol_identity: ExperimentTrialProtocolIdentity
    research_plan_digest: str
    research_semantics: RunResearchSemanticsReference

    def __post_init__(self) -> None:
        if type(self.task_definitions) is not tuple or any(
            type(row) is not TaskDefinition for row in self.task_definitions
        ):
            raise TypeError(
                "compiled research plan task_definitions must contain TaskDefinition"
            )
        task_ids = tuple(row.task_id for row in self.task_definitions)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("compiled research plan task ids must be unique")
        assignment_task_ids = {
            row.task_id
            for row in self.experiment_plan.assignments
            if row.task_id is not None
        }
        if assignment_task_ids != set(task_ids):
            raise ValueError(
                "compiled research plan task cut does not cover assignment tasks"
            )
        expected = canonical_digest({
            "definition_digest": self.definition_digest,
            "scientific_design_digest": self.scientific_design_digest,
            "participant_design_digest": self.participant_design_digest,
            "binding_requirement_digest": self.binding_requirement_digest,
            "requirement_resolution_digest": self.requirement_resolution_digest,
            "binding_digest": self.binding_digest,
            "method_implementation_digest": self.method_implementation_digest,
            "execution_policy_digest": self.execution_policy_digest,
            "benchmark_cut_digest": self.benchmark_cut_digest,
            "interventions": tuple(row.intervention_digest for row in self.interventions),
            "study_plan_digest": self.experiment_plan.plan_digest,
            "experiment_digest": self.experiment.identity_digest(),
            "measurement_semantics_digest": self.measurement_protocol.semantic_digest,
        })
        if expected != self.research_plan_digest:
            raise ValueError("compiled research plan digest is not authoritative")
        if self.research_semantics.research_plan_digest != self.research_plan_digest:
            raise ValueError("compiled research semantics do not bind the research plan")

    def task_for(self, task_id: str) -> TaskDefinition:
        matches = tuple(
            row for row in self.task_definitions if row.task_id == task_id
        )
        if len(matches) != 1:
            raise KeyError(
                f"compiled research plan has no unique task {task_id!r}"
            )
        return matches[0]


def _factor_selections(
    definition: ResearchStudyDefinition,
) -> tuple[tuple[FactorSelection, ...], ...]:
    if not definition.factors:
        return ((),)
    return tuple(
        tuple(
            FactorSelection(factor.factor_id, level.level_id, level.level_digest)
            for factor, level in zip(definition.factors, levels, strict=True)
        )
        for levels in product(*(factor.levels for factor in definition.factors))
    )


def _intervention_for(
    definition: ResearchStudyDefinition,
    selections: tuple[FactorSelection, ...],
) -> StudyIntervention:
    control = True
    for factor, selected in zip(definition.factors, selections, strict=True):
        level = next(row for row in factor.levels if row.level_id == selected.level_id)
        if not level.control:
            control = False
            break
    selection_digest = canonical_digest(selections)
    intervention_id = "control" if control else f"intervention-{selection_digest[:16]}"
    return StudyIntervention(intervention_id, selections)


def _trial_provider_id(
    definition: ResearchStudyDefinition,
    binding: ResearchBindingContribution,
) -> str:
    requirement_id = definition.binding_requirements.trial_provider_requirement_id
    return binding.capability_binding(requirement_id).proof.provider_identity


def _variant_for(
    definition: ResearchStudyDefinition,
    intervention: StudyIntervention,
    provider_id: str,
) -> StudyVariantSpec:
    return StudyVariantSpec(
        intervention.intervention_id,
        VariantKind.CONTROL if intervention.control else VariantKind.TREATMENT,
        provider_id,
        intervention.intervention_digest,
        definition.execution_policy.trial_budget.budget_id,
    )


def _assignments(
    definition: ResearchStudyDefinition,
    variants: tuple[StudyVariantSpec, ...],
) -> tuple[StudyAssignment, ...]:
    """Expand the exact author-declared benchmark assignment granularity."""
    tasks = definition.benchmark.selected_tasks(definition.benchmark_split_id)
    if definition.benchmark_assignment_mode is BenchmarkAssignmentMode.CUT:
        if not tasks:
            raise ValueError("cut-level Study assignment requires a non-empty benchmark cut")
        return tuple(
            StudyAssignment(
                definition.study_id,
                variant.variant_id,
                repetition,
                seed,
                None,
            )
            for repetition, variant, seed in product(
                range(definition.repetitions), variants, definition.seeds
            )
        )
    if definition.benchmark_assignment_mode is not BenchmarkAssignmentMode.TASK:
        raise ValueError(
            f"unsupported benchmark assignment mode: {definition.benchmark_assignment_mode!r}"
        )
    return tuple(
        StudyAssignment(
            definition.study_id,
            variant.variant_id,
            repetition,
            seed,
            task.task_id,
        )
        for repetition, variant, seed, task in product(
            range(definition.repetitions), variants, definition.seeds, tasks
        )
    )


def _scalar_measurement_names(protocol: MeasurementProtocol) -> tuple[str, ...]:
    return tuple(
        row.measurement_id
        for row in protocol.definitions
        if row.value_kind is MeasurementValueKind.SCALAR
    )


def _protocol(
    definition: ResearchStudyDefinition,
    variants: tuple[StudyVariantSpec, ...],
    assignments: tuple[StudyAssignment, ...],
) -> StudyProtocol:
    seed_schedule_digest = canonical_digest({
        "seeds": definition.seeds,
        "repetitions": definition.repetitions,
        "assignments": tuple(row.assignment_digest for row in assignments),
    })
    return StudyProtocol(
        definition.study_id,
        definition.workload_id,
        variants,
        definition.repetitions,
        seed_schedule_digest,
        _scalar_measurement_names(definition.measurement_protocol),
        definition.benchmark.cut_digest,
        (definition.execution_policy.trial_budget.budget_id,),
        definition.execution_policy.concurrency_policy,
    )


def _bindings(
    variants: tuple[StudyVariantSpec, ...],
    provider_id: str,
) -> tuple[VariantBinding, ...]:
    return tuple(
        VariantBinding(
            variant, variant.configuration_digest, provider_id,
            "none", variant.kind.value,
        )
        for variant in variants
    )


def _participants(
    definition: ResearchStudyDefinition,
    binding: ResearchBindingContribution,
) -> tuple[ExperimentParticipantSpec, ...]:
    requirements = {row.role: row for row in definition.binding_requirements.participants}
    return tuple(
        ExperimentParticipantSpec(
            role=row.role,
            implementation=row.binding.binding.implementation,
            runtime=row.binding.binding.runtime,
            configuration_digest=row.binding.binding.configuration_digest,
            depends_on_roles=requirements[row.role].depends_on_roles,
        )
        for row in binding.participant_bindings
    )


def _model_roles(
    definition: ResearchStudyDefinition,
    binding: ResearchBindingContribution,
) -> tuple[ExperimentModelRoleSpec, ...]:
    requirements = {
        row.role: row for row in definition.binding_requirements.model_roles
    }
    return tuple(
        ExperimentModelRoleSpec(
            role=row.role,
            requirement_id=row.requirement_id,
            provider_id=row.binding.provider_id,
            deployment_id=row.binding.deployment_id,
            deployment_generation=row.binding.deployment_generation,
            model_identity_digest=canonical_digest(row.binding.model),
            model_stack_digest=row.binding.model_stack_digest,
            binding_digest=row.binding_digest,
            prompt_generation_id=row.binding.prompt_generation_id,
            usage=requirements[row.role].usage,
            required=requirements[row.role].required,
            member_index=row.member_index,
        )
        for row in binding.model_role_bindings
    )


def _experiment(
    definition: ResearchStudyDefinition,
    protocol: StudyProtocol,
    binding: ResearchBindingContribution,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=definition.experiment_id,
        study_id=definition.study_id,
        project_id=definition.project_id,
        participants=_participants(definition, binding),
        model_roles=_model_roles(definition, binding),
        workload_digest=canonical_digest({
            "workload_id": definition.workload_id,
            "benchmark_cut_digest": definition.benchmark.cut_digest,
        }),
        seed_digest=protocol.seed_schedule_digest,
        repetitions=definition.repetitions,
        trial_protocol_id=definition.trial_protocol_identity.protocol_id,
        trial_protocol_configuration_digest=definition.trial_protocol_identity.configuration_digest,
    )


def _schedule(
    experiment: ExperimentSpec,
) -> tuple[ParticipantSchedule | None, OptionalIdentityFacet, OptionalIdentityFacet]:
    if not experiment.participants:
        absent = OptionalIdentityFacet()
        return None, absent, absent
    topology = ExperimentParticipantTopology.from_spec(experiment)
    waves = tuple(tuple(row.role for row in wave) for wave in topology.waves())
    schedule = ParticipantSchedule(waves)
    return (
        schedule,
        OptionalIdentityFacet(topology.digest()),
        OptionalIdentityFacet(schedule.schedule_digest),
    )


def _revision_facet(definition: ResearchStudyDefinition) -> OptionalIdentityFacet:
    if definition.revision is None:
        return OptionalIdentityFacet()
    return OptionalIdentityFacet(definition.revision.revision_digest)


def _validate_capability_bindings(
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    provided_ids = {row.requirement_id for row in binding.capability_bindings}
    expected_ids = set(resolution.capability_requirement_ids)
    if provided_ids != expected_ids:
        raise ValueError("binding contribution capability coverage drifted")
    for requirement in resolution.capability_requirements:
        rows = binding.capability_bindings_for(requirement.requirement_id)
        if requirement.cardinality is ProjectRequirementCardinality.EXACTLY_ONE:
            if len(rows) != 1:
                raise ValueError("exactly-one capability requires exactly one producer proof")
        elif not rows:
            raise ValueError("one-or-more capability requires producer proof")
        expected_requirement_digest = canonical_digest(requirement)
        selected_provider_ids = {
            row.provider_identity
            for row in resolution.provider_bindings_for(requirement.requirement_id)
        }
        for row in rows:
            proof = row.proof
            if proof.subject != resolution.project_subject:
                raise ValueError("capability proof belongs to another project subject")
            if proof.requirement_digest.value != expected_requirement_digest:
                raise ValueError("capability proof requirement drifted")
            if selected_provider_ids and proof.provider_identity not in selected_provider_ids:
                raise ValueError("capability proof violates ProjectManifest provider selection")


def _validate_participant_bindings(
    definition: ResearchStudyDefinition,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    requirements = definition.binding_requirements.participants
    if tuple(row.role for row in binding.participant_bindings) != tuple(row.role for row in requirements):
        raise ValueError("binding contribution participant roles drifted")
    for requirement, row in zip(requirements, binding.participant_bindings, strict=True):
        if row.proof.subject != resolution.project_subject:
            raise ValueError("participant proof belongs to another project subject")
        runtime_binding = row.binding.binding
        if runtime_binding.implementation.kind != requirement.participant_kind:
            raise ValueError("binding contribution participant kind drifted")
        if requirement.participant_kind == "method" and runtime_binding.implementation.participant_id != requirement.method_id:
            raise ValueError("method participant binding changed author method identity")
        method_matches = tuple(
            item for item in resolution.method_requirements
            if item.method_id == requirement.method_id and item.treatment_id == requirement.treatment_id
        )
        if len(method_matches) != 1:
            raise ValueError("participant has no unique resolved method implementation requirement")
        if runtime_binding.implementation.digest() != method_matches[0].implementation_digest:
            raise ValueError("participant runtime implementation does not match project method implementation")


def _validate_model_role_bindings(
    definition: ResearchStudyDefinition,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    requirements = definition.binding_requirements.model_roles
    known_roles = {row.role for row in requirements}
    bound_roles = {row.role for row in binding.model_role_bindings}
    unknown_roles = bound_roles - known_roles
    if unknown_roles:
        raise ValueError(
            f"binding contribution has undeclared model roles: {sorted(unknown_roles)}"
        )

    for requirement in requirements:
        rows = binding.model_role_bindings_for(requirement.role)
        if requirement.required and not rows:
            raise ValueError(f"required model role is unbound: {requirement.role}")
        if requirement.max_bindings is not None and len(rows) > requirement.max_bindings:
            raise ValueError(
                f"model role {requirement.role} exceeds max_bindings={requirement.max_bindings}"
            )
        for row in rows:
            if row.requirement_id != requirement.requirement_id:
                raise ValueError(
                    "model role binding does not satisfy author model role requirement"
                )
            if row.proof.subject != resolution.project_subject:
                raise ValueError("model proof belongs to another project subject")
            capability_rows = binding.capability_bindings_for(requirement.requirement_id)
            if not any(
                capability.proof.provider_identity == row.proof.provider_identity
                for capability in capability_rows
            ):
                raise ValueError(
                    "model domain binding does not match capability provider proof"
                )
            if (
                requirement.prompt_configuration_id is not None
                and row.binding.prompt_generation_id is None
            ):
                raise ValueError(
                    "prompt configuration requires a generation-bound model binding"
                )


def _validate_binding_contribution(
    definition: ResearchStudyDefinition,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    if type(resolution) is not ResearchRequirementResolution:
        raise TypeError("research compiler requires ResearchRequirementResolution")
    if type(binding) is not ResearchBindingContribution:
        raise TypeError("research compiler requires ResearchBindingContribution")
    if resolution.requirements_digest != definition.binding_requirement_digest:
        raise ValueError("requirement resolution does not bind the author definition")
    if binding.requirement_resolution_digest != resolution.resolution_digest:
        raise ValueError("binding contribution does not bind requirement resolution")
    _validate_capability_bindings(resolution, binding)
    trial_requirement = definition.binding_requirements.trial_provider_requirement_id
    if len(binding.capability_bindings_for(trial_requirement)) != 1:
        raise ValueError("compiled Trial requires exactly one trial provider proof")
    _validate_participant_bindings(definition, resolution, binding)
    _validate_model_role_bindings(definition, resolution, binding)


def _method_implementation_digest(resolution: ResearchRequirementResolution) -> str:
    """Digest the exact method implementations selected by the project manifest."""
    return canonical_digest(
        tuple(
            sorted(
                (
                    row.method_id,
                    row.treatment_id,
                    row.implementation_digest,
                )
                for row in resolution.method_requirements
            )
        )
    )


def compile_research_plan(
    definition: ResearchStudyDefinition,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> CompiledResearchPlan:
    if type(definition) is not ResearchStudyDefinition:
        raise TypeError("research compiler requires ResearchStudyDefinition")
    _validate_binding_contribution(definition, resolution, binding)
    interventions = tuple(
        _intervention_for(definition, rows) for rows in _factor_selections(definition)
    )
    provider_id = _trial_provider_id(definition, binding)
    variants = tuple(_variant_for(definition, row, provider_id) for row in interventions)
    task_definitions = definition.benchmark.selected_tasks(
        definition.benchmark_split_id
    )
    assignments = _assignments(definition, variants)
    protocol = _protocol(definition, variants, assignments)
    experiment_plan = ExperimentPlan.compile(
        protocol, _bindings(variants, provider_id), assignments
    )
    experiment = _experiment(definition, protocol, binding)
    participant_schedule, topology, schedule = _schedule(experiment)
    intervention = OptionalIdentityFacet(
        canonical_digest(tuple(row.intervention_digest for row in interventions))
    )
    revision = _revision_facet(definition)
    trial_protocol = definition.trial_protocol_identity
    method_implementation_digest = _method_implementation_digest(resolution)
    provisional_plan_digest = canonical_digest({
        "definition_digest": definition.definition_digest,
        "scientific_design_digest": definition.scientific_design_digest,
        "participant_design_digest": definition.participant_design_digest,
        "binding_requirement_digest": definition.binding_requirement_digest,
        "requirement_resolution_digest": resolution.resolution_digest,
        "binding_digest": binding.contribution_digest,
        "method_implementation_digest": method_implementation_digest,
        "execution_policy_digest": definition.execution_policy_digest,
        "benchmark_cut_digest": definition.benchmark.cut_digest,
        "interventions": tuple(row.intervention_digest for row in interventions),
        "study_plan_digest": experiment_plan.plan_digest,
        "experiment_digest": experiment.identity_digest(),
        "measurement_semantics_digest": definition.measurement_protocol.semantic_digest,
    })
    semantics = RunResearchSemanticsReference(
        research_plan_digest=provisional_plan_digest,
        study_plan_digest=experiment_plan.plan_digest,
        measurement_protocol_digest=definition.measurement_protocol.semantic_digest,
        trial_protocol_digest=trial_protocol.digest(),
        method_implementation_digest=method_implementation_digest,
        intervention=intervention,
        topology=topology,
        participant_schedule=schedule,
        revision=revision,
        replay_level=definition.execution_policy.replay_level,
    )
    return CompiledResearchPlan(
        definition_digest=definition.definition_digest,
        scientific_design_digest=definition.scientific_design_digest,
        participant_design_digest=definition.participant_design_digest,
        binding_requirement_digest=definition.binding_requirement_digest,
        requirement_resolution_digest=resolution.resolution_digest,
        binding_digest=binding.contribution_digest,
        method_implementation_digest=method_implementation_digest,
        execution_policy_digest=definition.execution_policy_digest,
        benchmark_cut_digest=definition.benchmark.cut_digest,
        task_definitions=task_definitions,
        interventions=interventions,
        protocol=protocol,
        experiment_plan=experiment_plan,
        experiment=experiment,
        measurement_protocol=definition.measurement_protocol,
        participant_schedule=participant_schedule,
        trial_protocol_identity=trial_protocol,
        research_plan_digest=provisional_plan_digest,
        research_semantics=semantics,
    )


def diff_research_plans(
    previous: CompiledResearchPlan,
    candidate: CompiledResearchPlan,
) -> ResearchPlanDiff:
    if type(previous) is not CompiledResearchPlan or type(candidate) is not CompiledResearchPlan:
        raise TypeError("research plan diff requires compiled plans")
    checks = (
        ("scientific_design", previous.scientific_design_digest, candidate.scientific_design_digest),
        ("participant_design", previous.participant_design_digest, candidate.participant_design_digest),
        ("provider_binding", previous.binding_digest, candidate.binding_digest),
        ("method_implementation", previous.method_implementation_digest, candidate.method_implementation_digest),
        ("execution_policy", previous.execution_policy_digest, candidate.execution_policy_digest),
        ("benchmark_cut", previous.benchmark_cut_digest, candidate.benchmark_cut_digest),
        ("assignments", previous.experiment_plan.assignment_digest, candidate.experiment_plan.assignment_digest),
        ("variant_bindings", previous.experiment_plan.binding_digest, candidate.experiment_plan.binding_digest),
        ("measurement_semantics", previous.measurement_protocol.semantic_digest, candidate.measurement_protocol.semantic_digest),
        ("topology", previous.research_semantics.topology, candidate.research_semantics.topology),
        ("participant_schedule", previous.research_semantics.participant_schedule, candidate.research_semantics.participant_schedule),
        ("revision", previous.research_semantics.revision, candidate.research_semantics.revision),
        ("replay_level", previous.research_semantics.replay_level, candidate.research_semantics.replay_level),
    )
    changed = tuple(name for name, left, right in checks if left != right)
    checkpoint_compatible = (
        previous.research_semantics.checkpoint_compatibility_digest
        == candidate.research_semantics.checkpoint_compatibility_digest
        and previous.method_implementation_digest == candidate.method_implementation_digest
        and previous.benchmark_cut_digest == candidate.benchmark_cut_digest
        and previous.experiment_plan.assignment_digest
        == candidate.experiment_plan.assignment_digest
    )
    return ResearchPlanDiff(
        changed_facets=changed,
        scientific_design_changed=(
            previous.scientific_design_digest != candidate.scientific_design_digest
        ),
        binding_changed=(previous.binding_digest != candidate.binding_digest),
        implementation_changed=(
            previous.method_implementation_digest != candidate.method_implementation_digest
        ),
        execution_plan_changed=(
            previous.execution_policy_digest != candidate.execution_policy_digest
            or previous.research_semantics.topology != candidate.research_semantics.topology
            or previous.research_semantics.participant_schedule
            != candidate.research_semantics.participant_schedule
        ),
        measurement_semantics_changed=(
            previous.measurement_protocol.semantic_digest
            != candidate.measurement_protocol.semantic_digest
        ),
        checkpoint_compatible=checkpoint_compatible,
        exact_plan_changed=(previous.research_plan_digest != candidate.research_plan_digest),
    )


__all__ = [
    "CompiledResearchPlan",
    "ResearchPlanDiff",
    "compile_research_plan",
    "resolve_research_requirements",
    "diff_research_plans",
]
