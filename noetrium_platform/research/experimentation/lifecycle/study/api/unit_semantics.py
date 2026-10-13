"""Unit-only Study semantics over the single NoetriumUnit carrier."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, require_sha256, thaw_json
from noetrium_platform.foundation.kernel.structure import EMPTY_BOUNDARY, NoetriumUnit, structure_unit
from noetrium_platform.research.execution.api import ArtifactReference
from noetrium_platform.research.experimentation.binding import (
    binding_requirements,
    binding_requirements_participants,
    model_role_requirement,
    participant_requirement,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel
from noetrium_platform.research.execution.api import (
    PARTICIPANT_DEPENDENCY_RELATION,
    participant_dependency,
    participant_graph,
    participant_relation,
)
from .contracts import assignment_workload, assignment_workload_digest, assignment_workload_task_ids
from .benchmark import (
    TaskRelation,
    TaskGraphInterner,
    task_graph as build_task_graph,
    task_graph_from_edges as build_task_graph_from_edges,
    task_graph_key,
    task_graph_relation,
    task_graph_relation_kind,
    task_graph_relation_source_id,
    task_graph_relation_target_id,
)

ARTIFACT_REFERENCE_BINDING_TRAIT = "noetrium.artifact-reference-binding"
TASK_TRAIT = "research.task"
SPLIT_TRAIT = "research.split"
BENCHMARK_TRAIT = "research.benchmark"
MEASUREMENT_TRAIT = "research.measurement"
MEASUREMENT_PROTOCOL_TRAIT = "noetrium.measurement-protocol"
FACTOR_TRAIT = "research.factor"
FACTOR_LEVEL_TRAIT = "noetrium.factor-level"
TRIAL_PROTOCOL_TRAIT = "noetrium.trial-protocol"
TRIAL_BUDGET_TRAIT = "noetrium.trial-budget"
EXECUTION_POLICY_TRAIT = "noetrium.study-execution-policy"
REVISION_TRAIT = "noetrium.research-revision"
STUDY_TRAIT = "research.study"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    return value


def _member_by_trait(unit: NoetriumUnit, trait: str, field: str) -> NoetriumUnit:
    rows = tuple(row for row in unit.members if row.has_trait(trait))
    if len(rows) != 1:
        raise ValueError(f"{field} requires exactly one {trait} Unit")
    return rows[0]


def _artifact_reference_binding_unit(reference: ArtifactReference) -> NoetriumUnit:
    if type(reference) is not ArtifactReference:
        raise TypeError("artifact reference binding requires ArtifactReference")
    return structure_unit(
        "artifact-reference:" + canonical_digest({
            "reference_id": reference.reference_id,
            "scope_digest": reference.scope.unit_digest,
            "artifact_id": reference.artifact_id,
            "generation": reference.generation,
        })[:32],
        traits=(ARTIFACT_REFERENCE_BINDING_TRAIT,),
        parameters={
            "reference_id": reference.reference_id,
            "artifact_id": reference.artifact_id,
            "generation": reference.generation,
        },
        members=(reference.scope,),
    )


def _artifact_reference_from_binding(binding: NoetriumUnit) -> ArtifactReference:
    if type(binding) is not NoetriumUnit or not binding.has_trait(ARTIFACT_REFERENCE_BINDING_TRAIT):
        raise TypeError("artifact reference binding must be NoetriumUnit")
    if len(binding.members) != 1:
        raise ValueError("artifact reference binding requires exactly one scope Unit")
    return ArtifactReference(
        str(binding.parameters["reference_id"]),
        binding.members[0],
        str(binding.parameters["artifact_id"]),
        int(binding.parameters["generation"]),
    )


def task_unit(
    task_id: str,
    *,
    revision_id: str,
    family: str,
    schema_id: str,
    content_digest: str | None,
    content: Mapping[str, JsonValue] | None = None,
    content_reference: ArtifactReference | None = None,
    lineage_refs: tuple[str, ...] = (),
    package: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    task_id = _text(task_id, "task_id")
    revision_id = _text(revision_id, "task revision_id")
    family = _text(family, "task family")
    schema_id = _text(schema_id, "task schema_id")
    frozen_content = None if content is None else freeze_json(content)
    if content_digest is None:
        if frozen_content is None:
            raise ValueError("task requires content_digest when inline content is absent")
        content_digest = canonical_digest(frozen_content)
    else:
        require_sha256(content_digest, "task content_digest")
        if frozen_content is not None and canonical_digest(frozen_content) != content_digest:
            raise ValueError("inline task content digest mismatch")
    if content_reference is not None and type(content_reference) is not ArtifactReference:
        raise TypeError("task content_reference must be ArtifactReference or None")
    if type(lineage_refs) is not tuple or any(type(row) is not str or not row.strip() for row in lineage_refs):
        raise TypeError("task lineage_refs must be text tuple")
    if len(lineage_refs) != len(set(lineage_refs)):
        raise ValueError("task lineage_refs must be unique")
    frozen_package = None
    package_digest = None
    if package is not None:
        if not isinstance(package, Mapping):
            raise TypeError("task package must be a mapping")
        package_payload = dict(package)
        supplied_digest = package_payload.pop("package_digest", None)
        package_digest = canonical_digest(package_payload)
        if supplied_digest is not None and supplied_digest != package_digest:
            raise ValueError("task package digest mismatch")
        package_payload["package_digest"] = package_digest
        frozen_package = freeze_json(package_payload)

    binding_members = (
        ()
        if content_reference is None
        else (_artifact_reference_binding_unit(content_reference),)
    )
    semantic = canonical_digest({
        "schema": "noetrium.research.task.semantic.v2",
        "task_id": task_id,
        "revision_id": revision_id,
        "family": family,
        "schema_id": schema_id,
        "content_digest": content_digest,
        "lineage_refs": lineage_refs,
        "package_digest": package_digest,
    })
    parameters = MappingProxyType({
        "task_id": task_id,
        "revision_id": revision_id,
        "family": family,
        "schema_id": schema_id,
        "content_digest": content_digest,
        "content": frozen_content,
        "lineage_refs": lineage_refs,
        "package": frozen_package,
    })
    return NoetriumUnit._from_normalized(
        task_graph_key(task_id),
        schemas=(TASK_TRAIT,),
        attributes=MappingProxyType({
            "kind": "structure",
            "parameters": parameters,
            "symbol_ids": (),
        }),
        roles=(
            ("atom", ()),
            ("boundary", (EMPTY_BOUNDARY,)),
            ("member", binding_members),
            ("relation", ()),
            ("symbol", ()),
        ),
        semantic_projection_digest=semantic,
    )


def require_task_unit(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(TASK_TRAIT):
        raise TypeError("task must be research.task NoetriumUnit")
    return value


def task_id(value: NoetriumUnit) -> str:
    value = require_task_unit(value)
    semantic_id = _text(value.parameters["task_id"], "task semantic task_id")
    if value.unit_id != task_graph_key(semantic_id):
        raise ValueError("task local Unit identity drifted from semantic task_id")
    return semantic_id


def task_family(value: NoetriumUnit) -> str:
    return str(require_task_unit(value).parameters["family"])


def task_content(value: NoetriumUnit):
    return require_task_unit(value).parameters["content"]


def task_content_digest(value: NoetriumUnit) -> str:
    return str(require_task_unit(value).parameters["content_digest"])


def task_content_reference(value: NoetriumUnit) -> ArtifactReference | None:
    task = require_task_unit(value)
    rows = tuple(
        row for row in task.members
        if row.has_trait(ARTIFACT_REFERENCE_BINDING_TRAIT)
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("task has multiple content-reference bindings")
    return _artifact_reference_from_binding(rows[0])


def verify_task_content(value: NoetriumUnit, references, artifacts) -> None:
    reference = task_content_reference(value)
    if reference is None:
        return
    resolved = references.resolve(reference.reference_id, reference.scope)
    if resolved != reference:
        raise ValueError("task content reference generation drift")
    record = artifacts.get(reference.artifact_id)
    if record.scope != reference.scope or record.digest != task_content_digest(value):
        raise ValueError("task content reference does not match immutable content")


def task_lineage_refs(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(require_task_unit(value).parameters["lineage_refs"])


def task_objective(value: NoetriumUnit) -> str:
    content = task_content(value)
    if not isinstance(content, Mapping):
        raise ValueError("task requires inline content for objective projection")
    objective = content.get("objective", content.get("goal"))
    if type(objective) is not str or not objective.strip():
        raise ValueError(f"task {task_id(value)!r} requires objective or goal")
    return objective.strip()


def task_context(value: NoetriumUnit) -> str:
    content = task_content(value)
    if not isinstance(content, Mapping):
        return ""
    context = content.get("context", "")
    if type(context) is not str:
        raise TypeError("task context must be text")
    return context


def task_lineage_id(value: NoetriumUnit) -> str:
    lineage = task_lineage_refs(value)
    return lineage[0] if lineage else task_id(value)


def task_max_steps(value: NoetriumUnit) -> int | None:
    content = task_content(value)
    if not isinstance(content, Mapping):
        return None
    raw = content.get("max_steps")
    if raw is None:
        return None
    if type(raw) is not int or raw <= 0:
        raise ValueError("task max_steps must be positive integer or None")
    return raw


def task_max_seconds(value: NoetriumUnit) -> float | None:
    content = task_content(value)
    if not isinstance(content, Mapping):
        return None
    raw = content.get("max_seconds")
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or float(raw) <= 0:
        raise ValueError("task max_seconds must be positive numeric or None")
    return float(raw)


def task_payload(value: NoetriumUnit):
    return task_content(value)


def task_field(value: NoetriumUnit, name: str):
    if name == "task_id":
        return task_id(value)
    if name == "family":
        return task_family(value)
    if name == "objective":
        return task_objective(value)
    if name == "context":
        return task_context(value)
    if name == "lineage_id":
        return task_lineage_id(value)
    if name == "max_steps":
        return task_max_steps(value)
    if name == "max_seconds":
        return task_max_seconds(value)
    if name == "payload":
        return task_payload(value)
    raise KeyError(f"unknown task semantic field: {name}")


def task_package(value: NoetriumUnit):
    return require_task_unit(value).parameters.get("package")


def split_unit(split_id: str, task_ids: tuple[str, ...]) -> NoetriumUnit:
    split_id = _text(split_id, "split_id")
    if type(task_ids) is not tuple or not task_ids or any(type(row) is not str or not row.strip() for row in task_ids):
        raise TypeError("split task_ids must be non-empty text tuple")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("split task_ids must be unique")
    return structure_unit(split_id, traits=(SPLIT_TRAIT,), parameters={"task_ids": task_ids})


def split_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(SPLIT_TRAIT):
        raise TypeError("split must be research.split NoetriumUnit")
    return value.unit_id


def split_task_ids(value: NoetriumUnit) -> tuple[str, ...]:
    if type(value) is not NoetriumUnit or not value.has_trait(SPLIT_TRAIT):
        raise TypeError("split must be research.split NoetriumUnit")
    return tuple(str(row) for row in value.parameters["task_ids"])


def benchmark_unit(
    benchmark_id: str,
    *,
    revision_id: str,
    source_digest: str,
    task_schema_id: str,
    tasks: tuple[NoetriumUnit, ...],
    source_reference: ArtifactReference | None = None,
    task_graph: NoetriumUnit | None = None,
    splits: tuple[NoetriumUnit, ...] = (),
    selection_policy_digest: str = "",
) -> NoetriumUnit:
    benchmark_id = _text(benchmark_id, "benchmark_id")
    revision_id = _text(revision_id, "benchmark revision_id")
    task_schema_id = _text(task_schema_id, "benchmark task_schema_id")
    require_sha256(source_digest, "benchmark source_digest")
    if selection_policy_digest:
        require_sha256(selection_policy_digest, "benchmark selection_policy_digest")
    if source_reference is not None and type(source_reference) is not ArtifactReference:
        raise TypeError("benchmark source_reference must be ArtifactReference or None")
    if type(tasks) is not tuple or not tasks:
        raise TypeError("benchmark tasks must be non-empty tuple")
    if task_graph is None:
        task_graph = build_task_graph()
    if type(task_graph) is not NoetriumUnit or not task_graph.has_trait("experiment.task-graph"):
        raise TypeError("benchmark task_graph must be experiment.task-graph NoetriumUnit")
    for row in tasks:
        require_task_unit(row)
    ordered_tasks = tuple(sorted(tasks, key=task_id))
    ids = tuple(task_id(row) for row in ordered_tasks)
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark task ids must be unique")
    if type(splits) is not tuple or any(type(row) is not NoetriumUnit or not row.has_trait(SPLIT_TRAIT) for row in splits):
        raise TypeError("benchmark splits must be research.split Unit tuple")
    ordered_splits = tuple(sorted(splits, key=split_id))
    known = set(ids)
    for row in ordered_splits:
        if not set(split_task_ids(row)).issubset(known):
            raise ValueError("benchmark split references unknown task")
    params = {
        "revision_id": revision_id,
        "source_digest": source_digest,
        "task_schema_id": task_schema_id,
        "selection_policy_digest": selection_policy_digest,
    }
    scientific_members = ordered_tasks + ordered_splits + (task_graph,)
    semantic_base = structure_unit(
        benchmark_id,
        traits=(BENCHMARK_TRAIT,),
        parameters=params,
        members=scientific_members,
    )
    exact_members = scientific_members + (
        ()
        if source_reference is None
        else (_artifact_reference_binding_unit(source_reference),)
    )
    return structure_unit(
        benchmark_id,
        traits=(BENCHMARK_TRAIT,),
        parameters=params,
        members=exact_members,
        semantic_projection_digest=semantic_base.semantic_digest,
    )


def benchmark_cut_unit(
    benchmark_id: str,
    revision_id: str,
    source_digest: str,
    task_schema_id: str,
    tasks: tuple[NoetriumUnit, ...],
    *,
    source_reference: ArtifactReference | None = None,
    splits: tuple[NoetriumUnit, ...] = (),
    task_graph: NoetriumUnit | None = None,
    selection_policy: Mapping[str, JsonValue] | None = None,
    selection_policy_digest: str | None = None,
) -> NoetriumUnit:
    if selection_policy is not None and selection_policy_digest is not None:
        raise ValueError(
            "benchmark cut accepts selection_policy or selection_policy_digest, not both"
        )
    if selection_policy is not None:
        frozen = freeze_json(selection_policy)
        if not isinstance(frozen, Mapping):
            raise TypeError("benchmark selection_policy must be an object")
        policy_digest = canonical_digest(frozen)
    elif selection_policy_digest is not None:
        require_sha256(selection_policy_digest, "benchmark selection_policy_digest")
        policy_digest = selection_policy_digest
    else:
        policy_digest = ""
    return benchmark_unit(
        benchmark_id,
        revision_id=revision_id,
        source_digest=source_digest,
        task_schema_id=task_schema_id,
        tasks=tasks,
        source_reference=source_reference,
        task_graph=task_graph,
        splits=splits,
        selection_policy_digest=policy_digest,
    )


def require_benchmark_unit(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(BENCHMARK_TRAIT):
        raise TypeError("benchmark must be research.benchmark NoetriumUnit")
    return value


def benchmark_tasks(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    require_benchmark_unit(value)
    return tuple(row for row in value.members if row.has_trait(TASK_TRAIT))


def benchmark_splits(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    require_benchmark_unit(value)
    return tuple(row for row in value.members if row.has_trait(SPLIT_TRAIT))


def benchmark_id(value: NoetriumUnit) -> str:
    return require_benchmark_unit(value).unit_id


def benchmark_cut_digest(value: NoetriumUnit) -> str:
    return require_benchmark_unit(value).unit_digest


def benchmark_task_graph(value: NoetriumUnit) -> NoetriumUnit:
    benchmark = require_benchmark_unit(value)
    rows = tuple(
        row for row in benchmark.members
        if row.has_trait("experiment.task-graph")
    )
    if len(rows) != 1:
        raise ValueError("benchmark requires exactly one task graph")
    return rows[0]


def benchmark_source_reference(value: NoetriumUnit) -> ArtifactReference | None:
    benchmark = require_benchmark_unit(value)
    rows = tuple(
        row for row in benchmark.members
        if row.has_trait(ARTIFACT_REFERENCE_BINDING_TRAIT)
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("benchmark has multiple source-reference bindings")
    return _artifact_reference_from_binding(rows[0])


def verify_benchmark_source(value: NoetriumUnit, references, artifacts) -> None:
    reference = benchmark_source_reference(value)
    if reference is None:
        return
    resolved = references.resolve(reference.reference_id, reference.scope)
    if resolved != reference:
        raise ValueError("benchmark source reference generation drift")
    record = artifacts.get(reference.artifact_id)
    if record.scope != reference.scope or record.digest != benchmark_source_digest(value):
        raise ValueError("benchmark source reference does not match immutable content")


def benchmark_selection_policy_digest(value: NoetriumUnit) -> str:
    return str(require_benchmark_unit(value).parameters["selection_policy_digest"])


def benchmark_revision_id(value: NoetriumUnit) -> str:
    return str(require_benchmark_unit(value).parameters["revision_id"])


def benchmark_source_digest(value: NoetriumUnit) -> str:
    return str(require_benchmark_unit(value).parameters["source_digest"])


def benchmark_task_schema_id(value: NoetriumUnit) -> str:
    return str(require_benchmark_unit(value).parameters["task_schema_id"])


def benchmark_selected_tasks(value: NoetriumUnit, split_id: str | None = None) -> tuple[NoetriumUnit, ...]:
    tasks = benchmark_tasks(value)
    if split_id is None:
        return tasks
    rows = tuple(row for row in benchmark_splits(value) if row.unit_id == split_id)
    if len(rows) != 1:
        raise KeyError(f"benchmark has no unique split {split_id!r}")
    by_id = {task_id(row): row for row in tasks}
    return tuple(by_id[str(item)] for item in rows[0].parameters["task_ids"])


def benchmark_split_projection_unit(
    value: NoetriumUnit,
    split_id: str,
) -> NoetriumUnit:
    """Project one exact split into a self-contained immutable Benchmark Unit.

    Source identity is preserved while selection identity binds the parent cut.
    Task-graph edges are induced over the selected task ids; cross-split edges
    are rejected because silently dropping an external prerequisite would alter
    task semantics.
    """
    benchmark = require_benchmark_unit(value)
    selected = benchmark_selected_tasks(benchmark, split_id)
    selected_ids = {task_id(row) for row in selected}
    source_graph = benchmark_task_graph(benchmark)
    projected_edges = []
    for relation in source_graph.relations:
        source = task_graph_relation_source_id(relation)
        target = task_graph_relation_target_id(relation)
        source_selected = source in selected_ids
        target_selected = target in selected_ids
        if source_selected != target_selected:
            raise ValueError(
                "benchmark split projection crosses a task-graph boundary: "
                f"{source!r}->{target!r}"
            )
        if source_selected:
            projected_edges.append((source, target, task_graph_relation_kind(relation)))
    projected_graph = build_task_graph_from_edges(tuple(projected_edges))
    source_split = tuple(
        row for row in benchmark_splits(benchmark) if split_id == row.unit_id
    )
    if len(source_split) != 1:
        raise KeyError(f"benchmark has no unique split {split_id!r}")
    parent_selection = benchmark_selection_policy_digest(benchmark)
    projection_policy = canonical_digest({
        "schema": "noetrium.benchmark-split-projection.v1",
        "parent_cut_digest": benchmark_cut_digest(benchmark),
        "parent_selection_policy_digest": parent_selection,
        "split_id": split_id,
        "task_ids": tuple(task_id(row) for row in selected),
    })
    return benchmark_cut_unit(
        benchmark_id(benchmark),
        benchmark_revision_id(benchmark),
        benchmark_source_digest(benchmark),
        benchmark_task_schema_id(benchmark),
        selected,
        task_graph=projected_graph,
        splits=(split_unit(split_id, tuple(task_id(row) for row in selected)),),
        selection_policy_digest=projection_policy,
    )


def benchmark_authoring_mapping(value: NoetriumUnit) -> Mapping[str, JsonValue]:
    """Lossless inline transport for one immutable Benchmark Unit.

    This is not a second benchmark carrier: the mapping includes the expected
    Unit cut digest and Study authoring revalidates the round trip. Artifact-
    referenced task/source content is rejected until an explicit reference
    transport is available.
    """
    benchmark = require_benchmark_unit(value)
    if benchmark_source_reference(benchmark) is not None:
        raise ValueError("benchmark authoring transport requires inline source authority")
    tasks = []
    for task in benchmark_tasks(benchmark):
        if task_content_reference(task) is not None:
            raise ValueError("benchmark authoring transport requires inline task content")
        content = task_content(task)
        if not isinstance(content, Mapping):
            raise ValueError("benchmark authoring transport requires inline task content")
        package = task_package(task)
        tasks.append({
            "task_id": task_id(task),
            "revision_id": str(task.parameters["revision_id"]),
            "family": task_family(task),
            "schema_id": str(task.parameters["schema_id"]),
            "content_digest": task_content_digest(task),
            "content": thaw_json(content),
            "lineage_refs": task_lineage_refs(task),
            "package": None if package is None else thaw_json(package),
        })
    graph = benchmark_task_graph(benchmark)
    edges = tuple({
        "source": task_graph_relation_source_id(relation),
        "target": task_graph_relation_target_id(relation),
        "relation": task_graph_relation_kind(relation).value,
    } for relation in graph.relations)
    payload = {
        "benchmark_id": benchmark_id(benchmark),
        "revision_id": benchmark_revision_id(benchmark),
        "source_digest": benchmark_source_digest(benchmark),
        "task_schema_id": benchmark_task_schema_id(benchmark),
        "tasks": tuple(tasks),
        "splits": tuple({
            "split_id": split_id(row),
            "task_ids": split_task_ids(row),
        } for row in benchmark_splits(benchmark)),
        "task_graph": {"edges": edges},
        "selection_policy_digest": benchmark_selection_policy_digest(benchmark),
        "cut_digest": benchmark_cut_digest(benchmark),
    }
    frozen = freeze_json(payload)
    if not isinstance(frozen, Mapping):
        raise TypeError("benchmark authoring transport did not freeze to an object")
    return frozen


def measurement_unit(
    measurement_id: str,
    *,
    schema_id: str,
    value_kind: str,
    unit: str | None = None,
    description: str = "",
    semantic_kind: str = "measurement",
    scale: str | None = None,
    domain: str | None = None,
    source_path: str | None = None,
    reducer: str | None = None,
) -> NoetriumUnit:
    measurement_id = _text(measurement_id, "measurement_id")
    schema_id = _text(schema_id, "measurement schema_id")
    value_kind = _text(value_kind, "measurement value_kind")
    semantic_kind = _text(semantic_kind, "measurement semantic_kind")
    if value_kind not in {
        "scalar", "boolean", "categorical", "structured", "sequence",
        "distribution", "matrix", "text_judgement", "content_reference",
    }:
        raise ValueError(f"unsupported measurement value_kind: {value_kind!r}")
    for name, value in (("unit", unit), ("scale", scale), ("domain", domain)):
        if value is not None:
            _text(value, f"measurement {name}")
    if source_path is not None:
        _text(source_path, "measurement source_path")
        if any(not part for part in source_path.split(".")):
            raise ValueError("measurement source_path must be canonical dotted path")
    if reducer is not None:
        _text(reducer, "measurement reducer")
        if reducer not in {"sum", "mean", "last", "min", "max", "all", "any", "series"}:
            raise ValueError("unsupported measurement reducer")
        if source_path is None:
            raise ValueError("measurement reducer requires source_path")
    if type(description) is not str:
        raise TypeError("measurement description must be text")

    parameters = {
        "schema_id": schema_id,
        "value_kind": value_kind,
        "unit": unit,
        "description": description,
        "semantic_kind": semantic_kind,
        "scale": scale,
        "domain": domain,
        "source_path": source_path,
        "reducer": reducer,
    }
    semantic = canonical_digest({
        "measurement_id": measurement_id,
        "schema_id": schema_id,
        "semantic_kind": semantic_kind,
        "value_kind": value_kind,
        "unit": unit,
        "scale": scale,
        "domain": domain,
        "source_path": source_path,
        "reducer": reducer,
    })
    return structure_unit(
        measurement_id,
        traits=(MEASUREMENT_TRAIT,),
        parameters=parameters,
        semantic_projection_digest=semantic,
    )


def measurement_protocol_unit(
    protocol_id: str,
    definitions: tuple[NoetriumUnit, ...],
    *,
    schema_version: str = "measurement.protocol.v1",
) -> NoetriumUnit:
    if type(definitions) is not tuple or not definitions:
        raise TypeError("measurement protocol requires definitions")
    if any(type(row) is not NoetriumUnit or not row.has_trait(MEASUREMENT_TRAIT) for row in definitions):
        raise TypeError("measurement definitions must be measurement Units")
    ordered = tuple(sorted(definitions, key=lambda row: row.unit_id))
    if len({row.unit_id for row in ordered}) != len(ordered):
        raise ValueError("measurement ids must be unique")
    return structure_unit(
        _text(protocol_id, "measurement protocol_id"),
        traits=(MEASUREMENT_PROTOCOL_TRAIT,),
        parameters={"schema_version": _text(schema_version, "measurement schema_version")},
        members=ordered,
    )


def measurement_definitions(protocol: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    if type(protocol) is not NoetriumUnit or not protocol.has_trait(MEASUREMENT_PROTOCOL_TRAIT):
        raise TypeError("measurement protocol must be NoetriumUnit")
    return tuple(protocol.members)


def measurement_scalar_names(protocol: NoetriumUnit) -> tuple[str, ...]:
    return tuple(row.unit_id for row in measurement_definitions(protocol) if str(row.parameters["value_kind"]) == "scalar")


def factor_level_unit(level_id: str, value: JsonValue, *, control: bool = False) -> NoetriumUnit:
    if type(control) is not bool:
        raise TypeError("factor level control must be boolean")
    return structure_unit(
        _text(level_id, "factor level_id"),
        traits=(FACTOR_LEVEL_TRAIT,),
        parameters={"value": freeze_json(value), "control": control},
    )


def factor_unit(factor_id: str, levels: tuple[NoetriumUnit, ...]) -> NoetriumUnit:
    if type(levels) is not tuple or not levels:
        raise TypeError("factor requires levels")
    if any(type(row) is not NoetriumUnit or not row.has_trait(FACTOR_LEVEL_TRAIT) for row in levels):
        raise TypeError("factor levels must be Unit")
    if sum(bool(row.parameters["control"]) for row in levels) > 1:
        raise ValueError("factor may declare at most one control")
    return structure_unit(
        _text(factor_id, "factor_id"),
        traits=(FACTOR_TRAIT,),
        members=tuple(sorted(levels, key=lambda row: row.unit_id)),
    )


def trial_protocol_unit(protocol_id: str, configuration_digest: str) -> NoetriumUnit:
    require_sha256(configuration_digest, "trial configuration_digest")
    return structure_unit(
        _text(protocol_id, "trial protocol_id"),
        traits=(TRIAL_PROTOCOL_TRAIT,),
        parameters={"configuration_digest": configuration_digest},
    )


def trial_budget_unit(value: Mapping[str, object]) -> NoetriumUnit:
    budget_id = _text(value["budget_id"], "trial budget_id")
    params = {key: value.get(key) for key in (
        "max_steps", "max_seconds", "max_tokens", "resource_budget_digest",
        "max_turns", "max_messages", "max_model_calls", "max_working_seconds", "max_cost_usd",
    )}
    return structure_unit(budget_id, traits=(TRIAL_BUDGET_TRAIT,), parameters=params)


def execution_policy_unit(
    *,
    replay_level: ReplayLevel,
    environment_session_scope: str,
    environment_seed_scope: str,
    trial_budget: NoetriumUnit | None = None,
) -> NoetriumUnit:
    if not isinstance(replay_level, ReplayLevel):
        raise TypeError("replay_level must be ReplayLevel")
    environment_session_scope = _text(
        environment_session_scope, "environment session scope"
    )
    environment_seed_scope = _text(
        environment_seed_scope, "environment seed scope"
    )
    return structure_unit(
        "execution-policy",
        traits=(EXECUTION_POLICY_TRAIT,),
        parameters={
            "replay_level": replay_level.value,
            "environment_session_scope": environment_session_scope,
            "environment_seed_scope": environment_seed_scope,
        },
        members=() if trial_budget is None else (trial_budget,),
    )


def execution_policy_budget(policy: NoetriumUnit) -> NoetriumUnit | None:
    if type(policy) is not NoetriumUnit or not policy.has_trait(EXECUTION_POLICY_TRAIT):
        raise TypeError("execution policy must be Unit")
    rows = tuple(row for row in policy.members if row.has_trait(TRIAL_BUDGET_TRAIT))
    if len(rows) > 1:
        raise ValueError("multiple trial budgets")
    return None if not rows else rows[0]


def execution_policy_replay_level(policy: NoetriumUnit) -> ReplayLevel:
    return ReplayLevel(str(policy.parameters["replay_level"]))


def revision_unit(revision_id: str, change_digest: str, parent_revision_digest: str | None = None) -> NoetriumUnit:
    require_sha256(change_digest, "revision change_digest")
    if parent_revision_digest is not None:
        require_sha256(parent_revision_digest, "revision parent digest")
    return structure_unit(
        _text(revision_id, "revision_id"),
        traits=(REVISION_TRAIT,),
        parameters={"change_digest": change_digest, "parent_revision_digest": parent_revision_digest},
    )


def study_unit(
    *,
    project_id: str,
    experiment_id: str,
    study_id_value: str,
    workload_id: str,
    factors: tuple[NoetriumUnit, ...],
    seeds: tuple[str, ...],
    repetitions: int,
    measurement_protocol: NoetriumUnit,
    benchmark: NoetriumUnit,
    benchmark_split_id: str | None,
    assignment_workloads: tuple[NoetriumUnit, ...],
    assignment_relations: tuple[tuple[int, int, str], ...] = (),
    binding_requirements_unit: NoetriumUnit,
    trial_protocol: NoetriumUnit,
    revision: NoetriumUnit | None,
    execution_policy: NoetriumUnit,
) -> NoetriumUnit:
    project_id = _text(project_id, "study project_id")
    experiment_id = _text(experiment_id, "study experiment_id")
    study_id_value = _text(study_id_value, "study_id")
    workload_id = _text(workload_id, "study workload_id")
    if type(seeds) is not tuple or not seeds or any(type(seed) is not str or not seed.strip() for seed in seeds):
        raise TypeError("study seeds must be non-empty text tuple")
    if len(seeds) != len(set(seeds)):
        raise ValueError("study seeds must be unique")
    if type(repetitions) is not int or isinstance(repetitions, bool) or repetitions <= 0:
        raise ValueError("study repetitions must be a positive integer")
    selected_ids = {task_id(row) for row in benchmark_selected_tasks(benchmark, benchmark_split_id)}
    workload_ids = {task for workload in assignment_workloads for task in assignment_workload_task_ids(workload)}
    if workload_ids != selected_ids:
        raise ValueError("assignment workloads must exactly cover benchmark cut")
    workload_order = tuple(assignment_workload_digest(w) for w in assignment_workloads)
    if len(workload_order) != len(set(workload_order)):
        raise ValueError("Study assignment workload identities must be unique")
    if len(assignment_relations) != len(set(assignment_relations)):
        raise ValueError("duplicate Study assignment relation")
    for source, target, relation in assignment_relations:
        if (type(source) is not int or type(target) is not int
            or not (0 <= source < target < len(assignment_workloads))
            or relation != "sequence_after"):
            raise ValueError("Study assignment relations require forward sequence_after edges")
    members = (
        tuple(sorted(factors, key=lambda row: row.unit_id))
        + (measurement_protocol, benchmark)
        + assignment_workloads
        + (binding_requirements_unit, trial_protocol, execution_policy)
        + (() if revision is None else (revision,))
    )
    return structure_unit(
        study_id_value,
        traits=(STUDY_TRAIT,),
        parameters={
            "project_id": project_id,
            "experiment_id": experiment_id,
            "study_id": study_id_value,
            "workload_id": workload_id,
            "seeds": seeds,
            "repetitions": repetitions,
            "benchmark_split_id": benchmark_split_id,
            "assignment_workload_order": workload_order,
            "assignment_relations": assignment_relations,
        },
        members=members,
    )


def require_study_unit(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(STUDY_TRAIT):
        raise TypeError("Study definition must be research.study NoetriumUnit")
    return value


def study_value(value: NoetriumUnit, name: str):
    return require_study_unit(value).parameters[name]


def study_project_id(value: NoetriumUnit) -> str: return str(study_value(value, "project_id"))
def study_experiment_id(value: NoetriumUnit) -> str: return str(study_value(value, "experiment_id"))
def study_id(value: NoetriumUnit) -> str: return str(study_value(value, "study_id"))
def study_workload_id(value: NoetriumUnit) -> str: return str(study_value(value, "workload_id"))
def study_seeds(value: NoetriumUnit) -> tuple[str, ...]: return tuple(study_value(value, "seeds"))
def study_repetitions(value: NoetriumUnit) -> int: return int(study_value(value, "repetitions"))
def study_benchmark_split_id(value: NoetriumUnit) -> str | None:
    raw = study_value(value, "benchmark_split_id")
    return None if raw is None else str(raw)
def study_factors(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]: return tuple(row for row in require_study_unit(value).members if row.has_trait(FACTOR_TRAIT))
def study_measurement_protocol(value: NoetriumUnit) -> NoetriumUnit: return _member_by_trait(value, MEASUREMENT_PROTOCOL_TRAIT, "study")
def study_benchmark(value: NoetriumUnit) -> NoetriumUnit: return _member_by_trait(value, BENCHMARK_TRAIT, "study")
def study_assignment_workloads(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    study = require_study_unit(value)
    # Unit members are canonical *sets*, not an ordered scientific sequence.
    # The declared workload order is an independent and binding Study truth.
    declared = tuple(study.parameters["assignment_workload_order"])
    workloads = tuple(
        row for row in study.members
        if row.has_trait("experiment.assignment-workload")
    )
    by_digest = {assignment_workload_digest(row): row for row in workloads}
    if (len(by_digest) != len(workloads)
        or len(declared) != len(by_digest)
        or set(declared) != set(by_digest)):
        raise ValueError("Study workload order does not match owned workload Units")
    return tuple(by_digest[digest] for digest in declared)
def study_assignment_relations(value: NoetriumUnit) -> tuple[tuple[int, int, str], ...]:
    return tuple(tuple(row) for row in require_study_unit(value).parameters.get("assignment_relations", ()))
def study_binding_requirements(value: NoetriumUnit) -> NoetriumUnit: return _member_by_trait(value, "noetrium.binding-requirements", "study")
def study_trial_protocol(value: NoetriumUnit) -> NoetriumUnit: return _member_by_trait(value, TRIAL_PROTOCOL_TRAIT, "study")
def study_execution_policy(value: NoetriumUnit) -> NoetriumUnit: return _member_by_trait(value, EXECUTION_POLICY_TRAIT, "study")
def study_revision(value: NoetriumUnit) -> NoetriumUnit | None:
    rows = tuple(row for row in require_study_unit(value).members if row.has_trait(REVISION_TRAIT))
    if len(rows) > 1: raise ValueError("multiple revisions")
    return None if not rows else rows[0]



def study_with_measurement_protocol(
    value: NoetriumUnit,
    protocol: NoetriumUnit,
) -> NoetriumUnit:
    """Return the same immutable Study semantics with one replacement measurement protocol."""

    study = require_study_unit(value)
    if type(protocol) is not NoetriumUnit or not protocol.has_trait(MEASUREMENT_PROTOCOL_TRAIT):
        raise TypeError("study replacement measurement protocol must be NoetriumUnit")
    return study_unit(
        project_id=study_project_id(study),
        experiment_id=study_experiment_id(study),
        study_id_value=study_id(study),
        workload_id=study_workload_id(study),
        factors=study_factors(study),
        seeds=study_seeds(study),
        repetitions=study_repetitions(study),
        measurement_protocol=protocol,
        benchmark=study_benchmark(study),
        benchmark_split_id=study_benchmark_split_id(study),
        assignment_workloads=study_assignment_workloads(study),
        assignment_relations=study_assignment_relations(study),
        binding_requirements_unit=study_binding_requirements(study),
        trial_protocol=study_trial_protocol(study),
        revision=study_revision(study),
        execution_policy=study_execution_policy(study),
    )

def study_scientific_design_digest(value: NoetriumUnit) -> str:
    return canonical_digest({
        "project_id": study_project_id(value),
        "experiment_id": study_experiment_id(value),
        "study_id": study_id(value),
        "workload_id": study_workload_id(value),
        "factors": tuple(row.unit_digest for row in study_factors(value)),
        "seeds": study_seeds(value),
        "repetitions": study_repetitions(value),
        "measurement_semantics": study_measurement_protocol(value).unit_digest,
        "benchmark_cut": study_benchmark(value).unit_digest,
        "benchmark_split_id": study_benchmark_split_id(value),
        "assignment_workloads": tuple(assignment_workload_digest(row) for row in study_assignment_workloads(value)),
        "assignment_relations": study_assignment_relations(value),
        "trial_protocol": study_trial_protocol(value).unit_digest,
    })


def study_participant_design_digest(value: NoetriumUnit) -> str:
    return canonical_digest(tuple(row.unit_digest for row in binding_requirements_participants(study_binding_requirements(value))))


def study_binding_requirement_digest(value: NoetriumUnit) -> str: return study_binding_requirements(value).unit_digest
def study_execution_policy_digest(value: NoetriumUnit) -> str: return study_execution_policy(value).unit_digest
def study_definition_digest(value: NoetriumUnit) -> str: return require_study_unit(value).unit_digest


class StudySpecCompiler:
    """One execution-scoped compiler for immutable declarative Study specs.

    Repeated scientific sub-specifications are hash-consed by canonical content
    digest. The cache is owned by one execution-authority materialization, so it
    has no global retention policy and cannot leak across independent runs.
    """

    __slots__ = ("task_graphs", "_units")

    def __init__(self) -> None:
        self.task_graphs = TaskGraphInterner()
        self._units: dict[tuple[str, str], NoetriumUnit] = {}

    def memo_unit(self, namespace: str, spec: object, factory) -> NoetriumUnit:
        key = (namespace, canonical_digest(spec))
        cached = self._units.get(key)
        if cached is not None:
            return cached
        unit = factory()
        if type(unit) is not NoetriumUnit:
            raise TypeError("StudySpecCompiler factory must return NoetriumUnit")
        existing = self._units.setdefault(key, unit)
        if existing.unit_digest != unit.unit_digest:
            raise RuntimeError(
                "canonical Study sub-spec resolved to multiple Unit identities"
            )
        return existing


def _task_graph_from_spec(
    value: object,
    compiler: StudySpecCompiler | None = None,
) -> NoetriumUnit:
    if value is None:
        return build_task_graph()
    row = _mapping(value, "task graph")
    edges = tuple(
        (
            str(edge["source_task_id"]),
            str(edge["target_task_id"]),
            TaskRelation(str(edge.get("relation", "prerequisite"))),
        )
        for edge in (_mapping(item, "task graph edge") for item in row.get("edges", ()))
    )
    if compiler is None:
        return build_task_graph_from_edges(edges)
    return compiler.task_graphs.build(edges)


def study_unit_from_spec(
    value: object,
    *,
    compiler: StudySpecCompiler | None = None,
) -> NoetriumUnit:
    row = _mapping(value, "research study spec")
    compiler = StudySpecCompiler() if compiler is None else compiler
    if not isinstance(compiler, StudySpecCompiler):
        raise TypeError("study compiler must be StudySpecCompiler")
    raw_benchmark = row["benchmark"]
    if type(raw_benchmark) is NoetriumUnit:
        benchmark = require_benchmark_unit(raw_benchmark)
    else:
        b = _mapping(raw_benchmark, "research study benchmark")
        revision_id = str(b["revision_id"])
        task_schema_id = str(b["task_schema_id"])
        tasks = []
        for raw in b["tasks"]:
            t = _mapping(raw, "benchmark task")
            content = t.get("content")
            content_digest = t.get("content_digest")
            if content_digest is None and not isinstance(content, Mapping):
                raise ValueError("task requires inline content when digest omitted")
            tasks.append(task_unit(
                str(t["task_id"]),
                revision_id=str(t.get("revision_id", revision_id)),
                family=str(t["family"]),
                schema_id=str(t.get("schema_id", task_schema_id)),
                content_digest=None if content_digest is None else str(content_digest),
                content=content if isinstance(content, Mapping) else None,
                lineage_refs=tuple(t.get("lineage_refs", ())),
                package=t.get("package") if isinstance(t.get("package"), Mapping) else None,
            ))
        source_digest = b.get("source_digest")
        if source_digest is None:
            source_digest = canonical_digest({
                "benchmark_id": str(b["benchmark_id"]),
                "revision_id": revision_id,
                "task_schema_id": task_schema_id,
                "tasks": tuple((task_id(t), t.parameters["content_digest"]) for t in tasks),
            })
        splits = tuple(
            split_unit(str(split["split_id"]), tuple(split["task_ids"]))
            for split in (_mapping(item, "benchmark split") for item in b.get("splits", ()))
        )
        benchmark = benchmark_unit(
            str(b["benchmark_id"]), revision_id=revision_id, source_digest=str(source_digest),
            task_schema_id=task_schema_id, tasks=tuple(tasks),
            task_graph=_task_graph_from_spec(b.get("task_graph"), compiler), splits=splits,
            selection_policy_digest=str(b.get("selection_policy_digest", "")),
        )
        expected_cut_digest = b.get("cut_digest")
        if expected_cut_digest is not None:
            require_sha256(str(expected_cut_digest), "benchmark authoring cut_digest")
            if benchmark_cut_digest(benchmark) != str(expected_cut_digest):
                raise ValueError(
                    "benchmark authoring transport did not round-trip exact cut identity"
                )
    measurements = tuple(
        compiler.memo_unit(
            "measurement",
            m,
            lambda m=m: measurement_unit(
                str(m["measurement_id"]), schema_id=str(m["schema_id"]),
                value_kind=str(m.get("value_kind", "scalar")), unit=m.get("unit"),
                description=str(m.get("description", "")),
                semantic_kind=str(m.get("semantic_kind", "measurement")),
                scale=m.get("scale"), domain=m.get("domain"),
                source_path=m.get("source_path"), reducer=m.get("reducer"),
            ),
        )
        for m in (_mapping(item, "measurement") for item in row["measurements"])
    )
    measurement_protocol = measurement_protocol_unit(f"{row['study_id']}.measurements", measurements)

    participant_rows = (row["method"],) + tuple(row.get("participants", ()))
    participants = tuple(
        participant_requirement(
            str(p["role"]), str(p["kind"]), str(p["implementation"]), str(p["treatment"]),
            capability_requirement_ids=tuple(p.get("capabilities", ())),
            configuration_ref_ids=tuple(p.get("configurations", ())),
        )
        for p in (_mapping(item, "study participant") for item in participant_rows)
    )
    roles = tuple(str(p.parameters["role"]) for p in participants)
    topo_raw = row.get("participant_topology")

    def build_participant_topology() -> NoetriumUnit:
        if topo_raw is None:
            return participant_graph(roles)
        topo = _mapping(topo_raw, "participant topology")
        topology_edges = []
        for edge in (
            _mapping(item, "participant topology edge")
            for item in topo.get("edges", ())
        ):
            semantic = str(
                edge.get("relation", PARTICIPANT_DEPENDENCY_RELATION)
            )
            if "sources" in edge or "targets" in edge:
                sources = tuple(str(value) for value in edge.get("sources", ()))
                targets = tuple(str(value) for value in edge.get("targets", ()))
                topology_edges.append(
                    participant_relation(
                        sources,
                        targets,
                        semantic,
                        parameters=_mapping(
                            edge.get("parameters", {}),
                            "participant topology relation parameters",
                        ),
                    )
                )
            elif semantic == PARTICIPANT_DEPENDENCY_RELATION:
                topology_edges.append(
                    participant_dependency(
                        str(edge["source_role"]),
                        str(edge["target_role"]),
                    )
                )
            else:
                topology_edges.append(
                    participant_relation(
                        (str(edge["source_role"]),),
                        (str(edge["target_role"]),),
                        semantic,
                        parameters=_mapping(
                            edge.get("parameters", {}),
                            "participant topology relation parameters",
                        ),
                    )
                )
        return participant_graph(roles, tuple(topology_edges))

    topology = compiler.memo_unit(
        "participant-topology",
        {"roles": roles, "topology": topo_raw},
        build_participant_topology,
    )
    models = []
    for role, raw in _mapping(row["models"], "study models").items():
        role_text = str(role)
        if isinstance(raw, str):
            models.append(
                compiler.memo_unit(
                    "model-role-requirement",
                    (role_text, raw),
                    lambda role_text=role_text, raw=raw: model_role_requirement(role_text, raw),
                )
            )
        else:
            m = _mapping(raw, "study model")
            models.append(
                compiler.memo_unit(
                    "model-role-requirement",
                    (role_text, m),
                    lambda role_text=role_text, m=m: model_role_requirement(
                        role_text, str(m["requirement"]),
                        prompt_configuration_id=None if m.get("prompt") is None else str(m["prompt"]),
                        usage=ModelRoleUsage(str(m.get("usage", ModelRoleUsage.EXECUTION.value))),
                        required=bool(m.get("required", True)), max_bindings=m.get("max_bindings", 1),
                        capability_id=str(m.get("capability_id", "generation")),
                        required_capabilities=tuple(m.get("required_capabilities", ())),
                        input_schema_id=str(m.get("input_schema_id", "model.generation.request.v1")),
                        output_schema_id=str(m.get("output_schema_id", "model.generation.response.v1")),
                        minimum_context_tokens=int(m.get("minimum_context_tokens", 1)),
                    ),
                )
            )
    requirements = binding_requirements(
        str(row.get("trial_provider_requirement_id", "trial.method-program")),
        participants=participants, model_roles=tuple(models), participant_topology=topology,
    )

    selected = benchmark_selected_tasks(benchmark, row.get("benchmark_split_id"))
    raw_workloads = row.get("assignment_workloads")
    workloads = (
        tuple(assignment_workload((task_id(task),)) for task in selected)
        if raw_workloads is None
        else tuple(
            assignment_workload(
                tuple(_mapping(w, "assignment workload")["task_ids"]),
                _task_graph_from_spec(
                    _mapping(w, "assignment workload").get("task_graph"),
                    compiler,
                ),
            )
            for w in raw_workloads
        )
    )
    factors = tuple(
        compiler.memo_unit(
            "factor",
            f,
            lambda f=f: factor_unit(
                str(f["factor_id"]),
                tuple(
                    factor_level_unit(str(level["level_id"]), level.get("value"), control=bool(level.get("control", False)))
                    for level in (_mapping(item, "factor level") for item in f["levels"])
                ),
            ),
        )
        for f in (_mapping(item, "study factor") for item in row.get("factors", ()))
    )
    tr = _mapping(row["trial"], "study trial")
    config_digest = tr.get("configuration_digest", tr.get("protocol_digest"))
    if config_digest is None:
        config_digest = canonical_digest({
            "protocol_id": str(tr["protocol_id"]),
            "configuration": {k: v for k, v in tr.items() if k not in {"configuration_digest", "protocol_digest"}},
        })
    trial_key = (str(tr["protocol_id"]), str(config_digest))
    trial = compiler.memo_unit(
        "trial-protocol",
        trial_key,
        lambda: trial_protocol_unit(*trial_key),
    )
    raw_limits = row.get("limits")
    budget = (
        None
        if raw_limits is None
        else compiler.memo_unit(
            "trial-budget",
            raw_limits,
            lambda: trial_budget_unit(_mapping(raw_limits, "study limits")),
        )
    )
    replay_level = ReplayLevel(
        str(row.get("replay_level", ReplayLevel.OBSERVATIONAL.value))
    )
    session_scope = str(row.get("environment_session_scope", "assignment"))
    seed_scope = str(row.get("environment_seed_scope", "assignment"))
    policy_key = (
        replay_level.value,
        session_scope,
        seed_scope,
        None if budget is None else budget.unit_digest,
    )
    policy = compiler.memo_unit(
        "execution-policy",
        policy_key,
        lambda: execution_policy_unit(
            replay_level=replay_level,
            environment_session_scope=session_scope,
            environment_seed_scope=seed_scope,
            trial_budget=budget,
        ),
    )
    revision = None
    if row.get("revision") is not None:
        rev = _mapping(row["revision"], "research revision")
        revision = revision_unit(str(rev["revision_id"]), str(rev["change_digest"]), rev.get("parent_revision_digest"))
    return study_unit(
        project_id=str(row["project_id"]), experiment_id=str(row.get("experiment_id", row["study_id"])),
        study_id_value=str(row["study_id"]), workload_id=str(row.get("workload_id", "method-program")),
        factors=factors, seeds=tuple(row["seeds"]), repetitions=int(row["repetitions"]),
        measurement_protocol=measurement_protocol, benchmark=benchmark,
        benchmark_split_id=row.get("benchmark_split_id"), assignment_workloads=workloads,
        assignment_relations=tuple(
            (int(r["source_workload_index"]), int(r["target_workload_index"]), str(r["relation"]))
            for r in (_mapping(x, "Study assignment relation") for x in row.get("assignment_relations", ()))
        ),
        binding_requirements_unit=requirements, trial_protocol=trial, revision=revision,
        execution_policy=policy,
    )


FACTOR_SELECTION_TRAIT = "noetrium.factor-selection"
INTERVENTION_TRAIT = "research.intervention"
PARTICIPANT_SCHEDULE_TRAIT = "noetrium.participant-schedule"


def benchmark_cut_digest(value: NoetriumUnit) -> str:
    return require_benchmark_unit(value).unit_digest


def measurement_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(MEASUREMENT_TRAIT):
        raise TypeError("measurement must be research.measurement NoetriumUnit")
    return value.unit_id


def measurement_schema_id(value: NoetriumUnit) -> str:
    return str(value.parameters["schema_id"])


def measurement_value_kind(value: NoetriumUnit) -> str:
    return str(value.parameters["value_kind"])


def measurement_semantic_digest(value: NoetriumUnit) -> str:
    return value.semantic_digest


def measurement_protocol_semantic_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(MEASUREMENT_PROTOCOL_TRAIT):
        raise TypeError("measurement protocol must be NoetriumUnit")
    return value.semantic_digest


def factor_levels(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    if type(value) is not NoetriumUnit or not value.has_trait(FACTOR_TRAIT):
        raise TypeError("factor must be research.factor NoetriumUnit")
    return tuple(value.members)


def factor_level_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(FACTOR_LEVEL_TRAIT):
        raise TypeError("factor level must be NoetriumUnit")
    return value.unit_id


def factor_level_value(value: NoetriumUnit):
    return value.parameters["value"]


def factor_level_control(value: NoetriumUnit) -> bool:
    return bool(value.parameters["control"])


def factor_selection_unit(factor: NoetriumUnit, level: NoetriumUnit) -> NoetriumUnit:
    if level not in factor_levels(factor):
        raise ValueError("factor selection level does not belong to factor")
    return structure_unit(
        f"selection:{factor.unit_id}:{level.unit_id}",
        traits=(FACTOR_SELECTION_TRAIT,),
        parameters={
            "factor_id": factor.unit_id,
            "level_id": level.unit_id,
            "level_digest": level.unit_digest,
            "value": factor_level_value(level),
            "control": factor_level_control(level),
        },
    )


def factor_selection_factor_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(FACTOR_SELECTION_TRAIT):
        raise TypeError("factor selection must be NoetriumUnit")
    return str(value.parameters["factor_id"])


def factor_selection_level_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(FACTOR_SELECTION_TRAIT):
        raise TypeError("factor selection must be NoetriumUnit")
    return str(value.parameters["level_id"])


def intervention_unit(
    intervention_id: str,
    selections: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    if type(selections) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(FACTOR_SELECTION_TRAIT)
        for row in selections
    ):
        raise TypeError("intervention selections must be factor-selection Units")
    ordered = tuple(sorted(selections, key=factor_selection_factor_id))
    if len({factor_selection_factor_id(row) for row in ordered}) != len(ordered):
        raise ValueError("intervention factor selections must be unique")
    return structure_unit(
        _text(intervention_id, "intervention_id"),
        traits=(INTERVENTION_TRAIT,),
        parameters={"control": intervention_id == "control"},
        members=ordered,
    )


def intervention_control(value: NoetriumUnit) -> bool:
    if type(value) is not NoetriumUnit or not value.has_trait(INTERVENTION_TRAIT):
        raise TypeError("intervention must be research.intervention NoetriumUnit")
    return bool(value.parameters["control"])


def intervention_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(INTERVENTION_TRAIT):
        raise TypeError("intervention must be research.intervention NoetriumUnit")
    return value.unit_digest


def participant_schedule_unit(
    waves: tuple[tuple[str, ...], ...],
    *,
    topology_digest: str | None = None,
) -> NoetriumUnit:
    if type(waves) is not tuple or not waves:
        raise TypeError("participant schedule waves must be non-empty tuple")
    roles: list[str] = []
    canonical_waves: list[tuple[str, ...]] = []
    for wave in waves:
        if type(wave) is not tuple or not wave:
            raise TypeError("participant schedule wave must be non-empty tuple")
        if any(type(role) is not str or not role.strip() for role in wave):
            raise TypeError("participant schedule roles must be text")
        if len(wave) != len(set(wave)):
            raise ValueError("participant schedule wave roles must be unique")
        ordered = tuple(sorted(wave))
        canonical_waves.append(ordered)
        roles.extend(ordered)
    if len(roles) != len(set(roles)):
        raise ValueError("participant schedule roles may appear only once")
    if topology_digest is not None:
        require_sha256(topology_digest, "participant schedule topology_digest")
    return structure_unit(
        "participant-schedule",
        traits=(PARTICIPANT_SCHEDULE_TRAIT,),
        parameters={
            "waves": tuple(canonical_waves),
            "topology_digest": topology_digest,
        },
    )


def participant_schedule_waves(value: NoetriumUnit) -> tuple[tuple[str, ...], ...]:
    if type(value) is not NoetriumUnit or not value.has_trait(PARTICIPANT_SCHEDULE_TRAIT):
        raise TypeError("participant schedule must be NoetriumUnit")
    return tuple(tuple(row) for row in value.parameters["waves"])


def participant_schedule_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(PARTICIPANT_SCHEDULE_TRAIT):
        raise TypeError("participant schedule must be NoetriumUnit")
    return value.unit_digest


def trial_protocol_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(TRIAL_PROTOCOL_TRAIT):
        raise TypeError("trial protocol must be NoetriumUnit")
    return value.unit_id


def trial_protocol_configuration_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(TRIAL_PROTOCOL_TRAIT):
        raise TypeError("trial protocol must be NoetriumUnit")
    return str(value.parameters["configuration_digest"])


def trial_protocol_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(TRIAL_PROTOCOL_TRAIT):
        raise TypeError("trial protocol must be NoetriumUnit")
    return value.unit_digest


def trial_budget_id(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(TRIAL_BUDGET_TRAIT):
        raise TypeError("trial budget must be NoetriumUnit")
    return value.unit_id


def execution_policy_environment_session_scope(value: NoetriumUnit) -> str:
    return str(value.parameters["environment_session_scope"])


def execution_policy_environment_seed_scope(value: NoetriumUnit) -> str:
    return str(value.parameters["environment_seed_scope"])


def revision_digest(value: NoetriumUnit) -> str:
    if type(value) is not NoetriumUnit or not value.has_trait(REVISION_TRAIT):
        raise TypeError("revision must be NoetriumUnit")
    return value.unit_digest


__all__ = [name for name in globals() if name.startswith((
    "study_", "benchmark_", "measurement_", "task_", "factor_", "trial_",
    "execution_policy_", "revision_", "intervention_", "participant_schedule_", "split_", "require_"
))]
