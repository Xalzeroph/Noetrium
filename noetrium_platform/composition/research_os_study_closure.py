from __future__ import annotations

from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
)
from noetrium_platform.research.experimentation.api import (
    ResearchStudyDefinition,
    materialize_research_study_spec,
)

from .research_binding_authority import (
    ResearchBindingAuthorityPort,
)
from .research_definition_authority import (
    ResearchDefinitionBindingAuthorityPort,
)
from .research_os_experiment import (
    ResearchOSExperimentClosure,
    compile_research_os_experiment_closure,
)
from .research_os_graph import CompiledResearchOSGraphNode
from .research_os_lowering import (
    ImportResearchImplementationResolver,
    ResearchImplementationResolverPort,
)


def materialize_research_protocol_definition(
    definition,
    resolver: ResearchImplementationResolverPort | None = None,
    definition_bindings: ResearchDefinitionBindingAuthorityPort | None = None,
) -> ResearchStudyDefinition:
    if definition.kind is not ResearchDefinitionKind.PROTOCOL:
        raise TypeError("research protocol materialization requires PROTOCOL definition")
    if definition.implementation is None:
        if definition_bindings is None:
            raise RuntimeError(
                "platform-resolved PROTOCOL requires definition binding authority"
            )
        binding = definition_bindings.resolve(definition)
        study = binding.binding
        if type(study) is not ResearchStudyDefinition:
            raise TypeError(
                "PROTOCOL owner binding must materialize ResearchStudyDefinition"
            )
        return study
    selected = ImportResearchImplementationResolver() if resolver is None else resolver
    resolved = selected.resolve(definition)
    try:
        study = resolved.implementation()
    except Exception as exc:
        raise RuntimeError("Research Study protocol factory failed: " + f"{resolved.declared.module}:{resolved.declared.qualname}") from exc
    if type(study) is ResearchStudyDefinition:
        return study
    if isinstance(study, dict):
        return materialize_research_study_spec(study)
    raise TypeError("Research Study protocol factory must return a top-level Study mapping")


class ResearchStudyProtocolClosureProvider:
    """Resolve generic Experiment nodes from one frozen Study protocol factory."""

    def __init__(
        self,
        research_bindings: ResearchBindingAuthorityPort,
        resolver: ResearchImplementationResolverPort | None = None,
        definition_bindings: ResearchDefinitionBindingAuthorityPort | None = None,
    ) -> None:
        if not isinstance(research_bindings, ResearchBindingAuthorityPort):
            raise TypeError(
                "Study closure provider requires ResearchBindingAuthorityPort"
            )
        resolved = (
            ImportResearchImplementationResolver()
            if resolver is None
            else resolver
        )
        if not isinstance(resolved, ResearchImplementationResolverPort):
            raise TypeError(
                "Study closure provider resolver must satisfy "
                "ResearchImplementationResolverPort"
            )
        self._research_bindings = research_bindings
        self._resolver = resolved
        if definition_bindings is not None and not isinstance(
            definition_bindings,
            ResearchDefinitionBindingAuthorityPort,
        ):
            raise TypeError(
                "Study closure definition_bindings must satisfy typed port"
            )
        self._definition_bindings = definition_bindings

    def _study(self, node: CompiledResearchOSGraphNode) -> ResearchStudyDefinition:
        candidates = tuple(
            row
            for row in node.definitions
            if row.kind is ResearchDefinitionKind.PROTOCOL
        )
        if len(candidates) != 1:
            raise ValueError(
                "Experiment node requires exactly one PROTOCOL definition: "
                f"node={node.graph_node_id} count={len(candidates)}"
            )
        return materialize_research_protocol_definition(
            candidates[0],
            self._resolver,
            self._definition_bindings,
        )

    def resolve(
        self,
        *,
        graph_id: str,
        graph_digest: str,
        research_revision_digest: str,
        node: CompiledResearchOSGraphNode,
    ) -> ResearchOSExperimentClosure:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError(
                "Study closure provider requires CompiledResearchOSGraphNode"
            )
        study = self._study(node)
        resolved = self._research_bindings.resolve(study)
        if type(resolved) is not tuple or len(resolved) != 2:
            raise TypeError(
                "research binding authority must return "
                "(ResearchRequirementResolution, ResearchBindingContribution)"
            )
        resolution, binding = resolved
        if not binding.binding_assurance_complete:
            raise RuntimeError(
                "Study binding assurance is incomplete; scientific execution "
                "requires all required bindings to be proof-backed: "
                + ",".join(row.gap_digest for row in binding.assurance_gaps)
            )
        return compile_research_os_experiment_closure(
            graph_id=graph_id,
            graph_digest=graph_digest,
            research_revision_digest=research_revision_digest,
            node=node,
            definition=study,
            resolution=resolution,
            binding=binding,
        )


__all__ = ["ResearchStudyProtocolClosureProvider", "materialize_research_protocol_definition"]
