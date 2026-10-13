from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from enum import StrEnum
from functools import lru_cache
import math
from typing import Self

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    NoetriumUnit,
    structure_topological_order,
)
from noetrium_platform.research.execution.api import ArtifactReference

from .benchmark import (
    TASK_VERTEX_TRAIT,
    TaskRelation,
    task_graph,
    task_vertex,
    task_vertex_id,
    task_graph_key,
    task_graph_relation_kind,
    task_graph_relation_source_id,
    task_graph_relation_target_id,
    validate_task_graph,
)


def _require_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _require_nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _require_finite_number(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _require_string_tuple(
    value: object, field: str, *, non_empty: bool, unique: bool
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"{field} must contain non-empty strings")
    if non_empty and not value:
        raise ValueError(f"{field} must be non-empty")
    if unique and len(value) != len(set(value)):
        raise ValueError(f"{field} must be unique")
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    return require_sha256(value, field)


class VariantKind(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"
    ABLATION = "ablation"
    EXTERNAL_BASELINE = "external_baseline"


STUDY_VARIANT_TRAIT = "experiment.study.variant"

def study_variant_graph(*, variant_id: str, kind: VariantKind, implementation_id: str, configuration_digest: str | None = None, configuration: object = None, budget_tier: str | None = None, ablates: tuple[str, ...] = ()) -> NoetriumUnit:
    _require_non_empty_string(variant_id, "study variant variant_id")
    if not isinstance(kind, VariantKind): raise TypeError("study variant kind must be VariantKind")
    _require_non_empty_string(implementation_id, "study variant implementation_id")
    digest = canonical_digest(configuration) if configuration_digest is None else configuration_digest
    _require_sha256(digest, "study variant configuration_digest")
    if budget_tier is not None: _require_non_empty_string(budget_tier, "study variant budget_tier")
    _require_string_tuple(ablates, "study variant ablates", non_empty=False, unique=True)
    return structure_unit(variant_id, traits=(STUDY_VARIANT_TRAIT,), parameters={"kind":kind.value,"implementation_id":implementation_id,"configuration_digest":digest,"budget_tier":budget_tier,"ablates":ablates})

def study_variant_kind(variant: NoetriumUnit) -> VariantKind:
    _require_study_variant(variant); return VariantKind(str(variant.parameters["kind"]))
def study_variant_implementation_id(variant: NoetriumUnit) -> str:
    _require_study_variant(variant); return str(variant.parameters["implementation_id"])
def study_variant_configuration_digest(variant: NoetriumUnit) -> str:
    _require_study_variant(variant); return str(variant.parameters["configuration_digest"])
def study_variant_budget_tier(variant: NoetriumUnit) -> str | None:
    _require_study_variant(variant); value=variant.parameters.get("budget_tier"); return None if value is None else str(value)
def study_variant_ablates(variant: NoetriumUnit) -> tuple[str, ...]:
    _require_study_variant(variant); return tuple(str(v) for v in variant.parameters.get("ablates", ()))
def _require_study_variant(variant: NoetriumUnit) -> None:
    if type(variant) is not NoetriumUnit or not variant.has_trait(STUDY_VARIANT_TRAIT): raise TypeError("study variant must be experiment.study.variant NoetriumUnit")


STUDY_VARIANT_SPACE_TRAIT = "study.variant-space"

def _require_variant_space(value: object) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(STUDY_VARIANT_SPACE_TRAIT):
        raise TypeError("study protocol variant_space must be study.variant-space NoetriumUnit")
    count = value.parameters.get("variant_count")
    if type(count) is not int or count <= 0:
        raise ValueError("study variant space requires positive variant_count")
    _require_non_empty_string(
        value.parameters.get("implementation_id"),
        "study variant space implementation_id",
    )
    budget_tier = value.parameters.get("budget_tier")
    if budget_tier is not None:
        _require_non_empty_string(budget_tier, "study variant space budget_tier")
    return value


STUDY_PROTOCOL_TRAIT = "study.protocol"

def study_protocol(
    *,
    study_id: str,
    workload_id: str,
    variant_space: NoetriumUnit,
    repetitions: int,
    seed_schedule_digest: str,
    metric_names: tuple[str, ...],
    task_manifest_digest: str,
    assignment_workloads: tuple[NoetriumUnit, ...],
    budget_tiers: tuple[str, ...],
    assignment_relations: tuple[tuple[int, int, str], ...] = (),
) -> NoetriumUnit:
    _require_non_empty_string(study_id, "study protocol study_id")
    _require_non_empty_string(workload_id, "study protocol workload_id")
    variant_space = _require_variant_space(variant_space)
    _require_positive_int(repetitions, "study protocol repetitions")
    _require_sha256(seed_schedule_digest, "study protocol seed_schedule_digest")
    _require_sha256(task_manifest_digest, "study protocol task_manifest_digest")
    _require_string_tuple(metric_names, "study protocol metric_names", non_empty=False, unique=True)
    _require_string_tuple(budget_tiers, "study protocol budget_tiers", non_empty=False, unique=True)
    budget_tier = variant_space.parameters.get("budget_tier")
    if budget_tier is not None and budget_tier not in budget_tiers:
        raise ValueError("study variant space uses undeclared budget tier")
    if type(assignment_workloads) is not tuple or not assignment_workloads:
        raise TypeError("study protocol assignment_workloads must be non-empty tuple")
    for workload in assignment_workloads:
        validate_assignment_workload(workload)
    if len({assignment_workload_digest(row) for row in assignment_workloads}) != len(assignment_workloads):
        raise ValueError("study protocol assignment workloads must be unique")
    if len(set(assignment_relations)) != len(assignment_relations):
        raise ValueError("duplicate Study assignment relation")
    for source, target, relation in assignment_relations:
        if (type(source) is not int or type(target) is not int
            or not (0 <= source < target < len(assignment_workloads))
            or relation != "sequence_after"):
            raise ValueError("Study assignment dependency must be forward sequence_after")
    members = (
        structure_unit(
            "variant-space",
            traits=("study.protocol.variant-space",),
            members=(variant_space,),
        ),
    ) + tuple(
        structure_unit(
            f"workload:{index}",
            traits=("study.protocol.workload",),
            members=(workload,),
        )
        for index, workload in enumerate(assignment_workloads)
    )
    return structure_unit(
        "study-protocol:" + canonical_digest(study_id)[:20],
        traits=(STUDY_PROTOCOL_TRAIT,),
        parameters={
            "study_id": study_id,
            "workload_id": workload_id,
            "repetitions": repetitions,
            "seed_schedule_digest": seed_schedule_digest,
            "metric_names": metric_names,
            "task_manifest_digest": task_manifest_digest,
            "budget_tiers": budget_tiers,
            "variant_count": int(variant_space.parameters["variant_count"]),
            "variant_space_digest": variant_space.unit_digest,
            "workload_count": len(assignment_workloads),
            "assignment_relations": assignment_relations,
        },
        members=members,
    )

def require_study_protocol(g: NoetriumUnit) -> NoetriumUnit:
    if type(g) is not NoetriumUnit or not g.has_trait(STUDY_PROTOCOL_TRAIT):
        raise TypeError("study protocol must be NoetriumUnit")
    return g

def study_protocol_variant_space(g: NoetriumUnit) -> NoetriumUnit:
    require_study_protocol(g)
    space = g.member("variant-space").members[0]
    _require_variant_space(space)
    if space.unit_digest != g.parameters["variant_space_digest"]:
        raise ValueError("study protocol variant space digest drifted")
    if int(space.parameters["variant_count"]) != int(g.parameters["variant_count"]):
        raise ValueError("study protocol variant count drifted")
    return space

def study_protocol_variant_count(g: NoetriumUnit) -> int:
    return int(study_protocol_variant_space(g).parameters["variant_count"])

def study_protocol_workloads(g: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    require_study_protocol(g)
    n = int(g.parameters["workload_count"])
    return tuple(g.member(f"workload:{i}").members[0] for i in range(n))


def study_protocol_assignment_relations(g: NoetriumUnit) -> tuple[tuple[int, int, str], ...]:
    require_study_protocol(g)
    return tuple(tuple(row) for row in g.parameters.get("assignment_relations", ()))

def study_protocol_text(g: NoetriumUnit, name: str) -> str:
    require_study_protocol(g)
    return str(g.parameters[name])

def study_protocol_repetitions(g: NoetriumUnit) -> int:
    require_study_protocol(g)
    return int(g.parameters["repetitions"])

def study_protocol_metric_names(g: NoetriumUnit) -> tuple[str, ...]:
    require_study_protocol(g)
    return tuple(str(x) for x in g.parameters["metric_names"])

def study_protocol_digest(g: NoetriumUnit) -> str:
    require_study_protocol(g)
    return g.semantic_digest


ASSIGNMENT_WORKLOAD_CACHED_LOOKUP_COMPLEXITY = ComplexityContract(
    algorithm_id="experiment.assignment-workload.cached-lookup.v2",
    implementation_digest=canonical_digest(
        (
            "experiment.assignment-workload.cached-lookup.v2",
            "precompiled-exact-source-queries",
        )
    ),
    time_upper_bound=ComplexityBound.constant(),
    space_upper_bound=ComplexityBound.constant(),
    assumptions=(
        "the immutable assignment workload derived index has already been compiled",
        "the requested task identity is one exact key",
    ),
    time_lower_bound=ComplexityBound.constant(),
    space_lower_bound=ComplexityBound.constant(),
)


ASSIGNMENT_WORKLOAD_TRAIT = "experiment.assignment-workload"


def _assignment_dependency_relation_ids(
    workload: NoetriumUnit,
) -> tuple[str, ...]:
    dependency_kinds = {
        TaskRelation.PREREQUISITE,
        TaskRelation.RETRY_OF,
        TaskRelation.SEQUENCE_AFTER,
    }
    return tuple(
        sorted(
            {
                relation.relation_id
                for relation in workload.relations
                if task_graph_relation_kind(relation) in dependency_kinds
            }
        )
    )


def assignment_workload(
    task_ids: tuple[str, ...],
    graph: NoetriumUnit | None = None,
) -> NoetriumUnit:
    task_ids = _require_string_tuple(
        task_ids,
        "assignment workload task_ids",
        non_empty=True,
        unique=True,
    )
    task_relations = task_graph() if graph is None else graph
    validate_task_graph(task_relations)
    known = set(task_ids)
    # validate_task_graph() has already proven relation parameters and endpoint
    # identities agree. Re-entering public source/target accessors here would
    # recompute the same task-key hashes once per edge.
    for relation in task_relations.relations:
        parameters = relation.parameters
        source_task_id = str(parameters["source_task_id"])
        target_task_id = str(parameters["target_task_id"])
        if source_task_id not in known or target_task_id not in known:
            raise ValueError(
                "assignment workload graph references task outside workload"
            )
    workload_identity = canonical_digest({
        "task_ids": tuple(sorted(task_ids)),
        "relations": tuple(sorted(
            relation.semantic_digest for relation in task_relations.relations
        )),
    })
    graph_vertices = {
        task_vertex_id(vertex): vertex
        for vertex in task_relations.members
    }
    workload = structure_unit(
        f"assignment-workload:{workload_identity}",
        traits=(ASSIGNMENT_WORKLOAD_TRAIT,),
        members=tuple(
            graph_vertices[task_id]
            if task_id in graph_vertices
            else task_vertex(task_id)
            for task_id in task_ids
        ),
        relations=task_relations.relations,
        semantic_projection_digest=workload_identity,
    )
    validate_assignment_workload(workload)
    return workload


def validate_assignment_workload(workload: NoetriumUnit) -> tuple[str, ...]:
    if (
        type(workload) is not NoetriumUnit
        or not workload.has_trait(ASSIGNMENT_WORKLOAD_TRAIT)
    ):
        raise TypeError(
            "assignment workload must be an "
            "experiment.assignment-workload NoetriumUnit"
        )
    return _validated_assignment_workload_order(workload)


@lru_cache(maxsize=4096)
def _validated_assignment_workload_order(
    workload: NoetriumUnit,
) -> tuple[str, ...]:
    """Compile immutable assignment graph semantics once per graph identity."""
    if not workload.members:
        raise ValueError("assignment workload requires at least one task graph")
    if any(
        not child.has_trait(TASK_VERTEX_TRAIT)
        for child in workload.members
    ):
        raise TypeError(
            "assignment workload children must have experiment.task trait"
        )
    for child in workload.members:
        task_vertex_id(child)
    for relation in workload.relations:
        task_graph_relation_kind(relation)
    by_local_id = {
        child.unit_id: task_vertex_id(child)
        for child in workload.members
    }
    try:
        local_order = structure_topological_order(
            workload,
            _assignment_dependency_relation_ids(workload),
        )
        return tuple(by_local_id[local_id] for local_id in local_order)
    except (KeyError, ValueError) as exc:
        raise ValueError(
            "assignment workload dependency graph must be acyclic"
        ) from exc


@lru_cache(maxsize=4096)
def _assignment_workload_order_index(
    workload: NoetriumUnit,
) -> Mapping[str, int]:
    order = validate_assignment_workload(workload)
    return MappingProxyType(
        {task_id: index for index, task_id in enumerate(order)}
    )


@lru_cache(maxsize=4096)
def _assignment_workload_source_index(
    workload: NoetriumUnit,
) -> Mapping[tuple[str, TaskRelation], tuple[str, ...]]:
    order_index = _assignment_workload_order_index(workload)
    rows: dict[tuple[str, TaskRelation], set[str]] = {}
    for relation in workload.relations:
        source = task_graph_relation_source_id(relation)
        target = task_graph_relation_target_id(relation)
        kind = task_graph_relation_kind(relation)
        rows.setdefault((target, kind), set()).add(source)
    return MappingProxyType(
        {
            key: tuple(sorted(values, key=order_index.__getitem__))
            for key, values in rows.items()
        }
    )


@lru_cache(maxsize=4096)
def _assignment_workload_dependency_index(
    workload: NoetriumUnit,
) -> Mapping[str, tuple[str, ...]]:
    """Precompile the exact union queried by dependency lookups."""

    order_index = _assignment_workload_order_index(workload)
    source_index = _assignment_workload_source_index(workload)
    rows: dict[str, set[str]] = {}
    for (task_id, kind), sources in source_index.items():
        if kind not in {
            TaskRelation.PREREQUISITE,
            TaskRelation.RETRY_OF,
            TaskRelation.SEQUENCE_AFTER,
        }:
            continue
        rows.setdefault(task_id, set()).update(sources)
    return MappingProxyType(
        {
            task_id: tuple(sorted(sources, key=order_index.__getitem__))
            for task_id, sources in rows.items()
        }
    )


def assignment_workload_task_ids(
    workload: NoetriumUnit,
) -> tuple[str, ...]:
    return validate_assignment_workload(workload)


def assignment_workload_digest(workload: NoetriumUnit) -> str:
    validate_assignment_workload(workload)
    return workload.unit_digest


def assignment_workload_task_index(
    workload: NoetriumUnit,
    task_id: str,
) -> int:
    try:
        return _assignment_workload_order_index(workload)[task_id]
    except KeyError as exc:
        raise KeyError(
            f"assignment workload has no task {task_id!r}"
        ) from exc


def _require_assignment_task(
    workload: NoetriumUnit,
    task_id: str,
) -> None:
    if task_id not in _assignment_workload_order_index(workload):
        raise KeyError(
            f"assignment workload has no task {task_id!r}"
        )


def assignment_workload_dependencies_for(
    workload: NoetriumUnit,
    task_id: str,
) -> tuple[str, ...]:
    _require_assignment_task(workload, task_id)
    return _assignment_workload_dependency_index(workload).get(task_id, ())


def assignment_workload_prerequisites_for(
    workload: NoetriumUnit,
    task_id: str,
) -> tuple[str, ...]:
    _require_assignment_task(workload, task_id)
    return _assignment_workload_source_index(workload).get(
        (task_id, TaskRelation.PREREQUISITE),
        (),
    )


def assignment_workload_retry_sources_for(
    workload: NoetriumUnit,
    task_id: str,
) -> tuple[str, ...]:
    _require_assignment_task(workload, task_id)
    return _assignment_workload_source_index(workload).get(
        (task_id, TaskRelation.RETRY_OF),
        (),
    )


STUDY_ASSIGNMENT_TRAIT = "study.assignment"

def study_assignment(
    study_id: str,
    variant_id: str,
    variant_index: int,
    repetition: int,
    seed: str,
    workload: NoetriumUnit,
) -> NoetriumUnit:
    _require_non_empty_string(study_id, "study assignment study_id")
    _require_non_empty_string(variant_id, "study assignment variant_id")
    _require_nonnegative_int(variant_index, "study assignment variant_index")
    _require_nonnegative_int(repetition, "study assignment repetition")
    _require_non_empty_string(seed, "study assignment seed")
    validate_assignment_workload(workload)
    return structure_unit(
        "assignment:"
        + canonical_digest(
            (study_id, variant_id, variant_index, repetition, seed, workload.unit_digest)
        )[:20],
        traits=(STUDY_ASSIGNMENT_TRAIT,),
        parameters={
            "study_id": study_id,
            "variant_id": variant_id,
            "variant_index": variant_index,
            "repetition": repetition,
            "seed": seed,
        },
        members=(workload,),
    )

def require_study_assignment(g: NoetriumUnit)->NoetriumUnit:
    if type(g) is not NoetriumUnit or not g.has_trait(STUDY_ASSIGNMENT_TRAIT): raise TypeError("study assignment must be NoetriumUnit")
    return g
def study_assignment_text(g:NoetriumUnit,name:str)->str: require_study_assignment(g); return str(g.parameters[name])
def study_assignment_variant_index(g: NoetriumUnit) -> int:
    require_study_assignment(g)
    return int(g.parameters["variant_index"])

def study_assignment_repetition(g:NoetriumUnit)->int: require_study_assignment(g); return int(g.parameters["repetition"])
def study_assignment_workload(g:NoetriumUnit)->NoetriumUnit: require_study_assignment(g); return g.members[0]
def study_assignment_digest(g:NoetriumUnit)->str: require_study_assignment(g); return g.semantic_digest


def _require_assignments(value: object) -> tuple[NoetriumUnit, ...]:
    if type(value) is not tuple:
        raise TypeError("study execution unit assignments must be a tuple")
    if not value:
        raise ValueError("study execution unit assignments must be non-empty")
    if any(not type(item) is NoetriumUnit and item.has_trait(STUDY_ASSIGNMENT_TRAIT) for item in value):
        raise TypeError("study execution unit assignments must contain StudyAssignment")
    return value


def _require_unit_assignment_identity(
    study_id: str, repetition: int, assignments: tuple[NoetriumUnit, ...]
) -> tuple[str, ...]:
    if any(study_assignment_text(item, "study_id") != study_id for item in assignments):
        raise ValueError("study execution unit contains another study")
    if any(study_assignment_repetition(item) != repetition for item in assignments):
        raise ValueError("study execution unit mixes repetitions")
    digests = tuple(study_assignment_digest(item) for item in assignments)
    if len(digests) != len(set(digests)):
        raise ValueError("study execution unit contains duplicate assignments")
    return digests


@dataclass(frozen=True, slots=True)
class StudyExecutionUnit:
    """One reproducible repetition group passed to an environment adapter."""

    study_id: str
    repetition: int
    assignments: tuple[NoetriumUnit, ...]
    unit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study execution unit study_id")
        _require_nonnegative_int(self.repetition, "study execution unit repetition")
        assignments = _require_assignments(self.assignments)
        digests = _require_unit_assignment_identity(
            self.study_id, self.repetition, assignments
        )
        object.__setattr__(self, "unit_digest", canonical_digest({
            "study_id": self.study_id,
            "repetition": self.repetition,
            "assignments": digests,
        }))


def _require_report_items(value: object, item_type: type, field: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"study matrix report {field} must be a tuple")
    if any(not isinstance(item, item_type) for item in value):
        raise TypeError(
            f"study matrix report {field} must contain {item_type.__name__}"
        )


@dataclass(frozen=True, slots=True)
class StudyMatrixExecutionReport:
    """Complete observations and aggregates for one frozen study matrix."""

    protocol_digest: str
    observations: tuple["StudyMetricObservation", ...]
    aggregates: tuple["StudyMetricAggregate", ...]
    binding_digest: str
    plan_digest: str

    def __post_init__(self) -> None:
        _require_sha256(self.protocol_digest, "study matrix report protocol_digest")
        _require_report_items(self.observations, StudyMetricObservation, "observations")
        _require_report_items(self.aggregates, StudyMetricAggregate, "aggregates")
        _require_sha256(self.binding_digest, "study matrix report binding_digest")
        _require_sha256(self.plan_digest, "study matrix report plan_digest")


def _require_metric_rows(value: object) -> tuple[tuple[str, float], ...]:
    if type(value) is not tuple:
        raise TypeError("study metric observation metrics must be a tuple")
    if not value:
        raise ValueError("study metric observation requires at least one metric")
    names: list[str] = []
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("study metric observation metric rows must be pairs")
        name, metric_value = row
        _require_non_empty_string(name, "study metric observation metric name")
        _require_finite_number(metric_value, f"study metric observation {name}")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("study metric observation requires unique metrics")
    return value


@dataclass(frozen=True, slots=True)
class StudyMetricObservation:
    assignment: NoetriumUnit
    metrics: tuple[tuple[str, float], ...]
    trial_request_digest: str | None = None
    trial_receipt_digest: str | None = None
    trial_receipt_reference: ArtifactReference | None = None
    measurement_record_digests: tuple[str, ...] = ()
    evidence_refs: tuple[ArtifactReference, ...] = ()
    verifier_receipt_digest: str | None = None
    unobserved_metric_names: tuple[str, ...] = ()
    observation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.assignment) is not NoetriumUnit or not self.assignment.has_trait(STUDY_ASSIGNMENT_TRAIT):
            raise TypeError("study metric observation assignment must be StudyAssignment")
        _require_metric_rows(self.metrics)
        missing = self.unobserved_metric_names
        if (type(missing) is not tuple or len(missing) != len(set(missing))
            or any(type(name) is not str or not name for name in missing)
            or set(missing) & {name for name, _ in self.metrics}):
            raise ValueError("study unobserved metric identities must be disjoint and unique")
        if missing and self.trial_receipt_digest is None:
            raise ValueError("study unobserved metrics require authoritative Trial receipt")
        provenance_fields = (
            self.trial_request_digest,
            self.trial_receipt_digest,
            self.trial_receipt_reference,
        )
        has_provenance = any(value is not None for value in provenance_fields)
        if has_provenance and any(value is None for value in provenance_fields):
            raise ValueError(
                "study metric observation Trial provenance must carry request, receipt and reference together"
            )
        if self.trial_request_digest is not None:
            _require_sha256(
                self.trial_request_digest,
                "study metric observation trial_request_digest",
            )
            _require_sha256(
                self.trial_receipt_digest,
                "study metric observation trial_receipt_digest",
            )
            if type(self.trial_receipt_reference) is not ArtifactReference:
                raise TypeError(
                    "study metric observation trial_receipt_reference must be ArtifactReference"
                )
        if type(self.measurement_record_digests) is not tuple:
            raise TypeError(
                "study metric observation measurement_record_digests must be tuple"
            )
        for digest in self.measurement_record_digests:
            _require_sha256(
                digest,
                "study metric observation measurement_record_digest",
            )
        if len(self.measurement_record_digests) != len(
            set(self.measurement_record_digests)
        ):
            raise ValueError(
                "study metric observation measurement_record_digests must be unique"
            )
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError(
                "study metric observation evidence_refs must contain ArtifactReference"
            )
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError(
                "study metric observation evidence_refs must be unique"
            )
        if self.verifier_receipt_digest is not None:
            _require_sha256(
                self.verifier_receipt_digest,
                "study metric observation verifier_receipt_digest",
            )
        if not has_provenance and (
            self.measurement_record_digests
            or self.evidence_refs
            or self.verifier_receipt_digest is not None
        ):
            raise ValueError(
                "study metric observation Trial-derived provenance requires a Trial receipt reference"
            )
        object.__setattr__(
            self,
            "observation_digest",
            canonical_digest(
                {
                    "assignment_digest": study_assignment_digest(self.assignment),
                    "metrics": self.metrics,
                    "unobserved_metric_names": self.unobserved_metric_names,
                    "trial_request_digest": self.trial_request_digest,
                    "trial_receipt_digest": self.trial_receipt_digest,
                    "trial_receipt_reference": self.trial_receipt_reference,
                    "measurement_record_digests": self.measurement_record_digests,
                    "evidence_refs": self.evidence_refs,
                    "verifier_receipt_digest": self.verifier_receipt_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class StudyMetricAggregate:
    study_id: str
    variant_id: str
    metric_name: str
    count: int
    mean: float
    sample_variance: float
    standard_error: float

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study aggregate study_id")
        _require_non_empty_string(self.variant_id, "study aggregate variant_id")
        _require_non_empty_string(self.metric_name, "study aggregate metric_name")
        _require_positive_int(self.count, "study aggregate count")
        _require_finite_number(self.mean, "study aggregate mean")
        variance = _require_finite_number(
            self.sample_variance, "study aggregate sample_variance"
        )
        error = _require_finite_number(
            self.standard_error, "study aggregate standard_error"
        )
        if variance < 0 or error < 0:
            raise ValueError("study aggregate variance and standard error cannot be negative")


__all__ = [
     "STUDY_VARIANT_SPACE_TRAIT", "STUDY_PROTOCOL_TRAIT", "STUDY_ASSIGNMENT_TRAIT", "study_protocol", "require_study_protocol", "study_protocol_variant_space", "study_protocol_variant_count", "study_protocol_workloads", "study_protocol_text", "study_protocol_repetitions", "study_protocol_metric_names", "study_protocol_digest", "study_assignment", "require_study_assignment", "study_assignment_text", "study_assignment_variant_index", "study_assignment_repetition", "study_assignment_workload", "study_assignment_digest",
    "assignment_workload",
    "assignment_workload_digest",
    "assignment_workload_task_ids",
    "assignment_workload_task_index",
    "assignment_workload_dependencies_for",
    "assignment_workload_prerequisites_for",
    "assignment_workload_retry_sources_for",
    "validate_assignment_workload",
    "StudyExecutionUnit",
    "StudyMatrixExecutionReport",
    "StudyMetricAggregate",
    "StudyMetricObservation",
    "STUDY_VARIANT_TRAIT",
    "study_variant_graph",
    "study_variant_kind",
    "study_variant_implementation_id",
    "study_variant_configuration_digest",
    "study_variant_budget_tier",
    "study_variant_ablates",
    "VariantKind",
]
