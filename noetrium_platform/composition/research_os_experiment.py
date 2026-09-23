from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.api import (
    CompiledExperimentProgram,
    CompiledResearchPlan,
    ResearchBindingContribution,
    ResearchRequirementResolution,
    ResearchStudyDefinition,
    compile_experiment_program,
    compile_research_plan,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    BoundStudyExecutionPort,
    RunArtifactStorePort,
    StudyMetricAggregationPort,
)

from .research_os_graph import CompiledResearchOSGraphNode


def _text(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentClosure:
    """Exact bridge from one ResearchGraph node into existing Experimentation IR."""

    source_graph_id: str
    source_graph_digest: str
    source_revision_digest: str
    source_graph_node_id: str
    source_semantic_digest: str
    source_definition_digests: tuple[tuple[str, str], ...]
    definition: ResearchStudyDefinition
    resolution: ResearchRequirementResolution
    binding: ResearchBindingContribution
    research_plan: CompiledResearchPlan
    experiment_program: CompiledExperimentProgram
    closure_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.source_graph_id, "experiment closure source_graph_id")
        require_sha256(self.source_graph_digest, "experiment closure source_graph_digest")
        require_sha256(
            self.source_revision_digest,
            "experiment closure source_revision_digest",
        )
        _text(self.source_graph_node_id, "experiment closure source_graph_node_id")
        require_sha256(
            self.source_semantic_digest,
            "experiment closure source_semantic_digest",
        )
        if type(self.source_definition_digests) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or type(row[1]) is not str
            for row in self.source_definition_digests
        ):
            raise TypeError(
                "experiment closure source_definition_digests must be typed pairs"
            )
        ordered_definitions = tuple(sorted(self.source_definition_digests))
        ids = tuple(row[0] for row in ordered_definitions)
        if len(ids) != len(set(ids)):
            raise ValueError("experiment closure source definitions must be unique")
        for _definition_id, digest in ordered_definitions:
            require_sha256(digest, "experiment closure source definition digest")
        if type(self.definition) is not ResearchStudyDefinition:
            raise TypeError(
                "experiment closure definition must be ResearchStudyDefinition"
            )
        if type(self.resolution) is not ResearchRequirementResolution:
            raise TypeError(
                "experiment closure resolution must be ResearchRequirementResolution"
            )
        if type(self.binding) is not ResearchBindingContribution:
            raise TypeError(
                "experiment closure binding must be ResearchBindingContribution"
            )
        if type(self.research_plan) is not CompiledResearchPlan:
            raise TypeError(
                "experiment closure research_plan must be CompiledResearchPlan"
            )
        if type(self.experiment_program) is not CompiledExperimentProgram:
            raise TypeError(
                "experiment closure experiment_program must be CompiledExperimentProgram"
            )

        expected_plan = compile_research_plan(
            self.definition,
            self.resolution,
            self.binding,
        )
        if expected_plan != self.research_plan:
            raise ValueError(
                "experiment closure research plan drifted from canonical compiler"
            )
        expected_program = compile_experiment_program(
            self.research_plan.experiment_plan
        )
        if expected_program != self.experiment_program:
            raise ValueError(
                "experiment closure ExperimentProgram drifted from canonical compiler"
            )
        if (
            self.research_plan.requirement_resolution_digest
            != self.resolution.resolution_digest
        ):
            raise ValueError(
                "experiment closure requirement resolution identity drifted"
            )
        if self.research_plan.binding_digest != self.binding.contribution_digest:
            raise ValueError("experiment closure binding identity drifted")

        object.__setattr__(
            self,
            "source_definition_digests",
            ordered_definitions,
        )
        object.__setattr__(
            self,
            "closure_digest",
            canonical_digest(
                {
                    "source_graph_id": self.source_graph_id,
                    "source_graph_digest": self.source_graph_digest,
                    "source_revision_digest": self.source_revision_digest,
                    "source_graph_node_id": self.source_graph_node_id,
                    "source_semantic_digest": self.source_semantic_digest,
                    "source_definition_digests": ordered_definitions,
                    "study_definition_digest": self.definition.definition_digest,
                    "requirement_resolution_digest": self.resolution.resolution_digest,
                    "binding_digest": self.binding.contribution_digest,
                    "research_plan_digest": self.research_plan.research_plan_digest,
                    "experiment_program_digest": (
                        self.experiment_program.program.program_digest
                    ),
                    "experiment_batch_plan_digest": (
                        self.experiment_program.batch_plan_digest
                    ),
                }
            ),
        )

    def validate_source(
        self,
        *,
        graph_id: str,
        graph_digest: str,
        research_revision_digest: str,
        node: CompiledResearchOSGraphNode,
    ) -> None:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError(
                "experiment closure validation requires compiled graph node"
            )
        expected_definitions = tuple(
            sorted(
                (
                    definition.definition_id,
                    definition.definition_digest,
                )
                for definition in node.definitions
            )
        )
        if (
            self.source_graph_id != graph_id
            or self.source_graph_digest != graph_digest
            or self.source_revision_digest != research_revision_digest
            or self.source_graph_node_id != node.graph_node_id
            or self.source_semantic_digest != node.semantic_digest
            or self.source_definition_digests != expected_definitions
        ):
            raise ValueError(
                "experiment closure does not belong to the requested ResearchGraph node"
            )


