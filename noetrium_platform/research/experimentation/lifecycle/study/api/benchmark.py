"""Unit-native Benchmark topology plus dynamic source-resolution authority seams."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType
from hashlib import sha256
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest, freeze_json, require_sha256
from noetrium_platform.foundation.kernel.unit import role
from noetrium_platform.foundation.kernel.structure import (
    EMPTY_BOUNDARY,
    NoetriumUnit,
    endpoint_child_id,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
)

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


class TaskVerifierIsolation(StrEnum):
    SHARED = "shared"
    SEPARATE = "separate"


def task_artifact(
    artifact_id: str,
    relative_path: str,
    required: bool = True,
) -> Mapping[str, object]:
    artifact_id = _text(artifact_id, "task artifact id")
    relative_path = _text(relative_path, "task artifact relative_path")
    if relative_path.startswith(("/", "\\")):
        raise ValueError("task artifact path must be package-relative")
    parts = tuple(part for part in relative_path.replace("\\", "/").split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("task artifact path must be canonical package-relative")
    if type(required) is not bool:
        raise TypeError("task artifact required must be boolean")
    return freeze_json({
        "artifact_id": artifact_id,
        "relative_path": relative_path,
        "required": required,
    })


def task_package(
    package_schema_id: str,
    instruction_digest: str,
    *,
    environment_requirement_id: str | None = None,
    verifier_requirement_id: str | None = None,
    verifier_isolation: TaskVerifierIsolation = TaskVerifierIsolation.SEPARATE,
    verifier_environment_requirement_id: str | None = None,
    artifacts: tuple[Mapping[str, object], ...] = (),
    resource_requirement_digest: str | None = None,
    network_policy_digest: str | None = None,
) -> Mapping[str, object]:
    package_schema_id = _text(package_schema_id, "task package schema_id")
    require_sha256(instruction_digest, "task package instruction_digest")
    for name, value in (
        ("environment_requirement_id", environment_requirement_id),
        ("verifier_requirement_id", verifier_requirement_id),
        ("verifier_environment_requirement_id", verifier_environment_requirement_id),
    ):
        if value is not None:
            _text(value, f"task package {name}")
    if not isinstance(verifier_isolation, TaskVerifierIsolation):
        raise TypeError("task package verifier_isolation must be TaskVerifierIsolation")
    if verifier_environment_requirement_id is not None and verifier_requirement_id is None:
        raise ValueError("task package verifier environment requires verifier requirement")
    if type(artifacts) is not tuple or any(not isinstance(row, Mapping) for row in artifacts):
        raise TypeError("task package artifacts must be mapping tuple")
    artifact_ids = tuple(str(row["artifact_id"]) for row in artifacts)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("task package artifact ids must be unique")
    for name, value in (
        ("resource_requirement_digest", resource_requirement_digest),
        ("network_policy_digest", network_policy_digest),
    ):
        if value is not None:
            require_sha256(value, f"task package {name}")
    payload = {
        "package_schema_id": package_schema_id,
        "instruction_digest": instruction_digest,
        "environment_requirement_id": environment_requirement_id,
        "verifier_requirement_id": verifier_requirement_id,
        "verifier_isolation": verifier_isolation.value,
        "verifier_environment_requirement_id": verifier_environment_requirement_id,
        "artifacts": tuple(artifacts),
        "resource_requirement_digest": resource_requirement_digest,
        "network_policy_digest": network_policy_digest,
    }
    payload["package_digest"] = canonical_digest(payload)
    return freeze_json(payload)


class TaskRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    RETRY_OF = "retry_of"
    SEQUENCE_AFTER = "sequence_after"
    LINEAGE = "lineage"


@lru_cache(maxsize=65536)
def task_graph_key(task_id: str) -> str:
    """Canonical local graph key for an arbitrary external scientific task id."""
    task_id = _text(task_id, "task graph task_id")
    return "task:" + canonical_digest({"task_id": task_id})


TASK_GRAPH_TRAIT = "experiment.task-graph"
TASK_VERTEX_TRAIT = "experiment.task"
_TASK_RELATION_IDS = {
    TaskRelation.PREREQUISITE: "experiment.prerequisite",
    TaskRelation.RETRY_OF: "experiment.retry-of",
    TaskRelation.SEQUENCE_AFTER: "experiment.sequence-after",
    TaskRelation.LINEAGE: "experiment.lineage",
}
_TASK_RELATION_KINDS = {value: key for key, value in _TASK_RELATION_IDS.items()}


def _task_vertex_from_key(task_id: str, local_key: str) -> NoetriumUnit:
    """Construct a proven leaf task vertex without generic graph revalidation."""
    semantic = local_key.removeprefix("task:")
    parameters = MappingProxyType({"task_id": task_id})
    return NoetriumUnit._from_normalized(
        local_key,
        schemas=(TASK_VERTEX_TRAIT,),
        attributes=MappingProxyType({
            "kind": "structure",
            "parameters": parameters,
            "symbol_ids": (),
        }),
        roles=(
            ("atom", ()),
            ("boundary", (EMPTY_BOUNDARY,)),
            ("member", ()),
            ("relation", ()),
            ("symbol", ()),
        ),
        semantic_projection_digest=semantic,
    )


def task_vertex(task_id: str) -> NoetriumUnit:
    task_id = _text(task_id, "task vertex task_id")
    return _task_vertex_from_key(task_id, task_graph_key(task_id))


def task_vertex_id(vertex: NoetriumUnit) -> str:
    if type(vertex) is not NoetriumUnit or not vertex.has_trait(TASK_VERTEX_TRAIT):
        raise TypeError("task vertex must be experiment.task NoetriumUnit")
    task_id = _text(vertex.parameters.get("task_id"), "task vertex semantic task_id")
    if vertex.unit_id != task_graph_key(task_id):
        raise ValueError("task vertex local identity does not match semantic task_id")
    return task_id


def _task_graph_relation_from_endpoints(
    source_task_id: str,
    target_task_id: str,
    relation: TaskRelation,
    source_endpoint: NoetriumUnit,
    target_endpoint: NoetriumUnit,
) -> NoetriumUnit:
    """Construct the proven single-edge TaskGraph relation directly.

    TaskGraphInterner has already established the generic relation invariants:
    exactly one source and target, canonical endpoints, no ports, default ALL
    trigger and no progress marker. Re-entering ``relation_unit`` would project
    those same endpoint Units back to child ids, revalidate/sort singleton
    tuples, and then hash the same parameters. Preserve the exact relation.v1
    identity byte protocol while making this path Θ(payload bytes) only.
    """

    source_key = str(source_endpoint.attribute("child_id"))
    target_key = str(target_endpoint.attribute("child_id"))
    relation_id_value = _TASK_RELATION_IDS[relation]
    parameters = freeze_json({
        "source_task_id": source_task_id,
        "target_task_id": target_task_id,
    })
    parameters_digest = canonical_digest(parameters)
    hasher = sha256()
    hasher.update(b"noetrium.unit.relation.instance.v1\0")
    for marker, child_key in ((b"S", source_key), (b"T", target_key)):
        hasher.update(marker)
        hasher.update(child_key.encode("utf-8"))
        hasher.update(b"\0")
        # TaskGraph endpoints are deliberately unported.
        hasher.update(b"\0")
    for value in (relation_id_value, parameters_digest, "all", "", ""):
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\0")
    semantic = hasher.hexdigest()
    return NoetriumUnit._from_normalized(
        f"relation:{semantic}",
        schemas=(),
        attributes=MappingProxyType({
            "kind": "relation",
            "relation_id": relation_id_value,
            "parameters": parameters,
            "trigger_kind": "all",
            "trigger_quorum": None,
            "progress": None,
        }),
        roles=(
            ("source", (source_endpoint,)),
            ("target", (target_endpoint,)),
        ),
        semantic_projection_digest=semantic,
    )


def task_graph_relation(
    source_task_id: str,
    target_task_id: str,
    relation: TaskRelation,
) -> NoetriumUnit:
    source_task_id = _text(source_task_id, "task graph source_task_id")
    target_task_id = _text(target_task_id, "task graph target_task_id")
    if source_task_id == target_task_id:
        raise ValueError("task graph relation cannot self-reference")
    if not isinstance(relation, TaskRelation):
        raise TypeError("task graph relation must be TaskRelation")
    return _task_graph_relation_from_endpoints(
        source_task_id,
        target_task_id,
        relation,
        endpoint_unit(task_graph_key(source_task_id), None),
        endpoint_unit(task_graph_key(target_task_id), None),
    )


def _task_graph_relation_ids(relation: NoetriumUnit) -> tuple[str, str]:
    if task_graph_relation_kind(relation) not in TaskRelation:
        raise ValueError("relation is not task graph relation")
    parameters = relation.parameters
    if not isinstance(parameters, Mapping):
        raise TypeError("task graph relation parameters must be an object")
    source_task_id = _text(
        parameters.get("source_task_id"),
        "task graph relation source_task_id",
    )
    target_task_id = _text(
        parameters.get("target_task_id"),
        "task graph relation target_task_id",
    )
    if endpoint_child_id(relation.sources[0]) != task_graph_key(source_task_id):
        raise ValueError("task graph relation source local key drifted")
    if endpoint_child_id(relation.targets[0]) != task_graph_key(target_task_id):
        raise ValueError("task graph relation target local key drifted")
    return source_task_id, target_task_id


def task_graph_relation_source_id(relation: NoetriumUnit) -> str:
    return _task_graph_relation_ids(relation)[0]


def task_graph_relation_target_id(relation: NoetriumUnit) -> str:
    return _task_graph_relation_ids(relation)[1]




def _task_graph_semantic_digest(
    task_ids: tuple[str, ...],
    edges: tuple[tuple[str, str, TaskRelation], ...],
) -> str:
    """Canonical TaskGraph semantics in Θ(V + E) schema work.

    Task ids are the semantic vertex identities and every TaskGraph relation is
    a directed, unported edge with one typed relation kind.  No graph
    isomorphism refinement is necessary once those schema invariants are
    proven, so the semantic projection is the canonical multiset of vertices
    and directed relation tuples.
    """

    return canonical_digest({
        "schema": "noetrium.task-graph.semantic.v2",
        "task_ids": tuple(sorted(task_ids)),
        "relations": tuple(sorted(
            (source, target, relation.value)
            for source, target, relation in edges
        )),
    })


def _task_graph_unit(
    task_ids: tuple[str, ...],
    vertices: tuple[NoetriumUnit, ...],
    relations: tuple[NoetriumUnit, ...],
    edges: tuple[tuple[str, str, TaskRelation], ...],
) -> NoetriumUnit:
    """Assemble an already-proven TaskGraph cut in canonical structure order."""
    ordered_vertices = tuple(sorted(vertices, key=lambda row: row.unit_id))
    ordered_relations = tuple(sorted(relations, key=lambda row: row.semantic_digest))
    return NoetriumUnit._from_normalized(
        "task-graph",
        schemas=(TASK_GRAPH_TRAIT,),
        attributes=MappingProxyType({
            "kind": "structure",
            "parameters": MappingProxyType({}),
            "symbol_ids": (),
        }),
        roles=(
            ("atom", ()),
            ("boundary", (EMPTY_BOUNDARY,)),
            ("member", ordered_vertices),
            ("relation", ordered_relations),
            ("symbol", ()),
        ),
        semantic_projection_digest=_task_graph_semantic_digest(task_ids, edges),
    )

def task_graph(relations: tuple[NoetriumUnit, ...] = ()) -> NoetriumUnit:
    if type(relations) is not tuple or any(type(row) is not NoetriumUnit for row in relations):
        raise TypeError("task graph relations must be NoetriumUnit tuple")
    valid = frozenset(_TASK_RELATION_IDS.values())
    if any(relation_id(row) not in valid for row in relations):
        raise ValueError("task graph contains non-task relation")
    edges = tuple(
        (*_task_graph_relation_ids(relation), task_graph_relation_kind(relation))
        for relation in relations
    )
    ids = tuple(sorted({
        task_id
        for source, target, _relation in edges
        for task_id in (source, target)
    }))
    return _task_graph_unit(
        ids,
        tuple(task_vertex(task_id) for task_id in ids),
        relations,
        edges,
    )


class TaskGraphInterner:
    """Execution-scoped hash-consing interner returning only immutable Unit graphs.

    Task vertex and endpoint semantics depend only on canonical task_id. Keeping
    one builder for a compilation cut therefore reduces repeated identity work
    across benchmark and assignment-workload projections without changing graph
    truth. Memory is bounded by the caller's compilation lifetime.
    """

    __slots__ = ("_keys", "_vertices", "_endpoints", "_relations", "_graphs")

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._vertices: dict[str, NoetriumUnit] = {}
        self._endpoints: dict[str, NoetriumUnit] = {}
        self._relations: dict[
            tuple[str, str, TaskRelation], NoetriumUnit
        ] = {}
        self._graphs: dict[
            tuple[tuple[str, str, TaskRelation], ...], NoetriumUnit
        ] = {}

    def _identity(self, task_id: str) -> tuple[str, NoetriumUnit, NoetriumUnit]:
        key = self._keys.get(task_id)
        if key is None:
            key = task_graph_key(task_id)
            self._keys[task_id] = key
        vertex = self._vertices.get(task_id)
        if vertex is None:
            vertex = _task_vertex_from_key(task_id, key)
            self._vertices[task_id] = vertex
        endpoint = self._endpoints.get(task_id)
        if endpoint is None:
            endpoint = endpoint_unit(key, None)
            self._endpoints[task_id] = endpoint
        return key, vertex, endpoint

    def _relation(
        self,
        source: str,
        target: str,
        relation: TaskRelation,
        source_endpoint: NoetriumUnit,
        target_endpoint: NoetriumUnit,
    ) -> NoetriumUnit:
        key = (source, target, relation)
        cached = self._relations.get(key)
        if cached is not None:
            return cached
        row = _task_graph_relation_from_endpoints(
            source, target, relation, source_endpoint, target_endpoint
        )
        existing = self._relations.setdefault(key, row)
        if existing.unit_digest != row.unit_digest:
            raise RuntimeError(
                "canonical task relation identity produced multiple Unit identities"
            )
        return existing

    def build(
        self,
        edges: tuple[tuple[str, str, TaskRelation], ...],
    ) -> NoetriumUnit:
        if type(edges) is not tuple:
            raise TypeError("task graph edges must be a tuple")
        normalized: list[tuple[str, str, TaskRelation]] = []
        task_ids: set[str] = set()
        for row in edges:
            if type(row) is not tuple or len(row) != 3:
                raise TypeError("task graph edge must be (source, target, relation)")
            source = _text(row[0], "task graph source_task_id")
            target = _text(row[1], "task graph target_task_id")
            relation = row[2]
            if source == target:
                raise ValueError("task graph relation cannot self-reference")
            if not isinstance(relation, TaskRelation):
                raise TypeError("task graph relation must be TaskRelation")
            normalized.append((source, target, relation))
            task_ids.add(source)
            task_ids.add(target)

        # Relation declaration order is not graph semantics.  Normalize once so
        # identical edge sets share one immutable graph Unit for this execution
        # cut.  Duplicate edges remain duplicates and therefore remain visible.
        edge_rows = tuple(
            sorted(
                normalized,
                key=lambda row: (row[0], row[1], row[2].value),
            )
        )
        cached = self._graphs.get(edge_rows)
        if cached is not None:
            return cached

        ordered_ids = tuple(sorted(task_ids))
        vertices: dict[str, NoetriumUnit] = {}
        endpoints: dict[str, NoetriumUnit] = {}
        for task_id in ordered_ids:
            _key, vertex, endpoint = self._identity(task_id)
            vertices[task_id] = vertex
            endpoints[task_id] = endpoint
        relations = tuple(
            self._relation(
                source, target, relation, endpoints[source], endpoints[target]
            )
            for source, target, relation in edge_rows
        )
        graph = _task_graph_unit(
            ordered_ids,
            tuple(vertices[task_id] for task_id in ordered_ids),
            relations,
            edge_rows,
        )
        existing = self._graphs.setdefault(edge_rows, graph)
        if existing.unit_digest != graph.unit_digest:
            raise RuntimeError(
                "canonical task graph edge set produced multiple Unit identities"
            )
        return existing


def task_graph_from_edges(
    edges: tuple[tuple[str, str, TaskRelation], ...],
) -> NoetriumUnit:
    """Construct one canonical task graph in Θ(V+E) identity work."""
    return TaskGraphInterner().build(edges)


def validate_task_graph(graph: NoetriumUnit) -> None:
    if type(graph) is not NoetriumUnit or not graph.has_trait(TASK_GRAPH_TRAIT):
        raise TypeError("task graph must be experiment.task-graph NoetriumUnit")
    semantic_ids = tuple(task_vertex_id(child) for child in graph.members)
    if len(semantic_ids) != len(set(semantic_ids)):
        raise ValueError("task graph contains duplicate semantic task ids")
    known = set(semantic_ids)
    valid = frozenset(_TASK_RELATION_IDS.values())
    for relation in graph.relations:
        if relation_id(relation) not in valid:
            raise ValueError("task graph contains unsupported relation semantics")
        source_task_id, target_task_id = _task_graph_relation_ids(relation)
        if source_task_id not in known or target_task_id not in known:
            raise ValueError("task graph relation references missing semantic task")


def task_graph_relation_kind(relation: NoetriumUnit) -> TaskRelation:
    try:
        return _TASK_RELATION_KINDS[relation_id(relation)]
    except KeyError as exc:
        raise ValueError("relation is not task graph relation") from exc


BENCHMARK_CUT_REQUIREMENT_TRAIT = "noetrium.benchmark-cut-requirement"
_BENCHMARK_CUT_REQUIREMENT_ATTR = "__noetrium_benchmark_cut_requirements__"


def benchmark_cut_requirement_unit(
    benchmark_id: str,
    revision_id: str,
    *,
    split_ids: tuple[str, ...] = (),
    cut_digest: str | None = None,
) -> NoetriumUnit:
    benchmark_id = _text(benchmark_id, "benchmark cut benchmark_id")
    revision_id = _text(revision_id, "benchmark cut revision_id")
    if type(split_ids) is not tuple or any(type(row) is not str or not row.strip() for row in split_ids):
        raise TypeError("benchmark cut split_ids must be text tuple")
    split_ids = tuple(sorted(set(split_ids)))
    if cut_digest is not None:
        require_sha256(cut_digest, "benchmark cut digest")
    return structure_unit(
        f"{benchmark_id}@{revision_id}",
        traits=(BENCHMARK_CUT_REQUIREMENT_TRAIT,),
        parameters={
            "benchmark_id": benchmark_id,
            "revision_id": revision_id,
            "required_split_ids": split_ids,
            "cut_digest": cut_digest,
        },
    )


def benchmark_cut_requirements(factory: object) -> tuple[NoetriumUnit, ...]:
    rows = getattr(factory, _BENCHMARK_CUT_REQUIREMENT_ATTR, ())
    if type(rows) is not tuple or any(
        type(row) is not NoetriumUnit or not row.has_trait(BENCHMARK_CUT_REQUIREMENT_TRAIT)
        for row in rows
    ):
        raise TypeError("Study benchmark cut requirements must be Unit tuple")
    return rows


def requires_benchmark_cut(
    benchmark_id: str,
    revision_id: str,
    *,
    split_ids: tuple[str, ...] = (),
    cut_digest: str | None = None,
):
    requirement = benchmark_cut_requirement_unit(
        benchmark_id,
        revision_id,
        split_ids=split_ids,
        cut_digest=cut_digest,
    )

    def decorate(factory):
        if not callable(factory):
            raise TypeError("benchmark cut requirement can decorate only callables")
        existing = benchmark_cut_requirements(factory)
        if any(row.parameters["benchmark_id"] == benchmark_id for row in existing):
            raise ValueError(f"duplicate benchmark cut declaration: {benchmark_id!r}")
        setattr(
            factory,
            _BENCHMARK_CUT_REQUIREMENT_ATTR,
            tuple(sorted((*existing, requirement), key=lambda row: row.unit_digest)),
        )
        return factory

    return decorate


class BenchmarkSourceKind(StrEnum):
    LOCAL_FILE = "local_file"
    HTTP = "http"
    GIT = "git"
    HUGGINGFACE = "huggingface"
    CUSTOM = "custom"


BENCHMARK_SOURCE_TRAIT = "noetrium.benchmark-source"


def benchmark_source_unit(
    source_id: str,
    kind: BenchmarkSourceKind,
    revision_id: str,
    locator: str,
    content_digest: str,
    *,
    license: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> NoetriumUnit:
    source_id = _text(source_id, "benchmark source source_id")
    revision_id = _text(revision_id, "benchmark source revision_id")
    locator = _text(locator, "benchmark source locator")
    if not isinstance(kind, BenchmarkSourceKind):
        raise TypeError("benchmark source kind must be BenchmarkSourceKind")
    require_sha256(content_digest, "benchmark source content_digest")
    if license is not None:
        _text(license, "benchmark source license")
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, Mapping) or any(
        type(k) is not str or type(v) is not str for k, v in metadata.items()
    ):
        raise TypeError("benchmark source metadata must be string mapping")
    return structure_unit(
        source_id,
        traits=(BENCHMARK_SOURCE_TRAIT,),
        parameters={
            "kind": kind.value,
            "revision_id": revision_id,
            "locator": locator,
            "content_digest": content_digest,
            "license": license,
            "metadata": dict(sorted(metadata.items())),
        },
    )


def require_benchmark_source(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(BENCHMARK_SOURCE_TRAIT):
        raise TypeError("benchmark source must be NoetriumUnit")
    return value


def require_benchmark(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait("research.benchmark"):
        raise TypeError("benchmark cut must be research.benchmark NoetriumUnit")
    return value


@dataclass(frozen=True, slots=True)
class BenchmarkSourceResolution:
    source: NoetriumUnit
    task_set: NoetriumUnit
    resolution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        source = require_benchmark_source(self.source)
        task_set = require_benchmark(self.task_set)
        if task_set.parameters["source_digest"] != source.parameters["content_digest"]:
            raise ValueError("resolved benchmark content digest does not match source")
        if task_set.parameters["revision_id"] != source.parameters["revision_id"]:
            raise ValueError("resolved benchmark revision does not match source")
        object.__setattr__(
            self,
            "resolution_digest",
            canonical_digest({
                "source": source.unit_digest,
                "task_set": task_set.unit_digest,
            }),
        )

    @property
    def cut_digest(self) -> str:
        return self.task_set.unit_digest


@dataclass(frozen=True, slots=True)
class BenchmarkResolutionRegistration:
    resolution: BenchmarkSourceResolution
    authority_proof_digest: str
    registration_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.resolution) is not BenchmarkSourceResolution:
            raise TypeError("benchmark resolution registration requires typed resolution")
        require_sha256(self.authority_proof_digest, "benchmark authority proof digest")
        object.__setattr__(
            self,
            "registration_digest",
            canonical_digest({
                "benchmark_id": self.resolution.task_set.unit_id,
                "revision_id": self.resolution.task_set.parameters["revision_id"],
                "resolution_digest": self.resolution.resolution_digest,
                "authority_proof_digest": self.authority_proof_digest,
            }),
        )

    @property
    def benchmark_id(self) -> str:
        return self.resolution.task_set.unit_id


class BenchmarkResolutionRegistry:
    def __init__(
        self,
        registrations: tuple[BenchmarkResolutionRegistration, ...] = (),
    ) -> None:
        if type(registrations) is not tuple or any(
            type(row) is not BenchmarkResolutionRegistration for row in registrations
        ):
            raise TypeError("benchmark resolution registry requires typed tuple")
        ordered = tuple(sorted(
            registrations,
            key=lambda row: (
                row.benchmark_id,
                str(row.resolution.task_set.parameters["revision_id"]),
                row.registration_digest,
            ),
        ))
        digests = tuple(row.registration_digest for row in ordered)
        if len(digests) != len(set(digests)):
            raise ValueError("benchmark resolution registrations must be unique")
        self._registrations = ordered
        self._identity_digest = canonical_digest({
            "schema": "noetrium.benchmark-resolution-registry.v2",
            "registrations": digests,
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def registrations(self) -> tuple[BenchmarkResolutionRegistration, ...]:
        return self._registrations

    @property
    def benchmark_ids(self) -> tuple[str, ...]:
        return tuple(sorted({row.benchmark_id for row in self._registrations}))

    def registrations_for(self, benchmark_id: str) -> tuple[BenchmarkResolutionRegistration, ...]:
        _text(benchmark_id, "benchmark resolution benchmark_id")
        return tuple(row for row in self._registrations if row.benchmark_id == benchmark_id)

    def resolve_exact(self, benchmark_id: str) -> BenchmarkResolutionRegistration:
        matches = self.registrations_for(benchmark_id)
        if len(matches) != 1:
            raise LookupError(
                f"benchmark {benchmark_id!r} exact resolution count={len(matches)}"
            )
        return matches[0]


class BenchmarkSourcePort(Protocol):
    def resolve(self, source: NoetriumUnit) -> BenchmarkSourceResolution: ...


class InMemoryBenchmarkSource(BenchmarkSourcePort):
    def __init__(self) -> None:
        self._cuts: dict[str, BenchmarkSourceResolution] = {}

    def register(
        self,
        source: NoetriumUnit,
        task_set: NoetriumUnit,
    ) -> BenchmarkSourceResolution:
        source = require_benchmark_source(source)
        resolution = BenchmarkSourceResolution(source, task_set)
        key = f"{source.unit_id}@{source.parameters['revision_id']}"
        existing = self._cuts.get(key)
        if existing is not None and existing != resolution:
            raise ValueError(f"benchmark source revision already registered: {key}")
        self._cuts[key] = resolution
        return resolution

    def resolve(self, source: NoetriumUnit) -> BenchmarkSourceResolution:
        source = require_benchmark_source(source)
        key = f"{source.unit_id}@{source.parameters['revision_id']}"
        try:
            return self._cuts[key]
        except KeyError as exc:
            raise KeyError(f"benchmark source revision is not registered: {key}") from exc


__all__ = [
    "BENCHMARK_CUT_REQUIREMENT_TRAIT",
    "BENCHMARK_SOURCE_TRAIT",
    "BenchmarkResolutionRegistration",
    "BenchmarkResolutionRegistry",
    "BenchmarkSourceKind",
    "BenchmarkSourcePort",
    "BenchmarkSourceResolution",
    "InMemoryBenchmarkSource",
    "TaskRelation",
    "TaskVerifierIsolation",
    "benchmark_cut_requirement_unit",
    "benchmark_cut_requirements",
    "benchmark_source_unit",
    "require_benchmark",
    "require_benchmark_source",
    "requires_benchmark_cut",
    "task_artifact",
    "task_graph",
    "task_graph_from_edges",
    "task_graph_relation",
    "task_graph_relation_kind",
    "task_package",
    "task_vertex",
    "task_vertex_id",
    "validate_task_graph",
]
