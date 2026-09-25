from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import JsonValue

from .causal_model import CausalGraph


def node_id(kind: str, value: object) -> str:
    return f"{kind}:{value}"


class PayloadProjector(Protocol):
    def project(self, graph: CausalGraph, object_id: str, payload: Mapping[str, JsonValue]) -> None: ...


@dataclass(frozen=True, slots=True)
class ContextProjector:
    mapping: tuple[tuple[str, str, str], ...] = (
        ("run_id", "run", "within_run"),
        ("study_id", "study", "within_study"),
        ("condition_id", "condition", "within_condition"),
        ("task_id", "task", "within_task"),
        ("decision_cycle_id", "decision_cycle", "within_decision_cycle"),
        ("trace_id", "trace", "within_trace"),
        ("span_id", "span", "within_span"),
        ("checkpoint_id", "checkpoint", "after_checkpoint"),
    )

    def project(self, graph: CausalGraph, object_id: str, payload: Mapping[str, JsonValue]) -> None:
        context = payload.get("context") or {}
        if not isinstance(context, Mapping):
            return
        for field_name, kind, relation in self.mapping:
            value = context.get(field_name)
            if value:
                target = node_id(kind, value)
                graph.ensure_node(target, kind, value=value)
                graph.ensure_edge(object_id, relation, target)
        operation_id = payload.get("operation_id") or context.get("operation_id")
        if operation_id:
            target = node_id("operation", operation_id)
            graph.ensure_node(target, "operation", value=operation_id, operation_type=payload.get("operation_type"))
            graph.ensure_edge(object_id, "caused_by" if payload.get("failure_id") else "belongs_to_operation", target)
        request_digest = payload.get("operation_payload_digest")
        if request_digest:
            request = node_id("request", request_digest)
            graph.ensure_node(request, "request", digest=request_digest)
            graph.ensure_edge(object_id, "references_request", request)
            if operation_id:
                graph.ensure_edge(node_id("operation", operation_id), "consumed_request", request)
        idempotency_key = payload.get("operation_idempotency_key")
        if idempotency_key:
            key_node = node_id("idempotency_key", idempotency_key)
            graph.ensure_node(key_node, "idempotency_key", value=idempotency_key)
            if operation_id:
                graph.ensure_edge(node_id("operation", operation_id), "uses_idempotency_key", key_node)
        component_id = payload.get("component_id") or context.get("component_id")
        if component_id:
            target = node_id("component", component_id)
            graph.ensure_node(target, "component", value=component_id)
            graph.ensure_edge(object_id, "emitted_by", target)
            if operation_id:
                graph.ensure_edge(node_id("operation", operation_id), "executed_by", target)


@dataclass(frozen=True, slots=True)
class ReferenceProjector:
    mappings: tuple[tuple[str, str, str], ...] = (
        ("artifact_refs", "artifact", "references_artifact"),
        ("input_artifacts", "artifact", "consumed_artifact"),
        ("output_artifacts", "artifact", "produced_artifact"),
        ("request_refs", "request", "references_request"),
        ("effect_refs", "effect", "references_effect"),
        ("state_refs", "state", "references_state"),
        ("state_reads", "state", "read_state"),
        ("state_mutations", "state", "mutated_state"),
        ("correlation_refs", "correlation", "correlates_with"),
    )

    def project(self, graph: CausalGraph, object_id: str, payload: Mapping[str, JsonValue]) -> None:
        for field_name, kind, relation in self.mappings:
            values = payload.get(field_name) or ()
            if isinstance(values, str):
                values = (values,)
            if not isinstance(values, (list, tuple)):
                continue
            for value in values:
                if value:
                    target = node_id(kind, value)
                    graph.ensure_node(target, kind, value=value)
                    graph.ensure_edge(object_id, relation, target)
        state_name = payload.get("state_name")
        if state_name:
            target = node_id("state", state_name)
            graph.ensure_node(target, "state", value=state_name)
            graph.ensure_edge(object_id, "writes_state", target)
        effect_ref = payload.get("effect_ref")
        if effect_ref:
            target = node_id("effect", effect_ref)
            graph.ensure_node(target, "effect", value=effect_ref)
            graph.ensure_edge(object_id, "commits_effect", target)


__all__ = ["ContextProjector", "PayloadProjector", "ReferenceProjector", "node_id"]