class ResearchOSExperimentClosureMissing(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResearchOSExperimentRuntimeBinding:
    """Exact runtime objects plus immutable identity for one experiment closure."""

    closure_digest: str
    study_plan_digest: str
    research_binding_digest: str
    adapter: BoundStudyExecutionPort
    aggregation: StudyMetricAggregationPort
    artifacts: RunArtifactStorePort
    adapter_identity_digest: str
    aggregation_identity_digest: str
    artifact_store_identity_digest: str
    runtime_binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(
            self.closure_digest,
            "experiment runtime binding closure_digest",
        )
        require_sha256(
            self.study_plan_digest,
            "experiment runtime binding study_plan_digest",
        )
        require_sha256(
            self.research_binding_digest,
            "experiment runtime binding research_binding_digest",
        )
        if not isinstance(self.adapter, BoundStudyExecutionPort):
            raise TypeError(
                "experiment runtime binding adapter must satisfy BoundStudyExecutionPort"
            )
        if not callable(getattr(self.aggregation, "aggregate", None)):
            raise TypeError(
                "experiment runtime binding aggregation must satisfy "
                "StudyMetricAggregationPort"
            )
        if not isinstance(self.artifacts, RunArtifactStorePort):
            raise TypeError(
                "experiment runtime binding artifacts must satisfy RunArtifactStorePort"
            )
        for field_name, value in (
            ("adapter_identity_digest", self.adapter_identity_digest),
            ("aggregation_identity_digest", self.aggregation_identity_digest),
            ("artifact_store_identity_digest", self.artifact_store_identity_digest),
        ):
            require_sha256(value, f"experiment runtime binding {field_name}")
        object.__setattr__(
            self,
            "runtime_binding_digest",
            canonical_digest(
                {
                    "closure_digest": self.closure_digest,
                    "study_plan_digest": self.study_plan_digest,
                    "research_binding_digest": self.research_binding_digest,
                    "adapter_identity_digest": self.adapter_identity_digest,
                    "aggregation_identity_digest": self.aggregation_identity_digest,
                    "artifact_store_identity_digest": self.artifact_store_identity_digest,
                }
            ),
        )

    def validate_closure(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> None:
        if type(closure) is not ResearchOSExperimentClosure:
            raise TypeError(
                "experiment runtime binding validation requires closure"
            )
        if (
            self.closure_digest != closure.closure_digest
            or self.study_plan_digest
            != closure.experiment_program.plan.plan_digest
            or self.research_binding_digest
            != closure.research_plan.binding_digest
        ):
            raise ValueError(
                "experiment runtime binding does not belong to the closure"
            )


@runtime_checkable
class ResearchOSExperimentRuntimeBindingPort(Protocol):
    def resolve(
        self,
        closure: ResearchOSExperimentClosure,
    ) -> ResearchOSExperimentRuntimeBinding: ...


@runtime_checkable
class ResearchOSExperimentClosurePort(Protocol):
    """Platform-owned resolver of a complete, proof-backed Experimentation closure."""

    def resolve(
        self,
        *,
        graph_id: str,
        graph_digest: str,
        research_revision_digest: str,
        node: CompiledResearchOSGraphNode,
    ) -> ResearchOSExperimentClosure: ...


def compile_research_os_experiment_closure(
    *,
    graph_id: str,
    graph_digest: str,
    research_revision_digest: str,
    node: CompiledResearchOSGraphNode,
    definition: ResearchStudyDefinition,
    resolution: ResearchRequirementResolution,
    binding: ResearchBindingContribution,
) -> ResearchOSExperimentClosure:
    """Use only the existing Experimentation compiler to create the closure."""

    if type(node) is not CompiledResearchOSGraphNode:
        raise TypeError(
            "experiment closure compilation requires compiled graph node"
        )
    plan = compile_research_plan(definition, resolution, binding)
    program = compile_experiment_program(plan.experiment_plan)
    closure = ResearchOSExperimentClosure(
        graph_id,
        graph_digest,
        research_revision_digest,
        node.graph_node_id,
        node.semantic_digest,
        tuple(
            sorted(
                (
                    row.definition_id,
                    row.definition_digest,
                )
                for row in node.definitions
            )
        ),
        definition,
        resolution,
        binding,
        plan,
        program,
    )
    closure.validate_source(
        graph_id=graph_id,
        graph_digest=graph_digest,
        research_revision_digest=research_revision_digest,
        node=node,
    )
    return closure


__all__ = [
    "ResearchOSExperimentClosure",
    "ResearchOSExperimentClosureMissing",
    "ResearchOSExperimentClosurePort",
    "ResearchOSExperimentRuntimeBinding",
    "ResearchOSExperimentRuntimeBindingPort",
    "compile_research_os_experiment_closure",
]
