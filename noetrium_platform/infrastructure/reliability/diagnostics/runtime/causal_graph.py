from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort, DiagnosticIndexSessionPort

from .causal_contracts import CausalGraphSnapshot, CausalNodeSnapshot
from .causal_model import CausalGraph
from .causal_projection import ContextProjector, PayloadProjector, ReferenceProjector


class CausalGraphService:
    """Build an immutable causal graph snapshot from backend-independent diagnostic evidence."""

    def __init__(
        self,
        evidence: DiagnosticEvidencePort,
        projectors: tuple[PayloadProjector, ...] | None = None,
    ) -> None:
        self.evidence = evidence
        self.projectors = projectors or (ContextProjector(), ReferenceProjector())

    def _project_object(self, graph: CausalGraph, payload: Mapping[str, JsonValue]) -> str | None:
        object_id = payload.get("failure_id") or payload.get("event_id") or payload.get("mutation_id")
        if not object_id:
            return None
        object_id = str(object_id)
        kind = "failure" if payload.get("failure_id") else "mutation" if payload.get("mutation_id") else "event"
        attrs = {
            key: payload.get(key)
            for key in ("failure_domain", "failure_code", "stage", "event_type", "state_name", "created_at", "timestamp")
            if payload.get(key) is not None
        }
        graph.ensure_node(object_id, kind, **attrs)
        for projector in self.projectors:
            projector.project(graph, object_id, payload)
        return object_id

    def build(
        self,
        root_id: str,
        *,
        related_limit: int = 200,
        index: DiagnosticIndexSessionPort | None = None,
    ) -> CausalGraphSnapshot:
        idx = index or self.evidence
        root_record = idx.locate(root_id)
        if root_record is None:
            raise KeyError(f"object not found: {root_id}")
        graph = CausalGraph()
        self._project_object(graph, root_record.payload)
        for record in idx.related_to(root_id, limit=related_limit):
            self._project_object(graph, record.payload)
        nodes = tuple(
            CausalNodeSnapshot(node.node_id, node.kind, node.attrs)
            for node in sorted(graph.nodes.values(), key=lambda item: (item.kind, item.node_id))
        )
        edges = tuple(
            edge
            for source in sorted(graph.out)
            for edge in sorted(graph.out[source], key=lambda item: (item.relation, item.target))
        )
        return CausalGraphSnapshot(root_id=root_id, nodes=nodes, edges=edges)


__all__ = ["CausalGraphService"]
