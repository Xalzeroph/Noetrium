"""Side-effect-free compiler from author research facts to typed run facets."""
from __future__ import annotations

from noetrium_platform.research.execution.api import (
    participant_waves,
)
from noetrium_platform.foundation.kernel.structure import atom_unit, structure_unit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_execution_plan,
    study_variant_space,
    study_plan_digest,
    study_plan_assignment_digest,
    study_plan_binding_digest,
    study_protocol,
    study_protocol_variant_space,
)

from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    benchmark_cut_digest,
    benchmark_selected_tasks,
    execution_policy_budget,
    execution_policy_replay_level,
    factor_level_value,
    measurement_protocol_semantic_digest,
    measurement_scalar_names,
    participant_schedule_digest,
    participant_schedule_unit,
    require_study_unit,
    revision_digest,
    study_assignment_workloads,
    study_assignment_relations,
    study_benchmark,
    study_benchmark_split_id,
    study_binding_requirement_digest,
    study_binding_requirements,
    study_definition_digest,
    study_execution_policy,
    study_execution_policy_digest,
    study_experiment_id,
    study_factors,
    study_id,
    study_measurement_protocol,
    study_participant_design_digest,
    study_project_id,
    study_repetitions,
    study_revision,
    study_scientific_design_digest,
    study_seeds,
    study_trial_protocol,
    study_workload_id,
    task_package,
    trial_budget_id,
    trial_protocol_configuration_digest,
    trial_protocol_digest,
    trial_protocol_id,
    trial_protocol_unit,
)
from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
    experiment_identity_digest,
    experiment_model_role_unit,
    experiment_participant_role,
    experiment_participant_unit,
    experiment_participants,
    experiment_unit,
)



from dataclasses import dataclass, field
from collections.abc import Mapping

