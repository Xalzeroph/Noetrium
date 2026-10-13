"""Unit-only Experiment and Metric semantics."""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.research.experimentation.identity import ModelRoleUsage

EXPERIMENT_PARTICIPANT_TRAIT = "noetrium.experiment-participant"
EXPERIMENT_MODEL_ROLE_TRAIT = "noetrium.experiment-model-role"
EXPERIMENT_TRAIT = "research.experiment"
METRIC_PREDICATE_TRAIT = "noetrium.metric-predicate"
METRIC_DEFINITION_TRAIT = "research.metric"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def experiment_participant_unit(
    role: str,
    *,
    implementation_kind: str,
    participant_id: str,
    implementation_digest: str,
    runtime_digest: str,
    configuration_digest: str | None = None,
) -> NoetriumUnit:
    role = _text(role, "experiment participant role")
    implementation_kind = _text(implementation_kind, "experiment participant kind")
    participant_id = _text(participant_id, "experiment participant id")
    require_sha256(implementation_digest, "experiment participant implementation_digest")
    require_sha256(runtime_digest, "experiment participant runtime_digest")
    if configuration_digest is not None:
        require_sha256(configuration_digest, "experiment participant configuration_digest")
    return structure_unit(
        role,
        traits=(EXPERIMENT_PARTICIPANT_TRAIT,),
        parameters={
            "role": role,
            "implementation_kind": implementation_kind,
            "participant_id": participant_id,
            "implementation_digest": implementation_digest,
            "runtime_digest": runtime_digest,
            "configuration_digest": configuration_digest,
        },
    )


def require_experiment_participant(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(EXPERIMENT_PARTICIPANT_TRAIT):
        raise TypeError("experiment participant must be NoetriumUnit")
    return value


def experiment_participant_role(value: NoetriumUnit) -> str:
    return str(require_experiment_participant(value).parameters["role"])


def experiment_participant_kind(value: NoetriumUnit) -> str:
    return str(require_experiment_participant(value).parameters["implementation_kind"])


def experiment_participant_implementation_digest(value: NoetriumUnit) -> str:
    return str(require_experiment_participant(value).parameters["implementation_digest"])


def experiment_participant_runtime_digest(value: NoetriumUnit) -> str:
    return str(require_experiment_participant(value).parameters["runtime_digest"])


def experiment_model_role_unit(
    role: str,
    *,
    requirement_id: str,
    model_definition_digest: str,
    model_id: str,
    binding_digest: str,
    prompt_generation_id: str | None = None,
    prompt_digest: str | None = None,
    capabilities: tuple[str, ...] = (),
    usage: ModelRoleUsage = ModelRoleUsage.EXECUTION,
    required: bool = True,
    member_index: int = 0,
) -> NoetriumUnit:
    role = _text(role, "experiment model role")
    requirement_id = _text(requirement_id, "experiment model requirement_id")
    model_id = _text(model_id, "experiment model_id")
    require_sha256(model_definition_digest, "experiment model definition digest")
    require_sha256(binding_digest, "experiment model binding digest")
    if prompt_generation_id is None:
        if prompt_digest is not None:
            raise ValueError("prompt digest requires prompt generation id")
    else:
        _text(prompt_generation_id, "experiment model prompt_generation_id")
        require_sha256(prompt_digest, "experiment model prompt_digest")
    if type(capabilities) is not tuple or any(type(row) is not str or not row.strip() for row in capabilities):
        raise TypeError("experiment model capabilities must be text tuple")
    capabilities = tuple(sorted(set(capabilities)))
    if not isinstance(usage, ModelRoleUsage):
        raise TypeError("experiment model usage must be ModelRoleUsage")
    if type(required) is not bool:
        raise TypeError("experiment model required must be boolean")
    if type(member_index) is not int or member_index < 0:
        raise ValueError("experiment model member_index must be non-negative")
    return structure_unit(
        f"{role}:{member_index}",
        traits=(EXPERIMENT_MODEL_ROLE_TRAIT,),
        parameters={
            "role": role,
            "requirement_id": requirement_id,
            "model_definition_digest": model_definition_digest,
            "model_id": model_id,
            "binding_digest": binding_digest,
            "prompt_generation_id": prompt_generation_id,
            "prompt_digest": prompt_digest,
            "capabilities": capabilities,
            "usage": usage.value,
            "required": required,
            "member_index": member_index,
        },
    )


def require_experiment_model_role(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(EXPERIMENT_MODEL_ROLE_TRAIT):
        raise TypeError("experiment model role must be NoetriumUnit")
    return value


def experiment_model_role_role(value: NoetriumUnit) -> str:
    return str(require_experiment_model_role(value).parameters["role"])


def experiment_model_role_usage(value: NoetriumUnit) -> ModelRoleUsage:
    return ModelRoleUsage(str(require_experiment_model_role(value).parameters["usage"]))


def experiment_model_role_member_index(value: NoetriumUnit) -> int:
    return int(require_experiment_model_role(value).parameters["member_index"])


def experiment_unit(
    experiment_id: str,
    *,
    study_id: str,
    project_id: str,
    participants: tuple[NoetriumUnit, ...],
    model_roles: tuple[NoetriumUnit, ...],
    workload_digest: str,
    seed_digest: str,
    repetitions: int,
    trial_protocol_id: str,
    trial_protocol_configuration_digest: str,
) -> NoetriumUnit:
    experiment_id = _text(experiment_id, "experiment_id")
    study_id = _text(study_id, "experiment study_id")
    project_id = _text(project_id, "experiment project_id")
    if type(participants) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(EXPERIMENT_PARTICIPANT_TRAIT)
        for row in participants
    ):
        raise TypeError("experiment participants must be participant Units")
    if type(model_roles) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(EXPERIMENT_MODEL_ROLE_TRAIT)
        for row in model_roles
    ):
        raise TypeError("experiment model roles must be model-role Units")
    if len({experiment_participant_role(row) for row in participants}) != len(participants):
        raise ValueError("experiment participant roles must be unique")
    ordered_models = tuple(sorted(model_roles, key=lambda row: (
        experiment_model_role_role(row), experiment_model_role_member_index(row)
    )))
    if len({(experiment_model_role_role(row), experiment_model_role_member_index(row)) for row in ordered_models}) != len(ordered_models):
        raise ValueError("experiment model role members must be unique")
    require_sha256(workload_digest, "experiment workload_digest")
    require_sha256(seed_digest, "experiment seed_digest")
    if type(repetitions) is not int or repetitions <= 0:
        raise ValueError("experiment repetitions must be positive")
    _text(trial_protocol_id, "experiment trial_protocol_id")
    require_sha256(trial_protocol_configuration_digest, "experiment trial protocol digest")
    return structure_unit(
        experiment_id,
        traits=(EXPERIMENT_TRAIT,),
        parameters={
            "experiment_id": experiment_id,
            "study_id": study_id,
            "project_id": project_id,
            "workload_digest": workload_digest,
            "seed_digest": seed_digest,
            "repetitions": repetitions,
            "trial_protocol_id": trial_protocol_id,
            "trial_protocol_configuration_digest": trial_protocol_configuration_digest,
        },
        members=tuple(sorted(participants, key=experiment_participant_role)) + ordered_models,
    )


