from __future__ import annotations

from dataclasses import dataclass
import json

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import MutationRecord
from noetrium_platform.infrastructure.reliability.forensics.providers.operation_projection import OperationInvocationProjection, event_operation_projection, raw_event_operation_projection


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
)->tuple[object,...]:
    return (
        object_id,kind,context.run_id,context.task_id,context.decision_cycle_id,
        context.trace_id,context.span_id,component,timestamp,
        json.dumps(payload,ensure_ascii=False,sort_keys=True),
    )


def event_projection(event:EventEnvelope)->ProjectionBundle:
    return ProjectionBundle(
        ObjectProjection(
            object_values(event.event_id,"event",event.component_id,event.timestamp,event.context,event.to_dict())
        ),
        operation_invocation=event_operation_projection(event),
    )


def failure_projection(failure:FailureEnvelope)->ProjectionBundle:
    return ProjectionBundle(ObjectProjection(
        object_values(failure.failure_id,"failure",failure.component_id,failure.created_at,failure.context,failure.to_dict())
    ))


def mutation_projection(mutation:MutationRecord)->ProjectionBundle:
    payload=mutation.to_dict(); c=mutation.context
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    sw=(
        mutation.mutation_id,mutation.state_name,c.run_id,c.task_id,c.decision_cycle_id,
        c.trace_id,c.span_id,mutation.component_id,mutation.operation_id,
        mutation.new_version,mutation.new_digest,mutation.created_at,encoded,
    )
    return ProjectionBundle(
        ObjectProjection(object_values(
            mutation.mutation_id,"mutation",mutation.component_id,mutation.created_at,c,payload
        )),
        StateWriterProjection(sw),
    )


def raw_projection(kind:str,payload:dict[str,object])->ProjectionBundle:
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
    obj=ObjectProjection((object_id,kind,run_id,task_id,dc_id,trace_id,span_id,component,timestamp,encoded))
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
