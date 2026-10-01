from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'videoagent'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'main_agent'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'caption_memory': 'Retrieve caption memory.',
 'main_agent': 'Reason over the video task and select the next VideoAgent tool.',
 'object_agent': 'Reason inside the object-memory subloop.',
 'object_database': 'Query object database memory.',
 'object_retrieve': 'Run open-vocabulary object retrieval.',
 'record_main_tool': 'Record main tool result and continue reasoning or finish.',
 'record_object_as_main_tool': 'Return object-memory result to main ReAct loop.',
 'record_object_tool': 'Record object tool result and continue or return to main loop.',
 'return': 'Return VideoAgent answer and evidence trajectory.',
 'route_main': 'Route the main ReAct decision to caption, segment, VQA, object memory, or final answer.',
 'route_object': 'Route object-memory query, retrieval, or return.',
 'segment_memory': 'Localize relevant video segments.',
 'start_object_memory': 'Initialize object-memory reasoning.',
 'vqa': 'Answer a focused visual question over selected evidence.'}
ROUTE_OPTIONS = {'record_main_tool': ('main_agent', 'return'),
 'record_object_tool': ('object_agent', 'record_object_as_main_tool'),
 'route_main': ('caption_memory', 'segment_memory', 'vqa', 'start_object_memory', 'return'),
 'route_object': ('object_database', 'object_retrieve', 'record_object_as_main_tool')}
ROUTE_DEFAULTS = {'record_main_tool': 'main_agent',
 'record_object_tool': 'object_agent',
 'route_main': 'caption_memory',
 'route_object': 'object_database'}
COMPONENT_NODE_MAP = {'caption_memory': 'videoagent.memory',
 'object_database': 'videoagent.memory',
 'object_retrieve': 'videoagent.memory',
 'segment_memory': 'videoagent.memory'}
COMPONENTS = (('videoagent.memory', 'memory'),)
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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('agent', 'main_agent', 'videoagent.react.main', ('route_main',), 'Reason over the video task and select the next VideoAgent tool.'),
 ('route',
  'route_main',
  'videoagent.react.route-main',
  ('caption_memory', 'segment_memory', 'vqa', 'start_object_memory', 'return'),
  'Route the main ReAct decision to caption, segment, VQA, object memory, or final answer.'),
 ('compute', 'caption_memory', 'videoagent.memory.caption-retrieval', ('record_main_tool',), 'Retrieve caption memory.'),
 ('compute', 'segment_memory', 'videoagent.memory.segment-localization', ('record_main_tool',), 'Localize relevant video segments.'),
 ('agent',
  'vqa',
  'videoagent.tool.visual-question-answering',
  ('record_main_tool',),
  'Answer a focused visual question over selected evidence.'),
 ('compute', 'start_object_memory', 'videoagent.object-memory.start', ('object_agent',), 'Initialize object-memory reasoning.'),
 ('agent', 'object_agent', 'videoagent.object-memory.react', ('route_object',), 'Reason inside the object-memory subloop.'),
 ('route',
  'route_object',
  'videoagent.object-memory.route',
  ('object_database', 'object_retrieve', 'record_object_as_main_tool'),
  'Route object-memory query, retrieval, or return.'),
 ('compute', 'object_database', 'videoagent.object-memory.database-query', ('record_object_tool',), 'Query object database memory.'),
 ('compute',
  'object_retrieve',
  'videoagent.object-memory.open-vocabulary-retrieval',
  ('record_object_tool',),
  'Run open-vocabulary object retrieval.'),
 ('route',
  'record_object_tool',
  'videoagent.object-memory.record-tool',
  ('object_agent', 'record_object_as_main_tool'),
  'Record object tool result and continue or return to main loop.'),
 ('compute',
  'record_object_as_main_tool',
  'videoagent.object-memory.return-to-main',
  ('record_main_tool',),
  'Return object-memory result to main ReAct loop.'),
 ('route',
  'record_main_tool',
  'videoagent.react.record-tool',
  ('main_agent', 'return'),
  'Record main tool result and continue reasoning or finish.'),
 ('return', 'return', 'videoagent.result', (), 'Return VideoAgent answer and evidence trajectory.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.agent('main_agent', 'videoagent.react.main', 'Reason over the video task and select the next VideoAgent tool.', ('route_main',), view=_view, max_visits=64, evidence=('videoagent.main_agent',))
    method.route('route_main', 'videoagent.react.route-main', _route, ('caption_memory', 'segment_memory', 'vqa', 'start_object_memory', 'return'), max_visits=64)
    method.compute('caption_memory', 'videoagent.memory.caption-retrieval', _compute, ('record_main_tool',), max_visits=64, evidence=('videoagent.caption_memory',))
    method.compute('segment_memory', 'videoagent.memory.segment-localization', _compute, ('record_main_tool',), max_visits=64, evidence=('videoagent.segment_memory',))
    method.agent('vqa', 'videoagent.tool.visual-question-answering', 'Answer a focused visual question over selected evidence.', ('record_main_tool',), view=_view, max_visits=64, evidence=('videoagent.vqa',))
    method.compute('start_object_memory', 'videoagent.object-memory.start', _compute, ('object_agent',), max_visits=64, evidence=('videoagent.start_object_memory',))
    method.agent('object_agent', 'videoagent.object-memory.react', 'Reason inside the object-memory subloop.', ('route_object',), view=_view, max_visits=64, evidence=('videoagent.object_agent',))
    method.route('route_object', 'videoagent.object-memory.route', _route, ('object_database', 'object_retrieve', 'record_object_as_main_tool'), max_visits=64)
    method.compute('object_database', 'videoagent.object-memory.database-query', _compute, ('record_object_tool',), max_visits=64, evidence=('videoagent.object_database',))
    method.compute('object_retrieve', 'videoagent.object-memory.open-vocabulary-retrieval', _compute, ('record_object_tool',), max_visits=64, evidence=('videoagent.object_retrieve',))
    method.route('record_object_tool', 'videoagent.object-memory.record-tool', _route, ('object_agent', 'record_object_as_main_tool'), max_visits=64)
    method.compute('record_object_as_main_tool', 'videoagent.object-memory.return-to-main', _compute, ('record_main_tool',), max_visits=64, evidence=('videoagent.record_object_as_main_tool',))
    method.route('record_main_tool', 'videoagent.react.record-tool', _route, ('main_agent', 'return'), max_visits=64)
    method.return_node('return', 'videoagent.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
