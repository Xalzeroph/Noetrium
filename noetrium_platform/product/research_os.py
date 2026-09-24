"""Single top-level downstream authoring and control model for Noetrium.

Lower platform systems keep their own authority APIs for composition, but ordinary
research projects author and control work only through this product surface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import importlib
import inspect
import re
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)

_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


def _token(value: object, field: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical token")
    return value


def _tokens(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    result = tuple(sorted(_token(value, field) for value in values))
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicates")
    return result


class ResearchDefinitionKind(StrEnum):
    METHOD = "method"
    BENCHMARK = "benchmark"
    DATASET = "dataset"
    METRIC = "metric"
    MODEL = "model"
    ENVIRONMENT = "environment"
    PARTICIPANT = "participant"
    PROTOCOL = "protocol"
    RESOURCE_POLICY = "resource-policy"
    CUSTOM = "custom"


class ResearchNodeKind(StrEnum):
    METHOD = "method"
    STUDY = "study"
    EXPERIMENT = "experiment"
    RUN = "run"
    TRIAL = "trial"
    EVALUATION = "evaluation"
    ANALYSIS = "analysis"
    OPTIMIZATION = "optimization"
    SELECTION = "selection"
    ABLATION = "ablation"
    ROBUSTNESS = "robustness"
    SCALING = "scaling"
    FIGURE = "figure"
    TABLE = "table"
    PUBLICATION = "publication"
    CUSTOM = "custom"


class ResearchValueKind(StrEnum):
    ARTIFACT = "artifact"
    EVIDENCE = "evidence"
    CHECKPOINT = "checkpoint"
    SELECTION = "selection"
    METRIC = "metric"
    DATA = "data"


@dataclass(frozen=True, slots=True)
class ResearchMethodProgramImplementation:
    """Import-resolvable immutable MethodProgram identity.

    Complex paper methods already authored as MethodProgram IR are referenced by
    module-level symbols rather than wrapped as ordinary Python callables.  The
    frozen ResearchProgram stores only import coordinates plus the exact
    MethodProgram digest; lowering re-imports the symbol and fails closed on any
    type or digest drift.
    """

    implementation_id: str
    module: str
    qualname: str
    program_digest: str
    implementation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.implementation_id, "research method-program implementation_id")
        if type(self.module) is not str or not self.module.strip():
            raise ValueError("research method-program module must be non-empty")
        if type(self.qualname) is not str or not self.qualname.strip():
            raise ValueError("research method-program qualname must be non-empty")
        if "<locals>" in self.qualname or "<lambda>" in self.qualname:
            raise ValueError(
                "research method-program must be a module-resolvable named symbol"
            )
        require_sha256(
            self.program_digest,
            "research method-program program_digest",
        )
        module = self.module.strip()
        qualname = self.qualname.strip()
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "qualname", qualname)
        object.__setattr__(
            self,
            "implementation_digest",
            canonical_digest(
                {
                    "implementation_type": "method_program",
                    "implementation_id": self.implementation_id,
                    "module": module,
                    "qualname": qualname,
                    "program_digest": self.program_digest,
                }
            ),
        )

    @classmethod
    def from_symbol(
        cls,
        implementation_id: str,
        *,
        module: str,
        qualname: str,
    ) -> "ResearchMethodProgramImplementation":
        if type(module) is not str or not module.strip():
            raise ValueError("research method-program module must be non-empty")
        if type(qualname) is not str or not qualname.strip():
            raise ValueError("research method-program qualname must be non-empty")
        try:
            value: object = importlib.import_module(module.strip())
            for part in qualname.strip().split("."):
                value = getattr(value, part)
        except (ImportError, AttributeError) as exc:
            raise ValueError(
                "research method-program symbol cannot be imported: "
                f"{module}:{qualname}"
            ) from exc
        program_digest = getattr(value, "program_digest", None)
        if type(program_digest) is not str:
            raise TypeError(
                "research method-program symbol does not expose program_digest"
            )
        require_sha256(
            program_digest,
            "research method-program symbol program_digest",
        )
        return cls(
            implementation_id,
            module.strip(),
            qualname.strip(),
            program_digest,
        )


@dataclass(frozen=True, slots=True)
class ResearchImplementation:
    """Import-resolvable authoring implementation with automatic source identity.

    The callable itself is never embedded in a frozen ResearchProgram.  The module
    and qualname are stable resolution coordinates; the exact callable source is
    normalized and digested so unrelated definitions do not invalidate each other.
    Runtime compilation binds the callable dependency closure plus Git, dependency,
    environment, model,
    and provider provenance without asking downstream authors to calculate hashes.
    """

    implementation_id: str
    module: str
    qualname: str
    source_digest: str
    implementation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.implementation_id, "research implementation_id")
        if type(self.module) is not str or not self.module.strip():
            raise ValueError("research implementation module must be non-empty")
        if type(self.qualname) is not str or not self.qualname.strip():
            raise ValueError("research implementation qualname must be non-empty")
        if "<locals>" in self.qualname or "<lambda>" in self.qualname:
            raise ValueError(
                "research implementation must be a module-resolvable named callable"
            )
        require_sha256(self.source_digest, "research implementation source_digest")
        module = self.module.strip()
        qualname = self.qualname.strip()
        object.__setattr__(self, "module", module)
        object.__setattr__(self, "qualname", qualname)
        object.__setattr__(
            self,
            "implementation_digest",
            canonical_digest(
                {
                    "implementation_id": self.implementation_id,
                    "module": module,
                    "qualname": qualname,
                    "source_digest": self.source_digest,
                }
            ),
        )

    @classmethod
    def from_callable(
        cls,
        implementation_id: str,
        implementation: Callable[..., object],
    ) -> "ResearchImplementation":
        if not callable(implementation):
            raise TypeError("research implementation must be callable")
        module = getattr(implementation, "__module__", None)
        qualname = getattr(implementation, "__qualname__", None)
        if type(module) is not str or not module.strip():
            raise ValueError("research implementation callable has no module identity")
        if type(qualname) is not str or not qualname.strip():
            raise ValueError("research implementation callable has no qualname identity")
        if module.strip() == "__main__":
            raise ValueError(
                "research implementation must live in an importable module, not __main__"
            )
        if "<locals>" in qualname or "<lambda>" in qualname:
            raise ValueError(
                "research implementation must be declared at module scope with a name"
            )
        try:
            source = inspect.getsource(implementation)
        except (OSError, TypeError) as exc:
            raise ValueError(
                "research implementation callable source cannot be resolved"
            ) from exc
        normalized = source.replace("\r\n", "\n").replace("\r", "\n")
        source_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return cls(
            implementation_id,
            module.strip(),
            qualname.strip(),
            source_digest,
        )


@dataclass(frozen=True, slots=True)
class ResearchDefinition:
    definition_id: str
    kind: ResearchDefinitionKind
    implementation: (
        ResearchImplementation | ResearchMethodProgramImplementation | None
    ) = None
    config: JsonValue = None
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.definition_id, "research definition_id")
        if not isinstance(self.kind, ResearchDefinitionKind):
            raise TypeError("research definition kind must be typed")
        if self.implementation is not None and type(self.implementation) not in {
            ResearchImplementation,
            ResearchMethodProgramImplementation,
        }:
            raise TypeError(
                "research definition implementation must be a typed Research "
                "implementation or None"
            )
        if (
            type(self.implementation) is ResearchMethodProgramImplementation
            and self.kind is not ResearchDefinitionKind.METHOD
        ):
            raise ValueError(
                "MethodProgram implementation may only back METHOD definitions"
            )
        config = freeze_json(self.config)
        object.__setattr__(self, "config", config)
        object.__setattr__(
            self,
            "definition_digest",
            canonical_digest(
                {
                    "definition_id": self.definition_id,
                    "kind": self.kind.value,
                    "implementation_digest": (
                        None
                        if self.implementation is None
                        else self.implementation.implementation_digest
                    ),
                    "config": config,
                }
            ),
        )

    @property
    def implementation_id(self) -> str | None:
        return None if self.implementation is None else self.implementation.implementation_id

    @property
    def implementation_digest(self) -> str | None:
        return (
            None
            if self.implementation is None
            else self.implementation.implementation_digest
        )

    @property
    def platform_resolved(self) -> bool:
        return self.implementation is None


@dataclass(frozen=True, slots=True)
class ResearchOutputSpec:
    name: str
    kind: ResearchValueKind

    def __post_init__(self) -> None:
        _token(self.name, "research output name")
        if not isinstance(self.kind, ResearchValueKind):
            raise TypeError("research output kind must be typed")


@dataclass(frozen=True, slots=True)
class ResearchInputBinding:
    input_name: str
    output_name: str
    kind: ResearchValueKind

    def __post_init__(self) -> None:
        _token(self.input_name, "research input name")
        _token(self.output_name, "research output name")
        if not isinstance(self.kind, ResearchValueKind):
            raise TypeError("research input kind must be typed")


@dataclass(frozen=True, slots=True)
class ResearchDependency:
    upstream_node_id: str
    downstream_node_id: str
    bindings: tuple[ResearchInputBinding, ...] = ()
    dependency_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.upstream_node_id, "research upstream node")
        _token(self.downstream_node_id, "research downstream node")
        if self.upstream_node_id == self.downstream_node_id:
            raise ValueError("research dependency cannot target itself")
        if type(self.bindings) is not tuple or any(
            type(row) is not ResearchInputBinding for row in self.bindings
        ):
            raise TypeError("research dependency bindings must be typed tuple")
        bindings = tuple(sorted(self.bindings, key=lambda row: row.input_name))
        names = tuple(row.input_name for row in bindings)
        if len(names) != len(set(names)):
            raise ValueError("research dependency input names must be unique")
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(
            self,
            "dependency_digest",
            canonical_digest(
                {
                    "upstream_node_id": self.upstream_node_id,
                    "downstream_node_id": self.downstream_node_id,
                    "bindings": tuple(
                        {
                            "input_name": row.input_name,
                            "output_name": row.output_name,
                            "kind": row.kind.value,
                        }
                        for row in bindings
                    ),
                }
            ),
        )

    @classmethod
    def after(
        cls,
        upstream_node_id: str,
        downstream_node_id: str,
    ) -> "ResearchDependency":
        return cls(upstream_node_id, downstream_node_id)


@dataclass(frozen=True, slots=True)
class ResearchNode:
    node_id: str
    kind: ResearchNodeKind
    definition_ids: tuple[str, ...] = ()
    outputs: tuple[ResearchOutputSpec, ...] = ()
    config: JsonValue = None
    node_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.node_id, "research node_id")
        if not isinstance(self.kind, ResearchNodeKind):
            raise TypeError("research node kind must be typed")
        definitions = _tokens(self.definition_ids, "research node definition")
        if type(self.outputs) is not tuple or any(
            type(row) is not ResearchOutputSpec for row in self.outputs
        ):
            raise TypeError("research node outputs must be typed tuple")
        outputs = tuple(sorted(self.outputs, key=lambda row: (row.kind.value, row.name)))
        output_keys = tuple((row.kind, row.name) for row in outputs)
        if len(output_keys) != len(set(output_keys)):
            raise ValueError("research node output kind/name pairs must be unique")
        config = freeze_json(self.config)
        object.__setattr__(self, "definition_ids", definitions)
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "config", config)
        object.__setattr__(
            self,
            "node_digest",
            canonical_digest(
                {
                    "node_id": self.node_id,
                    "kind": self.kind.value,
                    "definition_ids": definitions,
                    "outputs": tuple(
                        {"name": row.name, "kind": row.kind.value}
                        for row in outputs
                    ),
                    "config": config,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchProgram:
    program_id: str
    definitions: tuple[ResearchDefinition, ...]
    nodes: tuple[ResearchNode, ...]
    dependencies: tuple[ResearchDependency, ...] = ()
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.program_id, "research program_id")
        if type(self.definitions) is not tuple or any(
            type(row) is not ResearchDefinition for row in self.definitions
        ):
            raise TypeError("research definitions must be typed tuple")
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(row) is not ResearchNode for row in self.nodes
        ):
            raise TypeError("research nodes must be non-empty typed tuple")
        if type(self.dependencies) is not tuple or any(
            type(row) is not ResearchDependency for row in self.dependencies
        ):
            raise TypeError("research dependencies must be typed tuple")

        definitions = tuple(sorted(self.definitions, key=lambda row: row.definition_id))
        nodes = tuple(sorted(self.nodes, key=lambda row: row.node_id))
        dependencies = tuple(
            sorted(
                self.dependencies,
                key=lambda row: (
                    row.downstream_node_id,
                    row.upstream_node_id,
                    row.dependency_digest,
                ),
            )
        )
        definition_ids = tuple(row.definition_id for row in definitions)
        node_ids = tuple(row.node_id for row in nodes)
        if len(definition_ids) != len(set(definition_ids)):
            raise ValueError("research definition identities must be unique")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("research node identities must be unique")
        known_definitions = set(definition_ids)
        known_nodes = set(node_ids)
        by_node = {row.node_id: row for row in nodes}

        for node in nodes:
            unknown = tuple(
                value for value in node.definition_ids
                if value not in known_definitions
            )
            if unknown:
                raise ValueError(
                    f"research node {node.node_id!r} references unknown definitions: {unknown}"
                )

        downstream_inputs: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        upstream_by_downstream: dict[str, list[str]] = {
            node_id: [] for node_id in node_ids
        }
        for dependency in dependencies:
            if dependency.upstream_node_id not in known_nodes:
                raise ValueError(
                    f"research dependency references unknown upstream node: "
                    f"{dependency.upstream_node_id!r}"
                )
            if dependency.downstream_node_id not in known_nodes:
                raise ValueError(
                    f"research dependency references unknown downstream node: "
                    f"{dependency.downstream_node_id!r}"
                )
            upstream = by_node[dependency.upstream_node_id]
            output_keys = {(row.kind, row.name) for row in upstream.outputs}
            for binding in dependency.bindings:
                if (binding.kind, binding.output_name) not in output_keys:
                    raise ValueError(
                        f"research dependency {dependency.upstream_node_id!r} -> "
                        f"{dependency.downstream_node_id!r} references missing output "
                        f"{binding.kind.value}:{binding.output_name}"
                    )
                names = downstream_inputs[dependency.downstream_node_id]
                if binding.input_name in names:
                    raise ValueError(
                        f"research node {dependency.downstream_node_id!r} receives "
                        f"duplicate input {binding.input_name!r}"
                    )
                names.add(binding.input_name)
            upstream_by_downstream[dependency.downstream_node_id].append(
                dependency.upstream_node_id
            )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise ValueError(f"research dependency cycle at node {node_id!r}")
            visiting.add(node_id)
            for upstream in upstream_by_downstream[node_id]:
                visit(upstream)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)

        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest(
                {
                    "program_id": self.program_id,
                    "definitions": tuple(row.definition_digest for row in definitions),
                    "nodes": tuple(row.node_digest for row in nodes),
                    "dependencies": tuple(
                        row.dependency_digest for row in dependencies
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchNodeRef:
    program_id: str
    node_id: str

    def __post_init__(self) -> None:
        _token(self.program_id, "research node reference program_id")
        _token(self.node_id, "research node reference node_id")


@dataclass(frozen=True, slots=True)
class ResearchPortfolioDependency:
    upstream: ResearchNodeRef
    downstream: ResearchNodeRef
    bindings: tuple[ResearchInputBinding, ...] = ()
    dependency_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.upstream) is not ResearchNodeRef:
            raise TypeError("portfolio upstream must be ResearchNodeRef")
        if type(self.downstream) is not ResearchNodeRef:
            raise TypeError("portfolio downstream must be ResearchNodeRef")
        if self.upstream == self.downstream:
            raise ValueError("portfolio dependency cannot target itself")
        if self.upstream.program_id == self.downstream.program_id:
            raise ValueError(
                "same-program dependencies belong inside ResearchProgram"
            )
        if type(self.bindings) is not tuple or any(
            type(row) is not ResearchInputBinding for row in self.bindings
        ):
            raise TypeError("portfolio dependency bindings must be typed tuple")
        bindings = tuple(sorted(self.bindings, key=lambda row: row.input_name))
        names = tuple(row.input_name for row in bindings)
        if len(names) != len(set(names)):
            raise ValueError("portfolio dependency input names must be unique")
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(
            self,
            "dependency_digest",
            canonical_digest(
                {
                    "upstream": (
                        self.upstream.program_id,
                        self.upstream.node_id,
                    ),
                    "downstream": (
                        self.downstream.program_id,
                        self.downstream.node_id,
                    ),
                    "bindings": tuple(
                        {
                            "input_name": row.input_name,
                            "output_name": row.output_name,
                            "kind": row.kind.value,
                        }
                        for row in bindings
                    ),
                }
            ),
        )


RESEARCH_PORTFOLIO_SCHEMA = "noetrium.research-portfolio.v2"


def _research_binding_document(binding: ResearchInputBinding) -> dict[str, object]:
    return {
        "input_name": binding.input_name,
        "output_name": binding.output_name,
        "kind": binding.kind.value,
    }


def _research_implementation_document(
    implementation: ResearchImplementation | ResearchMethodProgramImplementation,
) -> dict[str, object]:
    if type(implementation) is ResearchImplementation:
        return {
            "implementation_type": "callable",
            "implementation_id": implementation.implementation_id,
            "module": implementation.module,
            "qualname": implementation.qualname,
            "source_digest": implementation.source_digest,
            "implementation_digest": implementation.implementation_digest,
        }
    if type(implementation) is ResearchMethodProgramImplementation:
        return {
            "implementation_type": "method_program",
            "implementation_id": implementation.implementation_id,
            "module": implementation.module,
            "qualname": implementation.qualname,
            "program_digest": implementation.program_digest,
            "implementation_digest": implementation.implementation_digest,
        }
    raise TypeError("research implementation document requires typed implementation")


def _research_definition_document(
    definition: ResearchDefinition,
) -> dict[str, object]:
    return {
        "definition_id": definition.definition_id,
        "kind": definition.kind.value,
        "implementation": (
            None
            if definition.implementation is None
            else _research_implementation_document(definition.implementation)
        ),
        "config": definition.config,
        "definition_digest": definition.definition_digest,
    }


def _research_node_document(node: ResearchNode) -> dict[str, object]:
    return {
        "node_id": node.node_id,
        "kind": node.kind.value,
        "definition_ids": node.definition_ids,
        "outputs": tuple(
            {"name": output.name, "kind": output.kind.value}
            for output in node.outputs
        ),
        "config": node.config,
        "node_digest": node.node_digest,
    }


def _research_dependency_document(
    dependency: ResearchDependency,
) -> dict[str, object]:
    return {
        "upstream_node_id": dependency.upstream_node_id,
        "downstream_node_id": dependency.downstream_node_id,
        "bindings": tuple(
            _research_binding_document(binding)
            for binding in dependency.bindings
        ),
        "dependency_digest": dependency.dependency_digest,
    }


def _research_program_document(program: ResearchProgram) -> dict[str, object]:
    return {
        "program_id": program.program_id,
        "definitions": tuple(
            _research_definition_document(definition)
            for definition in program.definitions
        ),
        "nodes": tuple(
            _research_node_document(node)
            for node in program.nodes
        ),
        "dependencies": tuple(
            _research_dependency_document(dependency)
            for dependency in program.dependencies
        ),
        "program_digest": program.program_digest,
    }


def _research_portfolio_dependency_document(
    dependency: ResearchPortfolioDependency,
) -> dict[str, object]:
    return {
        "upstream": {
            "program_id": dependency.upstream.program_id,
            "node_id": dependency.upstream.node_id,
        },
        "downstream": {
            "program_id": dependency.downstream.program_id,
            "node_id": dependency.downstream.node_id,
        },
        "bindings": tuple(
            _research_binding_document(binding)
            for binding in dependency.bindings
        ),
        "dependency_digest": dependency.dependency_digest,
    }


def _research_portfolio_document(portfolio: "ResearchPortfolio") -> dict[str, object]:
    return {
        "schema": RESEARCH_PORTFOLIO_SCHEMA,
        "portfolio_id": portfolio.portfolio_id,
        "programs": tuple(
            _research_program_document(program)
            for program in portfolio.programs
        ),
        "dependencies": tuple(
            _research_portfolio_dependency_document(dependency)
            for dependency in portfolio.dependencies
        ),
    }


@dataclass(frozen=True, slots=True)
class ResearchPortfolio:
    portfolio_id: str
    programs: tuple[ResearchProgram, ...]
    dependencies: tuple[ResearchPortfolioDependency, ...] = ()
    portfolio_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.portfolio_id, "research portfolio_id")
        if type(self.programs) is not tuple or not self.programs or any(
            type(row) is not ResearchProgram for row in self.programs
        ):
            raise TypeError("research portfolio programs must be non-empty typed tuple")
        if type(self.dependencies) is not tuple or any(
            type(row) is not ResearchPortfolioDependency
            for row in self.dependencies
        ):
            raise TypeError("research portfolio dependencies must be typed tuple")
        programs = tuple(sorted(self.programs, key=lambda row: row.program_id))
        ids = tuple(row.program_id for row in programs)
        if len(ids) != len(set(ids)):
            raise ValueError("research portfolio program identities must be unique")
        program_by_id = {row.program_id: row for row in programs}
        node_by_ref = {
            ResearchNodeRef(program.program_id, node.node_id): node
            for program in programs
            for node in program.nodes
        }
        dependencies = tuple(
            sorted(
                self.dependencies,
                key=lambda row: (
                    row.downstream.program_id,
                    row.downstream.node_id,
                    row.upstream.program_id,
                    row.upstream.node_id,
                    row.dependency_digest,
                ),
            )
        )
        seen_edges: set[tuple[ResearchNodeRef, ResearchNodeRef]] = set()
        downstream_inputs: dict[ResearchNodeRef, set[str]] = {
            ref: set() for ref in node_by_ref
        }
        upstream_by_downstream: dict[ResearchNodeRef, list[ResearchNodeRef]] = {
            ref: [] for ref in node_by_ref
        }

        for program in programs:
            for edge in program.dependencies:
                upstream = ResearchNodeRef(program.program_id, edge.upstream_node_id)
                downstream = ResearchNodeRef(program.program_id, edge.downstream_node_id)
                upstream_by_downstream[downstream].append(upstream)
                downstream_inputs[downstream].update(
                    binding.input_name for binding in edge.bindings
                )

        for dependency in dependencies:
            if dependency.upstream not in node_by_ref:
                raise ValueError(
                    "portfolio dependency references unknown upstream node: "
                    f"{dependency.upstream.program_id}:{dependency.upstream.node_id}"
                )
            if dependency.downstream not in node_by_ref:
                raise ValueError(
                    "portfolio dependency references unknown downstream node: "
                    f"{dependency.downstream.program_id}:{dependency.downstream.node_id}"
                )
            edge_key = (dependency.upstream, dependency.downstream)
            if edge_key in seen_edges:
                raise ValueError("portfolio dependencies must not repeat an edge")
            seen_edges.add(edge_key)
            upstream_node = node_by_ref[dependency.upstream]
            output_keys = {
                (row.kind, row.name) for row in upstream_node.outputs
            }
            names = downstream_inputs[dependency.downstream]
            for binding in dependency.bindings:
                if (binding.kind, binding.output_name) not in output_keys:
                    raise ValueError(
                        "portfolio dependency references missing upstream output "
                        f"{binding.kind.value}:{binding.output_name}"
                    )
                if binding.input_name in names:
                    raise ValueError(
                        "portfolio downstream node receives duplicate input "
                        f"{binding.input_name!r}"
                    )
                names.add(binding.input_name)
            upstream_by_downstream[dependency.downstream].append(
                dependency.upstream
            )

        visiting: set[ResearchNodeRef] = set()
        visited: set[ResearchNodeRef] = set()

        def visit(ref: ResearchNodeRef) -> None:
            if ref in visited:
                return
            if ref in visiting:
                raise ValueError(
                    "research portfolio dependency cycle at "
                    f"{ref.program_id}:{ref.node_id}"
                )
            visiting.add(ref)
            for upstream in upstream_by_downstream[ref]:
                visit(upstream)
            visiting.remove(ref)
            visited.add(ref)

        for ref in sorted(
            node_by_ref,
            key=lambda row: (row.program_id, row.node_id),
        ):
            visit(ref)

        object.__setattr__(self, "programs", programs)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self,
            "portfolio_digest",
            canonical_digest(_research_portfolio_document(self)),
        )


class ResearchPortfolioBuilder:
    """Compose many papers/programs into one cross-program research graph."""

    def __init__(self, portfolio_id: str) -> None:
        _token(portfolio_id, "research portfolio_id")
        self._portfolio_id = portfolio_id
        self._programs: dict[str, ResearchProgram] = {}
        self._dependencies: list[ResearchPortfolioDependency] = []

    def program(self, program: ResearchProgram) -> "ResearchPortfolioBuilder":
        if type(program) is not ResearchProgram:
            raise TypeError("portfolio builder requires ResearchProgram")
        if program.program_id in self._programs:
            raise ValueError(
                f"duplicate research program: {program.program_id}"
            )
        self._programs[program.program_id] = program
        return self

    def depends(
        self,
        *,
        downstream_program_id: str,
        downstream_node_id: str,
        upstream_program_id: str,
        upstream_node_id: str,
        bindings: tuple[ResearchInputBinding, ...] = (),
    ) -> "ResearchPortfolioBuilder":
        self._dependencies.append(
            ResearchPortfolioDependency(
                ResearchNodeRef(upstream_program_id, upstream_node_id),
                ResearchNodeRef(downstream_program_id, downstream_node_id),
                bindings,
            )
        )
        return self

    def freeze(self) -> ResearchPortfolio:
        return ResearchPortfolio(
            self._portfolio_id,
            tuple(self._programs.values()),
            tuple(self._dependencies),
        )


@dataclass(frozen=True, slots=True)
class ResearchGraphRevision:
    portfolio_id: str
    portfolio_digest: str
    parent_revision_digests: tuple[str, ...] = ()
    message: str = ""
    revision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.portfolio_id, "research revision portfolio_id")
        require_sha256(self.portfolio_digest, "research revision portfolio_digest")
        parents = self.parent_revision_digests
        if type(parents) is not tuple:
            raise TypeError("research revision parents must be a tuple")
        for parent in parents:
            require_sha256(parent, "research parent revision")
        if len(parents) != len(set(parents)):
            raise ValueError("research revision parents must not contain duplicates")
        if type(self.message) is not str:
            raise TypeError("research revision message must be text")
        object.__setattr__(
            self,
            "revision_digest",
            canonical_digest(
                {
                    "subject_id": self.portfolio_id,
                    "payload_digest": self.portfolio_digest,
                    "parents": parents,
                    "message": self.message,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchBranch:
    portfolio_id: str
    name: str
    revision_digest: str
    generation: int

    def __post_init__(self) -> None:
        _token(self.portfolio_id, "research branch portfolio_id")
        _token(self.name, "research branch")
        require_sha256(self.revision_digest, "research branch revision")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("research branch generation must be positive")


@dataclass(frozen=True, slots=True)
class ResearchTag:
    portfolio_id: str
    name: str
    revision_digest: str

    def __post_init__(self) -> None:
        _token(self.portfolio_id, "research tag portfolio_id")
        _token(self.name, "research tag")
        require_sha256(self.revision_digest, "research tag revision")


class ResearchImpactState(StrEnum):
    UNCHANGED = "unchanged"
    REUSABLE = "reusable"
    NEW = "new"
    STALE = "stale"
    INVALIDATED = "invalidated"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class ResearchNodeImpact:
    program_id: str
    node_id: str
    state: ResearchImpactState

    def __post_init__(self) -> None:
        _token(self.program_id, "research impact program")
        _token(self.node_id, "research impact node")
        if not isinstance(self.state, ResearchImpactState):
            raise TypeError("research impact state must be typed")


@dataclass(frozen=True, slots=True)
class ResearchRevisionDiff:
    portfolio_id: str
    left_revision_digest: str
    right_revision_digest: str
    impacts: tuple[ResearchNodeImpact, ...]

    def __post_init__(self) -> None:
        _token(self.portfolio_id, "research diff portfolio_id")
        require_sha256(self.left_revision_digest, "left research revision")
        require_sha256(self.right_revision_digest, "right research revision")
        if type(self.impacts) is not tuple or any(
            type(row) is not ResearchNodeImpact for row in self.impacts
        ):
            raise TypeError("research revision impacts must be typed tuple")


@dataclass(frozen=True, slots=True)
class ResearchExecutionTarget:
    """Stable live-execution identity bound to one immutable scientific revision."""

    execution_id: str
    revision: ResearchGraphRevision
    node: ResearchNodeRef | None = None
    target_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.execution_id, "research execution_id")
        if type(self.revision) is not ResearchGraphRevision:
            raise TypeError("research execution target requires ResearchGraphRevision")
        if self.node is not None and type(self.node) is not ResearchNodeRef:
            raise TypeError("research execution node must be ResearchNodeRef when provided")
        object.__setattr__(
            self,
            "target_digest",
            canonical_digest(
                {
                    "execution_id": self.execution_id,
                    "portfolio_id": self.revision.portfolio_id,
                    "research_revision_digest": self.revision.revision_digest,
                    "node": (
                        None
                        if self.node is None
                        else {
                            "program_id": self.node.program_id,
                            "node_id": self.node.node_id,
                        }
                    ),
                }
            ),
        )

    @property
    def portfolio_id(self) -> str:
        return self.revision.portfolio_id

    @property
    def research_revision_digest(self) -> str:
        return self.revision.revision_digest

    def for_node(self, program_id: str, node_id: str) -> "ResearchExecutionTarget":
        return ResearchExecutionTarget(
            self.execution_id,
            self.revision,
            ResearchNodeRef(program_id, node_id),
        )


class ResearchControlAction(StrEnum):
    RUN = "run"
    INSPECT = "inspect"
    PAUSE = "pause"
    DRAIN = "drain"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    RETRY = "retry"
    CANCEL = "cancel"
    CHECKPOINT = "checkpoint"
    RECONCILE = "reconcile"
    MIGRATE = "migrate"


@dataclass(frozen=True, slots=True)
class ResearchControlRequest:
    action: ResearchControlAction
    target: ResearchExecutionTarget
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchControlAction):
            raise TypeError("research control action must be typed")
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("research control target must be ResearchExecutionTarget")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class ResearchControlReceipt:
    action: ResearchControlAction
    target: ResearchExecutionTarget
    state: str
    control_revision_digest: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchControlAction):
            raise TypeError("research control receipt action must be typed")
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("research control receipt target must be ResearchExecutionTarget")
        if not isinstance(self.state, str) or not self.state.strip():
            raise ValueError("research control receipt state must be non-empty")
        require_sha256(
            self.control_revision_digest,
            "research control state revision",
        )
        object.__setattr__(self, "state", self.state.strip())
        object.__setattr__(self, "payload", freeze_json(self.payload))


@runtime_checkable
class ResearchOS(Protocol):
    """Bound top-level Research OS capability presented to downstream authors."""

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[ResearchGraphRevision, ...] = (),
        message: str = "",
    ) -> ResearchGraphRevision: ...

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff: ...

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None = None,
    ) -> ResearchBranch: ...

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag: ...

    def merge(
        self,
        portfolio: ResearchPortfolio,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str = "",
    ) -> ResearchGraphRevision: ...

    def run(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def inspect(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def pause(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def drain(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def interrupt(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def resume(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def retry(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def cancel(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def checkpoint(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def reconcile(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def migrate(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...


class ResearchOSPort(Protocol):
    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[ResearchGraphRevision, ...],
        message: str,
    ) -> ResearchGraphRevision: ...

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff: ...

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None,
    ) -> ResearchBranch: ...

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag: ...

    def merge(
        self,
        portfolio: ResearchPortfolio,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str,
    ) -> ResearchGraphRevision: ...

    def control(self, request: ResearchControlRequest) -> ResearchControlReceipt: ...


class _BoundResearchOS:
    """Internal facade over one platform-composed ResearchOSPort."""

    def __init__(self, port: ResearchOSPort) -> None:
        required = ("commit", "diff", "branch", "tag", "merge", "control")
        if any(not callable(getattr(port, name, None)) for name in required):
            raise TypeError("research OS port does not satisfy the unified product contract")
        self._port = port

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[ResearchGraphRevision, ...] = (),
        message: str = "",
    ) -> ResearchGraphRevision:
        if type(parents) is not tuple or any(
            type(parent) is not ResearchGraphRevision for parent in parents
        ):
            raise TypeError("research commit parents must be ResearchGraphRevision tuple")
        if any(parent.portfolio_id != portfolio.portfolio_id for parent in parents):
            raise ValueError("research commit parents must belong to the same portfolio")
        return self._port.commit(portfolio, parents=parents, message=message)

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff:
        if type(left) is not ResearchGraphRevision or type(right) is not ResearchGraphRevision:
            raise TypeError("research diff requires ResearchGraphRevision values")
        if left.portfolio_id != right.portfolio_id:
            raise ValueError("research diff revisions must belong to the same portfolio")
        return self._port.diff(left, right)

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None = None,
    ) -> ResearchBranch:
        if type(revision) is not ResearchGraphRevision:
            raise TypeError("research branch requires ResearchGraphRevision")
        if expected is not None:
            if type(expected) is not ResearchGraphRevision:
                raise TypeError("research expected branch revision must be ResearchGraphRevision")
            if expected.portfolio_id != revision.portfolio_id:
                raise ValueError("research branch revisions must belong to the same portfolio")
        return self._port.branch(name, revision, expected=expected)

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag:
        if type(revision) is not ResearchGraphRevision:
            raise TypeError("research tag requires ResearchGraphRevision")
        return self._port.tag(name, revision)

    def merge(
        self,
        portfolio: ResearchPortfolio,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str = "",
    ) -> ResearchGraphRevision:
        if type(left) is not ResearchGraphRevision or type(right) is not ResearchGraphRevision:
            raise TypeError("research merge requires ResearchGraphRevision parents")
        if left.portfolio_id != portfolio.portfolio_id or right.portfolio_id != portfolio.portfolio_id:
            raise ValueError("research merge parents must belong to the resolved portfolio")
        return self._port.merge(
            portfolio,
            left,
            right,
            message=message,
        )

    def _control(
        self,
        action: ResearchControlAction,
        target: ResearchExecutionTarget,
        payload: JsonInput = None,
    ) -> ResearchControlReceipt:
        if type(target) is not ResearchExecutionTarget:
            raise TypeError("research OS control requires ResearchExecutionTarget")
        receipt = self._port.control(
            ResearchControlRequest(action, target, freeze_json(payload))
        )
        if type(receipt) is not ResearchControlReceipt:
            raise TypeError("research OS control port returned invalid receipt")
        if receipt.action is not action or receipt.target != target:
            raise ValueError("research OS control receipt identity drifted")
        return receipt

    def run(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.RUN, target, payload)

    def inspect(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.INSPECT, target, payload)

    def pause(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.PAUSE, target, payload)

    def drain(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.DRAIN, target, payload)

    def interrupt(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.INTERRUPT, target, payload)

    def resume(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.RESUME, target, payload)

    def retry(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.RETRY, target, payload)

    def cancel(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.CANCEL, target, payload)

    def checkpoint(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.CHECKPOINT, target, payload)

    def reconcile(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.RECONCILE, target, payload)

    def migrate(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt:
        return self._control(ResearchControlAction.MIGRATE, target, payload)


def bind_research_os(port: ResearchOSPort) -> ResearchOS:
    """Internal composition seam; downstream projects never bind ports themselves."""

    return _BoundResearchOS(port)


class ResearchProgramBuilder:
    """High-level authoring surface for all downstream scientific semantics."""

    def __init__(self, program_id: str) -> None:
        _token(program_id, "research program_id")
        self._program_id = program_id
        self._definitions: dict[str, ResearchDefinition] = {}
        self._nodes: dict[str, ResearchNode] = {}
        self._dependencies: list[ResearchDependency] = []

    def definition(
        self,
        definition_id: str,
        *,
        kind: ResearchDefinitionKind,
        implementation: (
            ResearchImplementation
            | ResearchMethodProgramImplementation
            | Callable[..., object]
            | None
        ) = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        resolved = (
            None
            if implementation is None
            else (
                implementation
                if type(implementation)
                in {ResearchImplementation, ResearchMethodProgramImplementation}
                else ResearchImplementation.from_callable(
                    definition_id,
                    implementation,
                )
            )
        )
        row = ResearchDefinition(
            definition_id,
            kind,
            resolved,
            freeze_json(config),
        )
        if row.definition_id in self._definitions:
            raise ValueError(f"duplicate research definition: {row.definition_id}")
        self._definitions[row.definition_id] = row
        return self

    def method(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object],
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.METHOD,
            implementation=implementation,
            config=config,
        )

    def method_program(
        self,
        definition_id: str,
        *,
        module: str,
        qualname: str,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        """Bind an existing immutable MethodProgram as METHOD semantics."""

        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.METHOD,
            implementation=ResearchMethodProgramImplementation.from_symbol(
                definition_id,
                module=module,
                qualname=qualname,
            ),
            config=config,
        )

    def benchmark(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.BENCHMARK,
            implementation=implementation,
            config=config,
        )

    def metric(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object],
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.METRIC,
            implementation=implementation,
            config=config,
        )

    def dataset(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.DATASET,
            implementation=implementation,
            config=config,
        )

    def model(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.MODEL,
            implementation=implementation,
            config=config,
        )

    def environment(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.ENVIRONMENT,
            implementation=implementation,
            config=config,
        )

    def participant(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.PARTICIPANT,
            implementation=implementation,
            config=config,
        )

    def protocol(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.PROTOCOL,
            implementation=implementation,
            config=config,
        )

    def resource_policy(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object] | None = None,
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.RESOURCE_POLICY,
            implementation=implementation,
            config=config,
        )

    def custom_definition(
        self,
        definition_id: str,
        *,
        implementation: ResearchImplementation | Callable[..., object],
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.definition(
            definition_id,
            kind=ResearchDefinitionKind.CUSTOM,
            implementation=implementation,
            config=config,
        )

    def node(
        self,
        node_id: str,
        *,
        kind: ResearchNodeKind,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        row = ResearchNode(
            node_id,
            kind,
            definitions,
            outputs,
            freeze_json(config),
        )
        if row.node_id in self._nodes:
            raise ValueError(f"duplicate research node: {row.node_id}")
        self._nodes[row.node_id] = row
        for upstream in depends_on:
            self._dependencies.append(
                ResearchDependency.after(upstream, node_id)
            )
        return self

    def experiment(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...],
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.EXPERIMENT,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def evaluation(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.EVALUATION,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def analysis(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.ANALYSIS,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def selection(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.SELECTION,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def method_node(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.METHOD,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def study(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.STUDY,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def run_node(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.RUN,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def trial(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.TRIAL,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def optimization(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.OPTIMIZATION,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def ablation(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.ABLATION,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def robustness(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.ROBUSTNESS,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def scaling(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.SCALING,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def figure(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.FIGURE,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def table(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.TABLE,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def publication(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.PUBLICATION,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def custom_node(
        self,
        node_id: str,
        *,
        definitions: tuple[str, ...] = (),
        outputs: tuple[ResearchOutputSpec, ...] = (),
        depends_on: tuple[str, ...] = (),
        config: JsonInput = None,
    ) -> "ResearchProgramBuilder":
        return self.node(
            node_id,
            kind=ResearchNodeKind.CUSTOM,
            definitions=definitions,
            outputs=outputs,
            depends_on=depends_on,
            config=config,
        )

    def depends(
        self,
        downstream_node_id: str,
        upstream_node_id: str,
        *,
        bindings: tuple[ResearchInputBinding, ...] = (),
    ) -> "ResearchProgramBuilder":
        self._dependencies.append(
            ResearchDependency(
                upstream_node_id,
                downstream_node_id,
                bindings,
            )
        )
        return self

    def freeze(self) -> ResearchProgram:
        return ResearchProgram(
            self._program_id,
            tuple(self._definitions.values()),
            tuple(self._nodes.values()),
            tuple(self._dependencies),
        )


__all__ = [
    "ResearchBranch",
    "ResearchControlAction",
    "ResearchControlReceipt",
    "ResearchControlRequest",
    "ResearchDefinition",
    "ResearchDefinitionKind",
    "ResearchDependency",
    "ResearchExecutionTarget",
    "ResearchGraphRevision",
    "ResearchImpactState",
    "ResearchImplementation",
    "ResearchMethodProgramImplementation",
    "ResearchInputBinding",
    "ResearchNode",
    "ResearchNodeImpact",
    "ResearchNodeKind",
    "ResearchPortfolioDependency",
    "ResearchPortfolioBuilder",
    "ResearchNodeRef",
    "ResearchOS",
    "ResearchOutputSpec",
    "ResearchPortfolio",
    "ResearchProgram",
    "ResearchProgramBuilder",
    "ResearchRevisionDiff",
    "ResearchTag",
    "ResearchValueKind",
]