from noetrium_platform.research.experimentation.identity import (
    require_run_research_semantics,
    run_research_checkpoint_compatibility_digest,
    run_research_semantics_unit,
    run_research_semantics_value,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.api import (
    ProjectRequirementCardinality,
    project_capability_requirement_cardinality,
    project_capability_requirement_id,
    project_configuration_reference_id,
    project_manifest_capability_requirements,
    project_manifest_configuration_refs,
    project_manifest_digest,
    project_manifest_method_requirements,
    project_manifest_project_id,
    project_manifest_provider_bindings,
    project_manifest_study_ids,
    project_manifest_version,
    project_method_requirement_implementation_digest,
    project_method_requirement_method_id,
    project_method_requirement_treatment_id,
    project_provider_binding_identity,
    project_provider_binding_requirement_id,
    require_project_manifest,
)

from noetrium_platform.research.experimentation.binding import (
    ResearchBindingAssuranceGap,
    ResearchBindingContribution,
    ResearchRequirementResolution,
    binding_requirements_model_roles,
    binding_requirements_participants,
    binding_requirements_topology,
    binding_requirements_trial_provider,
    model_role_requirement_id,
    model_role_requirement_max_bindings,
    model_role_requirement_prompt,
    model_role_requirement_required,
    model_role_requirement_role,
    model_role_requirement_usage,
    participant_requirement_capabilities,
    participant_requirement_configurations,
    participant_requirement_kind,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_requirement_treatment_id,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.execution.api import (
    participant_implementation_digest,
    participant_implementation_id,
    participant_implementation_kind,
)


def _unique_preserving_order(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ResearchManifestRequirementKeys:
    """Exact ProjectManifest keys selected by one NoetriumUnit."""

    capability_requirement_ids: tuple[str, ...]
    method_requirement_keys: tuple[tuple[str, str], ...]
    configuration_ref_ids: tuple[str, ...]
    keys_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.capability_requirement_ids) is not tuple:
            raise TypeError("manifest capability requirement ids must be tuple")
        if type(self.method_requirement_keys) is not tuple:
            raise TypeError("manifest method requirement keys must be tuple")
        if type(self.configuration_ref_ids) is not tuple:
            raise TypeError("manifest configuration ref ids must be tuple")
        if len(self.capability_requirement_ids) != len(
            set(self.capability_requirement_ids)
        ):
            raise ValueError("manifest capability requirement ids must be unique")
        if len(self.method_requirement_keys) != len(
            set(self.method_requirement_keys)
        ):
            raise ValueError("manifest method requirement keys must be unique")
        if len(self.configuration_ref_ids) != len(
            set(self.configuration_ref_ids)
        ):
            raise ValueError("manifest configuration ref ids must be unique")
        object.__setattr__(
            self,
            "keys_digest",
            canonical_digest(
                {
                    "capability_requirement_ids": self.capability_requirement_ids,
                    "method_requirement_keys": self.method_requirement_keys,
                    "configuration_ref_ids": self.configuration_ref_ids,
                }
            ),
        )


def research_manifest_requirement_keys(
    definition: NoetriumUnit,
) -> ResearchManifestRequirementKeys:
    """Derive the exact ProjectManifest key set needed by one Study."""

    if type(definition) is not NoetriumUnit:
        raise TypeError(
            "manifest requirement selection requires NoetriumUnit"
        )
    requirements = study_binding_requirements(definition)
    capability_ids = [binding_requirements_trial_provider(requirements)]
    method_pairs: list[tuple[str, str]] = []
    configuration_ids: list[str] = []

    for model_role in binding_requirements_model_roles(requirements):
        capability_ids.append(model_role_requirement_id(model_role))
        if model_role_requirement_prompt(model_role) is not None:
            configuration_ids.append(model_role_requirement_prompt(model_role))

    for participant in binding_requirements_participants(requirements):
        capability_ids.extend(participant_requirement_capabilities(participant))
        method_pairs.append(
            (participant_requirement_method_id(participant), participant_requirement_treatment_id(participant))
        )
        configuration_ids.extend(participant_requirement_configurations(participant))

    for task in benchmark_selected_tasks(study_benchmark(definition), study_benchmark_split_id(definition)):
        package = task_package(task)
        if package is None:
            continue
        for requirement_id in (
            package.get("environment_requirement_id"),
            package.get("verifier_requirement_id"),
            package.get("verifier_environment_requirement_id"),
        ):
            if requirement_id is not None:
                capability_ids.append(requirement_id)

    return ResearchManifestRequirementKeys(
        _unique_preserving_order(capability_ids),
        _unique_preserving_order(method_pairs),
        _unique_preserving_order(configuration_ids),
    )


class ResearchManifestRequirementsUnresolved(ValueError):
    """A ProjectManifest does not cover the exact keys selected by one Study."""

    def __init__(
        self,
        *,
        keys: ResearchManifestRequirementKeys,
        missing_capability_requirement_ids: tuple[str, ...],
        missing_method_requirement_keys: tuple[tuple[str, str], ...],
        missing_configuration_ref_ids: tuple[str, ...],
    ) -> None:
        if type(keys) is not ResearchManifestRequirementKeys:
            raise TypeError(
                "unresolved Research manifest requirements require typed keys"
            )
        for field_name, values in (
            (
                "missing_capability_requirement_ids",
                missing_capability_requirement_ids,
            ),
            (
                "missing_method_requirement_keys",
                missing_method_requirement_keys,
            ),
            (
                "missing_configuration_ref_ids",
                missing_configuration_ref_ids,
            ),
        ):
            if type(values) is not tuple:
                raise TypeError(
                    f"unresolved Research manifest {field_name} must be tuple"
                )
        if not (
            missing_capability_requirement_ids
            or missing_method_requirement_keys
            or missing_configuration_ref_ids
        ):
            raise ValueError(
                "unresolved Research manifest requirements need a missing key"
            )
        self.keys = keys
        self.missing_capability_requirement_ids = (
            missing_capability_requirement_ids
        )
        self.missing_method_requirement_keys = missing_method_requirement_keys
        self.missing_configuration_ref_ids = missing_configuration_ref_ids
        self.error_digest = canonical_digest(
            {
                "manifest_keys_digest": keys.keys_digest,
                "missing_capability_requirement_ids": (
                    missing_capability_requirement_ids
                ),
                "missing_method_requirement_keys": (
                    missing_method_requirement_keys
                ),
                "missing_configuration_ref_ids": (
                    missing_configuration_ref_ids
                ),
            }
        )
        super().__init__(
            "research ProjectManifest requirements unresolved: "
            f"capabilities={missing_capability_requirement_ids} "
            f"methods={missing_method_requirement_keys} "
            f"configurations={missing_configuration_ref_ids}"
        )


def resolve_research_requirements(
    definition: NoetriumUnit,
    project_manifest: NoetriumUnit,
) -> ResearchRequirementResolution:
    """Select the exact ProjectManifest facts required by one author definition."""
    if type(definition) is not NoetriumUnit:
        raise TypeError("requirement resolver requires research.study NoetriumUnit")
    require_project_manifest(project_manifest)
    if project_manifest_project_id(project_manifest) != study_project_id(definition):
        raise ValueError("research requirements belong to a different project")
    if study_id(definition) not in project_manifest_study_ids(project_manifest):
        raise ValueError("research study is not declared by ProjectManifest")
    selected = research_manifest_requirement_keys(definition)
    selected_capability_ids = selected.capability_requirement_ids
    selected_method_keys = selected.method_requirement_keys
    selected_config_ids = selected.configuration_ref_ids
    capability_by_id = {project_capability_requirement_id(row): row for row in project_manifest_capability_requirements(project_manifest)}
    method_by_key = {(project_method_requirement_method_id(row), project_method_requirement_treatment_id(row)): row for row in project_manifest_method_requirements(project_manifest)}
    config_by_id = {project_configuration_reference_id(row): row for row in project_manifest_configuration_refs(project_manifest)}
    missing_capabilities = tuple(row for row in selected_capability_ids if row not in capability_by_id)
    missing_methods = tuple(row for row in selected_method_keys if row not in method_by_key)
    missing_configs = tuple(row for row in selected_config_ids if row not in config_by_id)
    if missing_capabilities or missing_methods or missing_configs:
        raise ResearchManifestRequirementsUnresolved(
            keys=selected,
            missing_capability_requirement_ids=missing_capabilities,
            missing_method_requirement_keys=missing_methods,
            missing_configuration_ref_ids=missing_configs,
        )
    selected_capabilities = tuple(capability_by_id[row] for row in selected_capability_ids)
    selected_methods = tuple(method_by_key[row] for row in selected_method_keys)
    selected_configs = tuple(config_by_id[row] for row in selected_config_ids)
    selected_capability_set = set(selected_capability_ids)
    selected_provider_bindings = tuple(
        row for row in project_manifest_provider_bindings(project_manifest)
        if project_provider_binding_requirement_id(row) in selected_capability_set
    )
    from noetrium_platform.research.execution.api import CompositionSubject
    return ResearchRequirementResolution(
        project_manifest_digest(project_manifest),
        CompositionSubject.project_subject(
            project_manifest_project_id(project_manifest), project_manifest_version(project_manifest)
        ),
        study_binding_requirement_digest(definition),
        selected_capabilities, selected_methods, selected_configs, selected_provider_bindings,
    )


RESEARCH_PLAN_DIFF_TRAIT = "research.plan-diff"

def research_plan_diff_value(diff: NoetriumUnit, name: str):
    if type(diff) is not NoetriumUnit or not diff.has_trait(RESEARCH_PLAN_DIFF_TRAIT): raise TypeError("research plan diff must be NoetriumUnit")
    return diff.parameters[name]


RESEARCH_PLAN_TRAIT = "research.compiled-plan"

def research_plan_graph(*, definition:NoetriumUnit, definition_digest:str, scientific_design_digest:str, participant_design_digest:str, binding_requirement_digest:str, requirement_resolution_digest:str, binding_digest:str, binding_assurance_gaps:tuple[ResearchBindingAssuranceGap,...], method_implementation_digest:str, execution_policy_digest:str, benchmark_cut_digest:str, protocol:NoetriumUnit, experiment_plan:NoetriumUnit, experiment_digest:str, measurement_semantics_digest:str, trial_protocol_digest:str, research_plan_digest:str, semantics:NoetriumUnit) -> NoetriumUnit:
    gaps=tuple(sorted(binding_assurance_gaps,key=lambda x:x.gap_digest))
    if gaps!=binding_assurance_gaps or len({x.gap_digest for x in gaps})!=len(gaps): raise ValueError("research binding assurance gaps must be canonical and unique")
    semantics = require_run_research_semantics(semantics)
    params={"definition_digest":definition_digest,"scientific_design_digest":scientific_design_digest,"participant_design_digest":participant_design_digest,"binding_requirement_digest":binding_requirement_digest,"requirement_resolution_digest":requirement_resolution_digest,"binding_digest":binding_digest,"binding_assurance_gap_digests":tuple(x.gap_digest for x in gaps),"method_implementation_digest":method_implementation_digest,"execution_policy_digest":execution_policy_digest,"benchmark_cut_digest":benchmark_cut_digest,"experiment_digest":experiment_digest,"measurement_semantics_digest":measurement_semantics_digest,"trial_protocol_digest":trial_protocol_digest,"research_plan_digest":research_plan_digest,"semantics_checkpoint_digest":run_research_checkpoint_compatibility_digest(semantics),"topology_digest":run_research_semantics_value(semantics,"topology_digest"),"participant_schedule_digest":run_research_semantics_value(semantics,"participant_schedule_digest"),"revision_digest":run_research_semantics_value(semantics,"revision_digest"),"replay_level":run_research_semantics_value(semantics,"replay_level")}
    identity_atom=atom_unit("study-identity","research.study-identity",{
        "project_id":study_project_id(definition),"experiment_id":study_experiment_id(definition),"study_id":study_id(definition),"workload_id":study_workload_id(definition),
        "trial_protocol":{"protocol_id":trial_protocol_id(study_trial_protocol(definition)),"configuration_digest":trial_protocol_configuration_digest(study_trial_protocol(definition))},
    })
    return structure_unit("research-plan:"+research_plan_digest[:20],traits=(RESEARCH_PLAN_TRAIT,),parameters=params,atoms=(identity_atom,),members=(structure_unit("protocol",traits=("research.plan-protocol",),members=(protocol,)),structure_unit("study-plan",traits=("research.plan-study",),members=(experiment_plan,)),semantics))

def require_research_plan(g:NoetriumUnit)->NoetriumUnit:
    if type(g) is not NoetriumUnit or not g.has_trait(RESEARCH_PLAN_TRAIT): raise TypeError("research plan must be NoetriumUnit")
    return g
def research_plan_value(g:NoetriumUnit,name:str): require_research_plan(g); return g.parameters[name]
def research_plan_protocol(g:NoetriumUnit)->NoetriumUnit: require_research_plan(g); return g.member("protocol").members[0]
def research_plan_study(g:NoetriumUnit)->NoetriumUnit: require_research_plan(g); return g.member("study-plan").members[0]
def research_plan_semantics(g:NoetriumUnit)->NoetriumUnit:
    require_research_plan(g)
    rows=tuple(row for row in g.members if row.has_trait("research.run-semantics"))
    if len(rows)!=1: raise ValueError("research plan requires exactly one run-semantics Unit")
    return require_run_research_semantics(rows[0])
def research_plan_digest(g:NoetriumUnit)->str: return research_plan_value(g,"research_plan_digest")
def research_plan_study_identity(g:NoetriumUnit):
    require_research_plan(g)
    atom=next((row for row in g.atoms if row.atom_id=="study-identity"),None)
    if atom is None or not isinstance(atom.value, Mapping): raise ValueError("research plan missing study identity atom")
    return atom.value
def research_plan_trial_protocol_identity(g: NoetriumUnit) -> NoetriumUnit:
    value = research_plan_study_identity(g)["trial_protocol"]
    return trial_protocol_unit(
        str(value["protocol_id"]),
        str(value["configuration_digest"]),
    )

def research_plan_binding_complete(g:NoetriumUnit)->bool: require_research_plan(g); return not tuple(g.parameters["binding_assurance_gap_digests"])


def _trial_provider_id(
    definition: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> str:
    requirement_id = binding_requirements_trial_provider(
        study_binding_requirements(definition)
    )
    return binding.capability_binding(requirement_id).proof.provider_identity


def _seed_schedule_digest(definition: NoetriumUnit) -> str:
    return canonical_digest(
        {
            "schema": "noetrium.study-seed-schedule.v2",
            "seeds": study_seeds(definition),
            "repetitions": study_repetitions(definition),
        }
    )


def _protocol(
    definition: NoetriumUnit,
    provider_id: str,
) -> NoetriumUnit:
    seed_schedule_digest = _seed_schedule_digest(definition)
    budget = execution_policy_budget(study_execution_policy(definition))
    variant_space = study_variant_space(
        study_factors(definition),
        implementation_id=provider_id,
        budget_tier=None if budget is None else trial_budget_id(budget),
    )
    return study_protocol(
        study_id=study_id(definition),
        workload_id=study_workload_id(definition),
        variant_space=variant_space,
        repetitions=study_repetitions(definition),
        seed_schedule_digest=seed_schedule_digest,
        metric_names=measurement_scalar_names(
            study_measurement_protocol(definition)
        ),
        task_manifest_digest=benchmark_cut_digest(study_benchmark(definition)),
        assignment_workloads=study_assignment_workloads(definition),
        assignment_relations=study_assignment_relations(definition),
        budget_tiers=() if budget is None else (trial_budget_id(budget),),
    )


def _participants(
    definition: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> tuple[NoetriumUnit, ...]:
    del definition
    return tuple(
        experiment_participant_unit(
            row.role,
            implementation_kind=participant_implementation_kind(row.binding.binding.implementation),
            participant_id=participant_implementation_id(row.binding.binding.implementation),
            implementation_digest=participant_implementation_digest(row.binding.binding.implementation),
            runtime_digest=row.binding.binding.runtime.digest(),
            configuration_digest=row.binding.binding.configuration_digest,
        )
        for row in binding.participant_bindings
    )


def _model_roles(
    definition: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> tuple[NoetriumUnit, ...]:
    requirements = {
        model_role_requirement_role(row): row
        for row in binding_requirements_model_roles(study_binding_requirements(definition))
    }
    return tuple(
        experiment_model_role_unit(
            row.role,
            requirement_id=row.requirement_id,
            model_definition_digest=str(row.binding.parameters["model_definition_digest"]),
            model_id=row.model_id,
            binding_digest=row.binding_digest,
            prompt_generation_id=row.prompt_generation_id,
            prompt_digest=row.prompt_digest,
            capabilities=row.capabilities,
            usage=model_role_requirement_usage(requirements[row.role]),
            required=model_role_requirement_required(requirements[row.role]),
            member_index=row.member_index,
        )
        for row in binding.model_role_bindings
    )


def _experiment(
    definition: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> NoetriumUnit:
    trial = study_trial_protocol(definition)
    return experiment_unit(
        study_experiment_id(definition),
        study_id=study_id(definition),
        project_id=study_project_id(definition),
        participants=_participants(definition, binding),
        model_roles=_model_roles(definition, binding),
        workload_digest=canonical_digest({
            "workload_id": study_workload_id(definition),
            "benchmark_cut_digest": benchmark_cut_digest(study_benchmark(definition)),
        }),
        seed_digest=_seed_schedule_digest(definition),
        repetitions=study_repetitions(definition),
        trial_protocol_id=trial_protocol_id(trial),
        trial_protocol_configuration_digest=trial_protocol_configuration_digest(trial),
    )


def _schedule(
    experiment: NoetriumUnit,
    topology_graph: NoetriumUnit,
) -> tuple[
    NoetriumUnit | None,
    str | None,
    str | None,
]:
    participants = experiment_participants(experiment)
    if not participants:
        return None, None, None
    resolved_roles = {experiment_participant_role(row) for row in participants}
    topology_roles = {child.unit_id for child in topology_graph.members}
    if resolved_roles != topology_roles:
        raise ValueError(
            "resolved experiment participants drifted from participant graph"
        )
    waves = participant_waves(topology_graph)
    schedule = participant_schedule_unit(
        waves,
        topology_digest=topology_graph.unit_digest,
    )
    return (
        schedule,
        topology_graph.unit_digest,
        participant_schedule_digest(schedule),
    )

def _revision_digest(definition: NoetriumUnit) -> str | None:
    revision = study_revision(definition)
    if revision is None:
        return None
    return revision_digest(revision)

def _validate_capability_bindings(
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    provided_ids = {row.requirement_id for row in binding.capability_bindings}
    expected_ids = set(resolution.capability_requirement_ids)
    if not provided_ids <= expected_ids:
        raise ValueError("binding contribution has undeclared capability proofs")

    model_requirements = {
        model_role_requirement_id(row): row
        for row in binding_requirements_model_roles(study_binding_requirements(definition))
    }
    allowed_missing: set[str] = set()
    for requirement_id, model_requirement in model_requirements.items():
        gaps = binding.assurance_gaps_for(
            domain="model",
            requirement_digest=model_requirement.unit_digest,
        )
        if gaps:
            allowed_missing.add(requirement_id)
    if expected_ids - provided_ids - allowed_missing:
        raise ValueError("binding contribution capability coverage drifted")

    for requirement in resolution.capability_requirements:
        rows = binding.capability_bindings_for(project_capability_requirement_id(requirement))
        if not rows and project_capability_requirement_id(requirement) in allowed_missing:
            continue
        if project_capability_requirement_cardinality(requirement) is ProjectRequirementCardinality.EXACTLY_ONE:
            if len(rows) != 1:
                raise ValueError("exactly-one capability requires exactly one producer proof")
        elif not rows:
            raise ValueError("one-or-more capability requires producer proof")
        expected_requirement_digest = requirement.unit_digest
        selected_provider_ids = {
            project_provider_binding_identity(row)
            for row in resolution.provider_bindings_for(project_capability_requirement_id(requirement))
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
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    requirements = binding_requirements_participants(study_binding_requirements(definition))
    if tuple(row.role for row in binding.participant_bindings) != tuple(participant_requirement_role(row) for row in requirements):
        raise ValueError("binding contribution participant roles drifted")
    for requirement, row in zip(requirements, binding.participant_bindings, strict=True):
        if row.proof.subject != resolution.project_subject:
            raise ValueError("participant proof belongs to another project subject")
        runtime_binding = row.binding.binding
        if participant_implementation_kind(runtime_binding.implementation) != participant_requirement_kind(requirement):
            raise ValueError("binding contribution participant kind drifted")
        if participant_requirement_kind(requirement) == "method" and participant_implementation_id(runtime_binding.implementation) != participant_requirement_method_id(requirement):
            raise ValueError("method participant binding changed author method identity")
        try:
            method_requirement = resolution.method_requirement(
                participant_requirement_method_id(requirement), participant_requirement_treatment_id(requirement)
            )
        except KeyError as exc:
            raise ValueError(
                "participant has no unique resolved method implementation requirement"
            ) from exc
        if participant_implementation_digest(runtime_binding.implementation) != project_method_requirement_implementation_digest(method_requirement):
            raise ValueError("participant runtime implementation does not match project method implementation")


def _validate_model_role_bindings(
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    requirements = binding_requirements_model_roles(study_binding_requirements(definition))
    known_roles = {model_role_requirement_role(row) for row in requirements}
    bound_roles = {row.role for row in binding.model_role_bindings}
    unknown_roles = bound_roles - known_roles
    if unknown_roles:
        raise ValueError(
            f"binding contribution has undeclared model roles: {sorted(unknown_roles)}"
        )

    known_requirement_digests = {row.unit_digest for row in requirements}
    for gap in binding.assurance_gaps:
        if (
            gap.domain != "model"
            or gap.requirement_digest not in known_requirement_digests
        ):
            raise ValueError(
                "binding contribution contains an unsupported assurance gap"
            )

    for requirement in requirements:
        rows = binding.model_role_bindings_for(model_role_requirement_role(requirement))
        gaps = binding.assurance_gaps_for(
            domain="model",
            requirement_digest=requirement.unit_digest,
        )
        if model_role_requirement_required(requirement) and not rows:
            if len(gaps) != 1:
                raise ValueError(
                    f"required model role lacks binding assurance evidence: {model_role_requirement_role(requirement)}"
                )
            continue
        if not model_role_requirement_required(requirement) and gaps:
            raise ValueError(
                f"optional model role must not create assurance gap: {model_role_requirement_role(requirement)}"
            )
        if model_role_requirement_max_bindings(requirement) is not None and len(rows) > model_role_requirement_max_bindings(requirement):
            raise ValueError(
                f"model role {model_role_requirement_role(requirement)} exceeds max_bindings={model_role_requirement_max_bindings(requirement)}"
            )
        capability_provider_ids = {
            capability.proof.provider_identity
            for capability in binding.capability_bindings_for(
                model_role_requirement_id(requirement)
            )
        }
        for row in rows:
            if row.requirement_id != model_role_requirement_id(requirement):
                raise ValueError(
                    "model role binding does not satisfy author model role requirement"
                )
            if row.proof.subject != resolution.project_subject:
                raise ValueError("model proof belongs to another project subject")
            if row.proof.provider_identity not in capability_provider_ids:
                raise ValueError(
                    "model domain binding does not match capability provider proof"
                )
            if row.requirement_digest != requirement.unit_digest:
                raise ValueError(
                    "model role binding requirement digest drifted"
                )
            if (
                model_role_requirement_prompt(requirement) is not None
                and row.prompt_generation_id is None
            ):
                raise ValueError(
                    "prompt configuration requires a generation-bound model binding"
                )


def _validate_binding_contribution(
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    if type(resolution) is not ResearchRequirementResolution:
        raise TypeError("research compiler requires ResearchRequirementResolution")
    if type(binding) is not ResearchBindingContribution:
        raise TypeError("research compiler requires ResearchBindingContribution")
    if resolution.requirements_digest != study_binding_requirement_digest(definition):
        raise ValueError("requirement resolution does not bind the author definition")
    if binding.requirement_resolution_digest != resolution.resolution_digest:
        raise ValueError("binding contribution does not bind requirement resolution")
    _validate_capability_bindings(definition, resolution, binding)
    trial_requirement = binding_requirements_trial_provider(study_binding_requirements(definition))
    if len(binding.capability_bindings_for(trial_requirement)) != 1:
        raise ValueError("compiled Trial requires exactly one trial provider proof")
    _validate_participant_bindings(definition, resolution, binding)
    _validate_model_role_bindings(definition, resolution, binding)


def validate_research_binding_contribution(
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> None:
    """Validate one immutable binding closure without materializing a plan.

    Binding authority proves only requirement/binding consistency. Factorial
    intervention and assignment expansion belongs to experiment execution
    planning and must never be paid during authority materialization.
    """
    if type(definition) is not NoetriumUnit:
        raise TypeError("research binding validation requires research.study NoetriumUnit")
    _validate_binding_contribution(definition, resolution, binding)


def _method_implementation_digest(resolution: ResearchRequirementResolution) -> str:
    """Digest the exact method implementations selected by the project manifest."""
    return canonical_digest(
        tuple(
            sorted(
                (
                    project_method_requirement_method_id(row),
                    project_method_requirement_treatment_id(row),
                    project_method_requirement_implementation_digest(row),
                )
                for row in resolution.method_requirements
            )
        )
    )



def compile_research_participant_schedule(
    definition: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> NoetriumUnit | None:
    # Participant scheduling is purely a participant-topology projection.  It
    # must never force factorial intervention or assignment materialization.
    experiment = _experiment(definition, binding)
    return _schedule(
        experiment,
        binding_requirements_topology(study_binding_requirements(definition)),
    )[0]


def compile_research_plan(
    definition: NoetriumUnit,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> NoetriumUnit:
    if type(definition) is not NoetriumUnit:
        raise TypeError("research compiler requires research.study NoetriumUnit")
    _validate_binding_contribution(definition, resolution, binding)
    provider_id = _trial_provider_id(definition, binding)
    protocol = _protocol(definition, provider_id)
    experiment_plan = study_execution_plan(
        protocol,
        seeds=study_seeds(definition),
    )
    experiment = _experiment(definition, binding)
    participant_schedule, topology, schedule = _schedule(
        experiment,
        binding_requirements_topology(study_binding_requirements(definition)),
    )
    intervention = canonical_digest(
        {
            "schema": "noetrium.intervention-space.v1",
            "variant_space_digest": study_protocol_variant_space(protocol).unit_digest,
        }
    )
    revision = _revision_digest(definition)
    trial_protocol = study_trial_protocol(definition)
    method_implementation_digest = _method_implementation_digest(resolution)
    # Every projection below is a pure Unit digest. Calculate each only once
    # per compilation: nested recursive Study/Plan graphs can be large, and
    # repeatedly obtaining one projection has no additional semantic value.
    definition_digest = study_definition_digest(definition)
    scientific_digest = study_scientific_design_digest(definition)
    participant_digest = study_participant_design_digest(definition)
    requirement_digest = study_binding_requirement_digest(definition)
    execution_policy_digest = study_execution_policy_digest(definition)
    benchmark_digest = benchmark_cut_digest(study_benchmark(definition))
    study_execution_digest = study_plan_digest(experiment_plan)
    experiment_digest = experiment_identity_digest(experiment)
    measurement_digest = measurement_protocol_semantic_digest(
        study_measurement_protocol(definition)
    )
    protocol_trial_digest = trial_protocol_digest(trial_protocol)
    assurance_gaps = tuple(row.gap_digest for row in binding.assurance_gaps)
    provisional_plan_digest = canonical_digest({
        "definition_digest": definition_digest,
        "scientific_design_digest": scientific_digest,
        "participant_design_digest": participant_digest,
        "binding_requirement_digest": requirement_digest,
        "requirement_resolution_digest": resolution.resolution_digest,
        "binding_digest": binding.contribution_digest,
        "binding_assurance_gaps": assurance_gaps,
        "method_implementation_digest": method_implementation_digest,
        "execution_policy_digest": execution_policy_digest,
        "benchmark_cut_digest": benchmark_digest,
        "intervention_space_digest": intervention,
        "study_plan_digest": study_execution_digest,
        "experiment_digest": experiment_digest,
        "measurement_semantics_digest": measurement_digest,
    })
    semantics = run_research_semantics_unit(
        research_plan_digest=provisional_plan_digest,
        study_plan_digest=study_execution_digest,
        measurement_protocol_digest=measurement_digest,
        trial_protocol_digest=protocol_trial_digest,
        method_implementation_digest=method_implementation_digest,
        intervention_digest=intervention,
        topology_digest=topology,
        participant_schedule_digest=schedule,
        revision_digest=revision,
        replay_level=execution_policy_replay_level(study_execution_policy(definition)),
    )
    return research_plan_graph(
        definition=definition,
        definition_digest=definition_digest,
        scientific_design_digest=scientific_digest,
        participant_design_digest=participant_digest,
        binding_requirement_digest=requirement_digest,
        requirement_resolution_digest=resolution.resolution_digest,
        binding_digest=binding.contribution_digest,
        binding_assurance_gaps=binding.assurance_gaps,
        method_implementation_digest=method_implementation_digest,
        execution_policy_digest=execution_policy_digest,
        benchmark_cut_digest=benchmark_digest,
        protocol=protocol,
        experiment_plan=experiment_plan,
        experiment_digest=experiment_digest,
        measurement_semantics_digest=measurement_digest,
        trial_protocol_digest=protocol_trial_digest,
        research_plan_digest=provisional_plan_digest,
        semantics=semantics,
    )

def diff_research_plans(
    previous: NoetriumUnit,
    candidate: NoetriumUnit,
) -> NoetriumUnit:
    require_research_plan(previous); require_research_plan(candidate)
    checks = (
        ("scientific_design", research_plan_value(previous, "scientific_design_digest"), research_plan_value(candidate, "scientific_design_digest")),
        ("participant_design", research_plan_value(previous, "participant_design_digest"), research_plan_value(candidate, "participant_design_digest")),
        ("provider_binding", research_plan_value(previous, "binding_digest"), research_plan_value(candidate, "binding_digest")),
        ("method_implementation", research_plan_value(previous, "method_implementation_digest"), research_plan_value(candidate, "method_implementation_digest")),
        ("execution_policy", research_plan_value(previous, "execution_policy_digest"), research_plan_value(candidate, "execution_policy_digest")),
        ("benchmark_cut", research_plan_value(previous, "benchmark_cut_digest"), research_plan_value(candidate, "benchmark_cut_digest")),
        ("assignments", study_plan_assignment_digest(research_plan_study(previous)), study_plan_assignment_digest(research_plan_study(candidate))),
        ("variant_bindings", study_plan_binding_digest(research_plan_study(previous)), study_plan_binding_digest(research_plan_study(candidate))),
        ("measurement_semantics", research_plan_value(previous, "measurement_semantics_digest"), research_plan_value(candidate, "measurement_semantics_digest")),
        ("topology", research_plan_value(previous, "topology_digest"), research_plan_value(candidate, "topology_digest")),
        ("participant_schedule", research_plan_value(previous, "participant_schedule_digest"), research_plan_value(candidate, "participant_schedule_digest")),
        ("revision", research_plan_value(previous, "revision_digest"), research_plan_value(candidate, "revision_digest")),
        ("replay_level", research_plan_value(previous, "replay_level"), research_plan_value(candidate, "replay_level")),
    )
    changed = tuple(name for name, left, right in checks if left != right)
    checkpoint_compatible = (
        research_plan_value(previous, "semantics_checkpoint_digest")
        == research_plan_value(candidate, "semantics_checkpoint_digest")
        and research_plan_value(previous, "method_implementation_digest") == research_plan_value(candidate, "method_implementation_digest")
        and research_plan_value(previous, "benchmark_cut_digest") == research_plan_value(candidate, "benchmark_cut_digest")
        and study_plan_assignment_digest(research_plan_study(previous))
        == study_plan_assignment_digest(research_plan_study(candidate))
    )
    params={
        "changed_facets": changed,
        "scientific_design_changed": research_plan_value(previous,"scientific_design_digest") != research_plan_value(candidate,"scientific_design_digest"),
        "binding_changed": research_plan_value(previous,"binding_digest") != research_plan_value(candidate,"binding_digest"),
        "implementation_changed": research_plan_value(previous,"method_implementation_digest") != research_plan_value(candidate,"method_implementation_digest"),
        "execution_plan_changed": (research_plan_value(previous,"execution_policy_digest") != research_plan_value(candidate,"execution_policy_digest") or research_plan_value(previous,"topology_digest") != research_plan_value(candidate,"topology_digest") or research_plan_value(previous,"participant_schedule_digest") != research_plan_value(candidate,"participant_schedule_digest")),
        "measurement_semantics_changed": research_plan_value(previous,"measurement_semantics_digest") != research_plan_value(candidate,"measurement_semantics_digest"),
        "checkpoint_compatible": checkpoint_compatible,
        "exact_plan_changed": research_plan_digest(previous) != research_plan_digest(candidate),
        "previous_digest": research_plan_digest(previous),
        "candidate_digest": research_plan_digest(candidate),
    }
    return structure_unit("research-plan-diff:"+canonical_digest(params)[:20],traits=(RESEARCH_PLAN_DIFF_TRAIT,),parameters=params)


__all__ = [
    "compile_research_participant_schedule",
    "RESEARCH_PLAN_TRAIT", "research_plan_graph", "require_research_plan", "research_plan_value", "research_plan_protocol", "research_plan_study", "research_plan_digest", "research_plan_binding_complete",
    "RESEARCH_PLAN_DIFF_TRAIT",
    "research_plan_diff_value",
    "compile_research_plan",
    "validate_research_binding_contribution",
    "resolve_research_requirements",
    "diff_research_plans",
]