def require_experiment_unit(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(EXPERIMENT_TRAIT):
        raise TypeError("experiment must be research.experiment NoetriumUnit")
    return value


def experiment_value(value: NoetriumUnit, name: str):
    return require_experiment_unit(value).parameters[name]


def experiment_id(value: NoetriumUnit) -> str:
    return str(experiment_value(value, "experiment_id"))


def experiment_study_id(value: NoetriumUnit) -> str:
    return str(experiment_value(value, "study_id"))


def experiment_project_id(value: NoetriumUnit) -> str:
    return str(experiment_value(value, "project_id"))


def experiment_participants(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(row for row in require_experiment_unit(value).members if row.has_trait(EXPERIMENT_PARTICIPANT_TRAIT))


def experiment_model_roles(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(row for row in require_experiment_unit(value).members if row.has_trait(EXPERIMENT_MODEL_ROLE_TRAIT))


def experiment_identity_digest(value: NoetriumUnit) -> str:
    return require_experiment_unit(value).unit_digest


def experiment_model_roles_digest(value: NoetriumUnit) -> str:
    return structure_unit(
        "model-role-digest-view",
        traits=("noetrium.digest-view",),
        members=experiment_model_roles(value),
    ).semantic_digest


def metric_predicate_unit(path: tuple[str, ...], equals: JsonValue) -> NoetriumUnit:
    if type(path) is not tuple or not path or any(type(row) is not str or not row.strip() for row in path):
        raise TypeError("metric predicate path must be non-empty text tuple")
    return structure_unit(
        "predicate:" + ".".join(path),
        traits=(METRIC_PREDICATE_TRAIT,),
        parameters={"path": path, "equals": freeze_json(equals)},
    )


def metric_definition_unit(
    metric_id: str,
    *,
    aggregation: str,
    record_types: tuple[str, ...] = (),
    schema_ids: tuple[str, ...] = (),
    value_path: tuple[str, ...] = (),
    group_by: tuple[tuple[str, ...], ...] = (),
    predicates: tuple[NoetriumUnit, ...] = (),
    missing: str = "skip",
    unit: str | None = None,
    description: str = "",
) -> NoetriumUnit:
    metric_id = _text(metric_id, "metric_id")
    aggregation = _text(aggregation, "metric aggregation")
    if aggregation != "count" and not value_path:
        raise ValueError("non-count metric requires value_path")
    if type(predicates) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(METRIC_PREDICATE_TRAIT)
        for row in predicates
    ):
        raise TypeError("metric predicates must be Unit tuple")
    return structure_unit(
        metric_id,
        traits=(METRIC_DEFINITION_TRAIT,),
        parameters={
            "aggregation": aggregation,
            "record_types": record_types,
            "schema_ids": schema_ids,
            "value_path": value_path,
            "group_by": group_by,
            "missing": _text(missing, "metric missing policy"),
            "unit": unit,
            "description": description,
        },
        members=predicates,
    )


def require_metric_definition(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(METRIC_DEFINITION_TRAIT):
        raise TypeError("metric definition must be research.metric NoetriumUnit")
    return value


def metric_definition_value(value: NoetriumUnit, name: str):
    return require_metric_definition(value).parameters[name]


def metric_id(value: NoetriumUnit) -> str:
    return require_metric_definition(value).unit_id


def metric_aggregation(value: NoetriumUnit) -> str:
    return str(metric_definition_value(value, "aggregation"))


def metric_predicates(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(require_metric_definition(value).members)


def metric_definition_digest(value: NoetriumUnit) -> str:
    return require_metric_definition(value).unit_digest


EVALUATION_TRAIT = "research.evaluation"


def posthoc_evaluation_unit(
    evaluation_id: str,
    *,
    evaluator_id: str,
    evaluator_version: str,
    implementation_digest: str,
    configuration_digest: str,
    source_execution_digest: str,
    input_cut_digest: str,
    output_protocol: NoetriumUnit,
    model_roles: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    evaluation_id = _text(evaluation_id, "evaluation_id")
    evaluator_id = _text(evaluator_id, "evaluator_id")
    evaluator_version = _text(evaluator_version, "evaluator_version")
    for name, digest in (
        ("implementation_digest", implementation_digest),
        ("configuration_digest", configuration_digest),
        ("source_execution_digest", source_execution_digest),
        ("input_cut_digest", input_cut_digest),
    ):
        require_sha256(digest, f"evaluation {name}")
    if type(output_protocol) is not NoetriumUnit or not output_protocol.has_trait("noetrium.measurement-protocol"):
        raise TypeError("evaluation output protocol must be measurement protocol Unit")
    if type(model_roles) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(EXPERIMENT_MODEL_ROLE_TRAIT)
        for row in model_roles
    ):
        raise TypeError("evaluation model roles must be model-role Units")
    ordered = tuple(sorted(model_roles, key=lambda row: (
        experiment_model_role_role(row),
        experiment_model_role_member_index(row),
    )))
    if any(not experiment_model_role_usage(row).affects_evaluation for row in ordered):
        raise ValueError("post-hoc evaluation accepts only evaluation-capable model roles")
    return structure_unit(
        evaluation_id,
        traits=(EVALUATION_TRAIT,),
        parameters={
            "evaluator_id": evaluator_id,
            "evaluator_version": evaluator_version,
            "implementation_digest": implementation_digest,
            "configuration_digest": configuration_digest,
            "source_execution_digest": source_execution_digest,
            "input_cut_digest": input_cut_digest,
            "output_protocol_semantic_digest": output_protocol.semantic_digest,
        },
        members=(output_protocol,) + ordered,
    )


def evaluation_model_roles_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(EVALUATION_TRAIT):
        raise TypeError("evaluation must be research.evaluation NoetriumUnit")
    roles = tuple(row for row in value.members if row.has_trait(EXPERIMENT_MODEL_ROLE_TRAIT))
    return canonical_digest(tuple(row.unit_digest for row in roles))


__all__ = [name for name in globals() if name.startswith((
    "experiment_", "metric_", "posthoc_", "evaluation_", "require_"
))]
