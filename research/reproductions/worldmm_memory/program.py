from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'worldmm'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'index_memory'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'answer': 'Produce the final answer from reasoning and retrieved memory.',
 'index_memory': 'Index multimodal world memory from the input stream.',
 'reason': 'Reason iteratively and decide whether to continue, retrieve memory, or answer.',
 'retrieve': 'Retrieve relevant multimodal memory for the current reasoning state.',
 'return': 'Return WorldMM answer and memory evidence.'}
ROUTE_OPTIONS = {'reason': ('reason', 'retrieve', 'answer')}
ROUTE_DEFAULTS = {'reason': 'retrieve'}
COMPONENT_NODE_MAP = {'index_memory': 'worldmm.memory', 'retrieve': 'worldmm.memory'}
COMPONENTS = (('worldmm.memory', 'memory'),)
CAPABILITY_NODES = {}

def _view(call):
    return {"instruction": NODE_INSTRUCTIONS[call.node_id], "input": call.input_value, "previous": call.previous_value, "state": call.state}

def _component_dispatch(call):
    payload = call.payload if isinstance(call.payload, Mapping) else {"payload": call.payload}
    return call.transition(value=freeze_json(payload), state_update={"last_payload": freeze_json(payload)}, next_node="dispatch")

def _compute(call):
    host_id = COMPONENT_NODE_MAP.get(call.node_id)
    if host_id is None:
        return call.transition(value=call.previous_value)
    child = call.component(host_id=host_id, component_instance_id=f"{call.run_id}:{host_id}", instance_identity={"method": METHOD_ID, "host": host_id}, initial_data={"method": METHOD_ID}, payload={"node_id": call.node_id, "input": call.input_value, "previous": call.previous_value, "state": dict(call.state)})
    return call.transition(value=child.result, state_update={call.node_id + "_component_status": child.status}, children=(child,))

def _route(call):
    allowed = ROUTE_OPTIONS[call.node_id]
    candidate = None
    if isinstance(call.previous_value, Mapping):
        for key in ("next_node", "route", "decision", "target"):
            value = call.previous_value.get(key)
            if isinstance(value, str) and value in allowed:
                candidate = value
                break
    if candidate is None:
        candidate = ROUTE_DEFAULTS[call.node_id]
    return call.transition(value=call.previous_value, next_node=candidate)

def _return(call):
    return call.transition(value={"method_id": METHOD_ID, "result": call.previous_value, "state": dict(call.state)})

def configure_method(method):
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('compute', 'index_memory', 'worldmm.memory.index', ('reason',), 'Index multimodal world memory from the input stream.'),
 ('route',
  'reason',
  'worldmm.reasoning.step',
  ('reason', 'retrieve', 'answer'),
  'Reason iteratively and decide whether to continue, retrieve memory, or answer.'),
 ('compute',
  'retrieve',
  'worldmm.memory.retrieve',
  ('reason', 'answer'),
  'Retrieve relevant multimodal memory for the current reasoning state.'),
 ('compute', 'answer', 'worldmm.answer', ('return',), 'Produce the final answer from reasoning and retrieved memory.'),
 ('return', 'return', 'worldmm.result', (), 'Return WorldMM answer and memory evidence.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.compute('index_memory', 'worldmm.memory.index', _compute, ('reason',), max_visits=64, evidence=('worldmm.index_memory',))
    method.route('reason', 'worldmm.reasoning.step', _route, ('reason', 'retrieve', 'answer'), max_visits=64)
    method.compute('retrieve', 'worldmm.memory.retrieve', _compute, ('reason', 'answer'), max_visits=64, evidence=('worldmm.retrieve',))
    method.compute('answer', 'worldmm.answer', _compute, ('return',), max_visits=64, evidence=('worldmm.answer',))
    method.return_node('return', 'worldmm.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
