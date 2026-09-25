from __future__ import annotations

from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    ResearchStudyDefinition,
)

from .research_binding_authority import (
    ResearchBindingAuthorityPort,
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


class ResearchStudyProtocolClosureProvider:
    """Resolve generic Experiment nodes from one frozen Study protocol factory."""

    def __init__(
        self,
        research_bindings: ResearchBindingAuthorityPort,
        resolver: ResearchImplementationResolverPort | None = None,
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

    def _study(self, node: CompiledResearchOSGraphNode) -> ResearchStudyDefinition:
        candidates = tuple(
            row
            for row in node.definitions
            if row.kind is ResearchDefinitionKind.PROTOCOL
            and row.implementation is not None
        )
        if len(candidates) != 1:
            raise ValueError(
                "Experiment node requires exactly one implemented PROTOCOL "
                f"Study factory: node={node.graph_node_id} count={len(candidates)}"
            )
        resolved = self._resolver.resolve(candidates[0])
        try:
            study = resolved.implementation()
        except Exception as exc:
            raise RuntimeError(
                "Research Study protocol factory failed: "
                f"{resolved.declared.module}:{resolved.declared.qualname}"
            ) from exc
        if type(study) is not ResearchStudyDefinition:
            raise TypeError(
                "Research Study protocol factory must return "
                "ResearchStudyDefinition"
            )
        return study

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
        return compile_research_os_experiment_closure(
            graph_id=graph_id,
            graph_digest=graph_digest,
            research_revision_digest=research_revision_digest,
            node=node,
            definition=study,
            resolution=resolution,
            binding=binding,
        )


__all__ = ["ResearchStudyProtocolClosureProvider"]
