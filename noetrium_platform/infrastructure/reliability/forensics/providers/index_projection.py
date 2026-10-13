from __future__ import annotations

from dataclasses import dataclass
import json

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.event import event_field, event_ref_digest
from noetrium_platform.foundation.kernel.record_plane import event_document
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.failure.api import failure_document, failure_field
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import (
    mutation_document,
    mutation_record_value,
)
from noetrium_platform.infrastructure.reliability.forensics.providers.operation_projection import (
    OperationInvocationProjection,
    event_document_operation_projection,
    raw_event_operation_projection,
)


@dataclass(frozen=True, slots=True)
class ObjectProjection:
    values: tuple[object,...]


@dataclass(frozen=True, slots=True)
class StateWriterProjection:
    values: tuple[object,...]


@dataclass(frozen=True, slots=True)
class ProjectionBundle:
    object: ObjectProjection
    state_writer: StateWriterProjection|None = None
    operation_invocation: OperationInvocationProjection|None = None


def object_values(
    object_id:str,
    kind:str,
    component:str,
    timestamp:float,
    context,
    payload:dict[str,object],
    *,
    encoded_payload:str|None=None,
)->tuple[object,...]:
    if isinstance(context,dict):
        run_id=context.get("run_id")
        task_id=context.get("task_id")
        decision_cycle_id=context.get("decision_cycle_id")
        trace_id=context.get("trace_id")
        span_id=context.get("span_id")
        coordinate=context.get("graph_coordinate")
    else:
        run_id=getattr(context,"run_id",None)
        task_id=getattr(context,"task_id",None)
        decision_cycle_id=getattr(context,"decision_cycle_id",None)
        trace_id=getattr(context,"trace_id",None)
        span_id=getattr(context,"span_id",None)
        coordinate=getattr(context,"graph_coordinate",None)
    if isinstance(coordinate,dict):
        research_revision_digest=coordinate.get("research_revision_digest")
        execution_id=coordinate.get("execution_id")
        cut_id=coordinate.get("cut_id")
        graph_node_id=coordinate.get("graph_node_id")
        attempt_id=coordinate.get("attempt_id")
        generation=coordinate.get("generation")
    else:
        research_revision_digest=getattr(coordinate,"research_revision_digest",None)
        execution_id=getattr(coordinate,"execution_id",None)
        cut_id=getattr(coordinate,"cut_id",None)
        graph_node_id=getattr(coordinate,"graph_node_id",None)
        attempt_id=getattr(coordinate,"attempt_id",None)
        generation=getattr(coordinate,"generation",None)
    return (
        object_id, kind, run_id, task_id,
        decision_cycle_id, trace_id, span_id,
        component,
        research_revision_digest,
        execution_id,
        cut_id,
        graph_node_id,
        attempt_id,
        generation,
        timestamp,
        (
            encoded_payload
            if encoded_payload is not None
            else json.dumps(payload,ensure_ascii=False,sort_keys=True)
        ),
    )


def event_document_projection(doc:dict[str,object])->ProjectionBundle:
    context=doc["context"]
    encoded=json.dumps(doc,ensure_ascii=False,sort_keys=True)
    return ProjectionBundle(
        ObjectProjection(
            object_values(
                str(doc["event_id"]),
                "event",
                str(doc["component_id"]),
                float(doc["timestamp"]),
                context,
                doc,
                encoded_payload=encoded,
            )
        ),
        operation_invocation=event_document_operation_projection(
            doc,
            encoded_payload=encoded,
        ),
    )


def event_projection(event:NoetriumUnit)->ProjectionBundle:
    return event_document_projection(event_document(event))


def failure_projection(failure:NoetriumUnit)->ProjectionBundle:
    payload = failure_document(failure)
    payload["event_digest"] = failure.unit_digest
    return ProjectionBundle(ObjectProjection(
        object_values(str(failure_field(failure, "failure_id")),"failure",str(failure_field(failure, "component_id")),float(failure_field(failure, "created_at")),failure_field(failure, "context"),payload)
    ))


def mutation_projection(mutation:NoetriumUnit)->ProjectionBundle:
    value=mutation_record_value(mutation)
    payload=mutation_document(mutation)
    payload["event_digest"] = mutation.unit_digest
    payload["causal_event_refs"] = tuple(
        digest
        for reference in event_field(mutation, "causal_parents")
        if (digest := event_ref_digest(reference)) is not None
    )
    c=value.context
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    sw=(
        value.mutation_id,value.state_name,c.run_id,c.task_id,c.decision_cycle_id,
        c.trace_id,c.span_id,value.component_id,value.operation_id,
        value.new_version,value.new_digest,value.created_at,encoded,
    )
    return ProjectionBundle(
        ObjectProjection(object_values(
            value.mutation_id,
            "mutation",
            value.component_id,
            value.created_at,
            c,
            payload,
            encoded_payload=encoded,
        )),
        StateWriterProjection(sw),
    )


def raw_projection(kind:str,payload:dict[str,object])->ProjectionBundle:
    # Canonical NoetriumUnit documents keep domain event fields in payload;
    # rebuild accepts that sole immutable envelope directly.
    if kind == "event" and "record_type" in payload and isinstance(payload.get("payload"), dict):
        envelope = payload
        domain = dict(envelope["payload"])
        if "event_id" not in domain and envelope.get("record_id") is not None:
            domain["event_id"] = envelope["record_id"]
        if "timestamp" not in domain and envelope.get("observed_at") is not None:
            domain["timestamp"] = envelope["observed_at"]
        payload = domain
    id_field={"event":"event_id","failure":"failure_id","mutation":"mutation_id"}.get(kind)
    if id_field is None:
        raise ValueError(f"unknown forensic kind: {kind}")
    object_id=str(payload[id_field])
    context=payload.get("context") or {}
    if not isinstance(context,dict):
        raise ValueError("forensic payload context is not an object")
    run_id=context.get("run_id"); task_id=context.get("task_id")
    dc_id=context.get("decision_cycle_id"); trace_id=context.get("trace_id")
    span_id=context.get("span_id")
    component=str(payload.get("component_id") or context.get("component_id") or "unknown")
    timestamp=float(payload.get("created_at",payload.get("timestamp",0.0)))
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    coordinate=context.get("graph_coordinate")
    if coordinate is not None and not isinstance(coordinate,dict):
        raise ValueError("forensic payload graph_coordinate is not an object")
    coordinate = coordinate or {}
    obj=ObjectProjection((
        object_id,kind,run_id,task_id,dc_id,trace_id,span_id,component,
        coordinate.get("research_revision_digest"),
        coordinate.get("execution_id"),
        coordinate.get("cut_id"),
        coordinate.get("graph_node_id"),
        coordinate.get("attempt_id"),
        coordinate.get("generation"),
        timestamp,encoded,
    ))
    if kind == "event":
        return ProjectionBundle(obj, operation_invocation=raw_event_operation_projection(payload))
    if kind != "mutation":
        return ProjectionBundle(obj)
    sw=StateWriterProjection((
        object_id,str(payload["state_name"]),str(run_id),task_id,dc_id,trace_id,span_id,
        component,str(payload["operation_id"]),int(payload["new_version"]),
        str(payload["new_digest"]),timestamp,encoded,
    ))
    return ProjectionBundle(obj,sw)
