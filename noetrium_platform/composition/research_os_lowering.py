from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import importlib
from typing import Callable, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product.research_os import (
    ResearchDefinition,
    ResearchImplementation,
    ResearchNodeKind,
)

from .research_os_graph import (
    CompiledResearchOSGraphNode,
    CompiledResearchOSGraph,
)


class ResearchOSLoweringTarget(StrEnum):
    """Existing authority family selected for one top-level research node.

    This is an internal compiler IR.  It does not create a second execution
    authority: every target names an already-existing lower semantic owner.
    """

    METHOD_MACHINE = "method-machine"
    EXPERIMENTATION = "experimentation"
    RUN_MACHINE = "run-machine"
    EVALUATION_MACHINE = "evaluation-machine"
    OPTIMIZATION_MACHINE = "optimization-machine"
    WORKBENCH = "workbench"
    PUBLICATION = "publication"
    CUSTOM = "custom"


_NODE_TARGETS: dict[ResearchNodeKind, ResearchOSLoweringTarget] = {
    ResearchNodeKind.METHOD: ResearchOSLoweringTarget.METHOD_MACHINE,
    ResearchNodeKind.STUDY: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.EXPERIMENT: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.RUN: ResearchOSLoweringTarget.RUN_MACHINE,
    ResearchNodeKind.TRIAL: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.EVALUATION: ResearchOSLoweringTarget.EVALUATION_MACHINE,
    ResearchNodeKind.ANALYSIS: ResearchOSLoweringTarget.WORKBENCH,
    ResearchNodeKind.OPTIMIZATION: ResearchOSLoweringTarget.OPTIMIZATION_MACHINE,
    ResearchNodeKind.SELECTION: ResearchOSLoweringTarget.WORKBENCH,
    ResearchNodeKind.ABLATION: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.ROBUSTNESS: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.SCALING: ResearchOSLoweringTarget.EXPERIMENTATION,
    ResearchNodeKind.FIGURE: ResearchOSLoweringTarget.WORKBENCH,
    ResearchNodeKind.TABLE: ResearchOSLoweringTarget.WORKBENCH,
    ResearchNodeKind.PUBLICATION: ResearchOSLoweringTarget.PUBLICATION,
    ResearchNodeKind.CUSTOM: ResearchOSLoweringTarget.CUSTOM,
}
if set(_NODE_TARGETS) != set(ResearchNodeKind):
    raise RuntimeError("Research OS lowering table must cover every ResearchNodeKind")


class ResearchImplementationResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedResearchImplementation:
    definition_id: str
    declared: ResearchImplementation
    implementation: Callable[..., object]

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("resolved research implementation definition_id is required")
        if type(self.declared) is not ResearchImplementation:
            raise TypeError("resolved research implementation requires ResearchImplementation")
        if not callable(self.implementation):
            raise TypeError("resolved research implementation value must be callable")


@runtime_checkable
class ResearchImplementationResolverPort(Protocol):
    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResolvedResearchImplementation: ...


