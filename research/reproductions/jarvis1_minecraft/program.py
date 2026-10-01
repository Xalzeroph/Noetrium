from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'jarvis1'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'lookup_plan'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'execute_skill': 'Execute the selected skill in the Minecraft environment.',
 'lookup_plan': 'Retrieve the current plan and memory context.',
 'prepare_controller': 'Prepare the controller command for the selected Minecraft skill.',
 'record_skill': 'Record skill outcome and decide whether to retry, advance, or finish.',
 'return': 'Return JARVIS-1 task result and trajectory.',
 'select_step': 'Select the next plan step or finish when the plan is complete.'}
ROUTE_OPTIONS = {'record_skill': ('prepare_controller', 'select_step', 'return'),
 'select_step': ('prepare_controller', 'return')}
ROUTE_DEFAULTS = {'record_skill': 'prepare_controller', 'select_step': 'prepare_controller'}
COMPONENT_NODE_MAP = {'lookup_plan': 'jarvis1.memory'}
COMPONENTS = (('jarvis1.memory', 'memory'),)
CAPABILITY_NODES = {'execute_skill': 'environment.act'}

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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('compute', 'lookup_plan', 'jarvis1.memory.load-plan', ('select_step',), 'Retrieve the current plan and memory context.'),
 ('route',
  'select_step',
  'jarvis1.plan.select-step',
  ('prepare_controller', 'return'),
  'Select the next plan step or finish when the plan is complete.'),
 ('compute',
  'prepare_controller',
  'jarvis1.controller.prepare',
  ('execute_skill',),
  'Prepare the controller command for the selected Minecraft skill.'),
 ('capability',
  'execute_skill',
  'jarvis1.controller.execute',
  ('record_skill',),
  'Execute the selected skill in the Minecraft environment.'),
 ('route',
  'record_skill',
  'jarvis1.controller.record',
  ('prepare_controller', 'select_step', 'return'),
  'Record skill outcome and decide whether to retry, advance, or finish.'),
 ('return', 'return', 'jarvis1.result', (), 'Return JARVIS-1 task result and trajectory.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.compute('lookup_plan', 'jarvis1.memory.load-plan', _compute, ('select_step',), max_visits=64, evidence=('jarvis1.lookup_plan',))
    method.route('select_step', 'jarvis1.plan.select-step', _route, ('prepare_controller', 'return'), max_visits=64)
    method.compute('prepare_controller', 'jarvis1.controller.prepare', _compute, ('execute_skill',), max_visits=64, evidence=('jarvis1.prepare_controller',))
    method.capability('execute_skill', 'jarvis1.controller.execute', 'environment.act', ('record_skill',), effect="reconcilable", max_visits=64, evidence=('jarvis1.execute_skill.effect',))
    method.route('record_skill', 'jarvis1.controller.record', _route, ('prepare_controller', 'select_step', 'return'), max_visits=64)
    method.return_node('return', 'jarvis1.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