class ImportResearchImplementationResolver:
    """Resolve frozen implementation coordinates and fail closed on code drift."""

    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResolvedResearchImplementation:
        if type(definition) is not ResearchDefinition:
            raise TypeError("implementation resolution requires ResearchDefinition")
        declared = definition.implementation
        if declared is None:
            raise ResearchImplementationResolutionError(
                f"definition is platform-resolved and has no paper implementation: "
                f"{definition.definition_id}"
            )
        try:
            value: object = importlib.import_module(declared.module)
            for part in declared.qualname.split("."):
                value = getattr(value, part)
        except (ImportError, AttributeError) as exc:
            raise ResearchImplementationResolutionError(
                "research implementation can no longer be imported from its frozen "
                f"coordinates: {declared.module}:{declared.qualname}"
            ) from exc
        if not callable(value):
            raise ResearchImplementationResolutionError(
                "frozen research implementation coordinates no longer resolve to "
                f"a callable: {declared.module}:{declared.qualname}"
            )
        try:
            observed = ResearchImplementation.from_callable(
                declared.implementation_id,
                value,
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ResearchImplementationResolutionError(
                "could not reconstruct research implementation source identity: "
                f"{declared.module}:{declared.qualname}"
            ) from exc
        if observed != declared:
            raise ResearchImplementationResolutionError(
                "research implementation source drifted from the immutable revision: "
                f"{declared.module}:{declared.qualname}; "
                f"declared={declared.implementation_digest} "
                f"observed={observed.implementation_digest}"
            )
        return ResolvedResearchImplementation(
            definition.definition_id,
            declared,
            value,
        )


@dataclass(frozen=True, slots=True)
class LoweredResearchOSGraphNode:
    """Ephemeral executable lowering view over an immutable ResearchGraph node."""

    source: CompiledResearchOSGraphNode
    target: ResearchOSLoweringTarget
    implementations: tuple[ResolvedResearchImplementation, ...] = ()
    platform_requirements: tuple[ResearchDefinition, ...] = ()
    lowering_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.source) is not CompiledResearchOSGraphNode:
            raise TypeError("lowered Research OS node requires compiled graph node")
        if not isinstance(self.target, ResearchOSLoweringTarget):
            raise TypeError("lowered Research OS target must be typed")
        if type(self.implementations) is not tuple or any(
            type(row) is not ResolvedResearchImplementation
            for row in self.implementations
        ):
            raise TypeError("lowered implementations must be a typed tuple")
        if type(self.platform_requirements) is not tuple or any(
            type(row) is not ResearchDefinition
            for row in self.platform_requirements
        ):
            raise TypeError("lowered platform requirements must be ResearchDefinition tuple")

        definitions = {row.definition_id: row for row in self.source.definitions}
        implementation_ids = tuple(row.definition_id for row in self.implementations)
        requirement_ids = tuple(row.definition_id for row in self.platform_requirements)
        if len(implementation_ids) != len(set(implementation_ids)):
            raise ValueError("lowered implementation definitions must be unique")
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("lowered platform requirements must be unique")
        if set(implementation_ids) & set(requirement_ids):
            raise ValueError("one research definition cannot be both implementation and requirement")
        if set(implementation_ids) | set(requirement_ids) != set(definitions):
            raise ValueError("lowered definitions must partition source definitions")
        if any(definitions[key].implementation is None for key in implementation_ids):
            raise ValueError("implementation lowering contains platform-resolved definition")
        if any(definitions[key].implementation is not None for key in requirement_ids):
            raise ValueError("platform requirement contains paper implementation")

        ordered_implementations = tuple(
            sorted(self.implementations, key=lambda row: row.definition_id)
        )
        ordered_requirements = tuple(
            sorted(self.platform_requirements, key=lambda row: row.definition_id)
        )
        object.__setattr__(self, "implementations", ordered_implementations)
        object.__setattr__(self, "platform_requirements", ordered_requirements)
        object.__setattr__(
            self,
            "lowering_digest",
            canonical_digest(
                {
                    "source_semantic_digest": self.source.semantic_digest,
                    "target": self.target.value,
                    "implementations": tuple(
                        (
                            row.definition_id,
                            row.declared.implementation_digest,
                        )
                        for row in ordered_implementations
                    ),
                    "platform_requirements": tuple(
                        (
                            row.definition_id,
                            row.definition_digest,
                        )
                        for row in ordered_requirements
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchOSLoweringPlan:
    graph_id: str
    graph_digest: str
    research_revision_digest: str
    nodes: tuple[LoweredResearchOSGraphNode, ...]
    lowering_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.graph_id) is not str or not self.graph_id.strip():
            raise ValueError("Research OS lowering graph_id is required")
        for name, value in (
            ("graph_digest", self.graph_digest),
            ("research_revision_digest", self.research_revision_digest),
        ):
            if type(value) is not str or len(value) != 64:
                raise ValueError(f"Research OS lowering {name} must be sha256 text")
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(node) is not LoweredResearchOSGraphNode for node in self.nodes
        ):
            raise TypeError("Research OS lowering nodes must be a non-empty typed tuple")
        ordered = tuple(sorted(self.nodes, key=lambda row: row.source.graph_node_id))
        ids = tuple(row.source.graph_node_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("Research OS lowering graph node ids must be unique")
        object.__setattr__(self, "nodes", ordered)
        object.__setattr__(
            self,
            "lowering_digest",
            canonical_digest(
                {
                    "graph_id": self.graph_id,
                    "graph_digest": self.graph_digest,
                    "research_revision_digest": self.research_revision_digest,
                    "nodes": tuple(
                        (row.source.graph_node_id, row.lowering_digest)
                        for row in ordered
                    ),
                }
            ),
        )

    def node(self, graph_node_id: str) -> LoweredResearchOSGraphNode:
        for node in self.nodes:
            if node.source.graph_node_id == graph_node_id:
                return node
        raise KeyError(graph_node_id)


class ResearchOSLoweringCompiler:
    """Compile canonical ResearchGraph nodes toward existing lower authorities."""

    def __init__(
        self,
        resolver: ResearchImplementationResolverPort | None = None,
    ) -> None:
        resolved = resolver or ImportResearchImplementationResolver()
        if not isinstance(resolved, ResearchImplementationResolverPort):
            raise TypeError(
                "Research OS lowering resolver must satisfy "
                "ResearchImplementationResolverPort"
            )
        self._resolver = resolved

    def compile_node(
        self,
        node: CompiledResearchOSGraphNode,
    ) -> LoweredResearchOSGraphNode:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("Research OS lowering requires CompiledResearchOSGraphNode")
        implementations: list[ResolvedResearchImplementation] = []
        requirements: list[ResearchDefinition] = []
        for definition in node.definitions:
            if definition.implementation is None:
                requirements.append(definition)
            else:
                implementations.append(self._resolver.resolve(definition))
        return LoweredResearchOSGraphNode(
            source=node,
            target=_NODE_TARGETS[node.node.kind],
            implementations=tuple(implementations),
            platform_requirements=tuple(requirements),
        )

    def compile(
        self,
        compilation: CompiledResearchOSGraph,
    ) -> ResearchOSLoweringPlan:
        if type(compilation) is not CompiledResearchOSGraph:
            raise TypeError("Research OS lowering requires CompiledResearchOSGraph")
        return ResearchOSLoweringPlan(
            compilation.plan.graph_id,
            compilation.plan.graph_digest,
            compilation.plan.research_revision_digest,
            tuple(self.compile_node(node) for node in compilation.nodes),
        )


def compile_research_os_lowering(
    compilation: CompiledResearchOSGraph,
    *,
    resolver: ResearchImplementationResolverPort | None = None,
) -> ResearchOSLoweringPlan:
    return ResearchOSLoweringCompiler(resolver).compile(compilation)


__all__ = [
    "ImportResearchImplementationResolver",
    "LoweredResearchOSGraphNode",
    "ResearchImplementationResolutionError",
    "ResearchImplementationResolverPort",
    "ResearchOSLoweringCompiler",
    "ResearchOSLoweringPlan",
    "ResearchOSLoweringTarget",
    "ResolvedResearchImplementation",
    "compile_research_os_lowering",
]
