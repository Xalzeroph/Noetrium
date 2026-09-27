from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'flow'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'initial_workflow'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'execute_ready_set': 'Execute the current dependency-ready subtask set concurrently.',
 'initial_workflow': 'Generate the initial modularized workflow candidate.',
 'record_initial_candidate': 'Record and validate the generated workflow candidate.',
 'record_refinement': 'Record the refined workflow and resume routing.',
 'record_summary': 'Record the final summary and workflow evidence.',
 'refine': 'Refine the workflow from measured subtask evidence.',
 'return': 'Return final workflow result.',
 'route': 'Route according to the workflow DAG ready set, refinement condition, or completion state.',
 'select_initial': 'Select the initial workflow for execution.',
 'summary': 'Synthesize the completed modular workflow result.'}
ROUTE_OPTIONS = {'record_initial_candidate': ('initial_workflow', 'select_initial'),
 'route': ('execute_ready_set', 'refine', 'summary')}
ROUTE_DEFAULTS = {'record_initial_candidate': 'initial_workflow', 'route': 'execute_ready_set'}
COMPONENT_NODE_MAP = {'execute_ready_set': 'flow.subtask-runtime'}
COMPONENTS = (('flow.subtask-runtime', 'runtime'),)
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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('agent',
  'initial_workflow',
  'flow.workflow.generate-candidate',
  ('record_initial_candidate',),
  'Generate the initial modularized workflow candidate.'),
 ('route',
  'record_initial_candidate',
  'flow.workflow.record-candidate',
  ('initial_workflow', 'select_initial'),
  'Record and validate the generated workflow candidate.'),
 ('compute', 'select_initial', 'flow.workflow.select-initial', ('route',), 'Select the initial workflow for execution.'),
 ('route',
  'route',
  'flow.workflow.route',
  ('execute_ready_set', 'refine', 'summary'),
  'Route according to the workflow DAG ready set, refinement condition, or completion state.'),
 ('compute',
  'execute_ready_set',
  'flow.ready-set.execute-batch',
  ('route',),
  'Execute the current dependency-ready subtask set concurrently.'),
 ('agent', 'refine', 'flow.workflow.refine', ('record_refinement',), 'Refine the workflow from measured subtask evidence.'),
 ('compute', 'record_refinement', 'flow.workflow.refinement-record', ('route',), 'Record the refined workflow and resume routing.'),
 ('agent', 'summary', 'flow.summary', ('record_summary',), 'Synthesize the completed modular workflow result.'),
 ('compute', 'record_summary', 'flow.summary.record', ('return',), 'Record the final summary and workflow evidence.'),
 ('return', 'return', 'flow.result', (), 'Return final workflow result.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.agent('initial_workflow', 'flow.workflow.generate-candidate', 'Generate the initial modularized workflow candidate.', ('record_initial_candidate',), view=_view, max_visits=64, evidence=('flow.initial_workflow',))
    method.route('record_initial_candidate', 'flow.workflow.record-candidate', _route, ('initial_workflow', 'select_initial'), max_visits=64)
    method.compute('select_initial', 'flow.workflow.select-initial', _compute, ('route',), max_visits=64, evidence=('flow.select_initial',))
    method.route('route', 'flow.workflow.route', _route, ('execute_ready_set', 'refine', 'summary'), max_visits=64)
    method.compute('execute_ready_set', 'flow.ready-set.execute-batch', _compute, ('route',), max_visits=64, evidence=('flow.execute_ready_set',))
    method.agent('refine', 'flow.workflow.refine', 'Refine the workflow from measured subtask evidence.', ('record_refinement',), view=_view, max_visits=64, evidence=('flow.refine',))
    method.compute('record_refinement', 'flow.workflow.refinement-record', _compute, ('route',), max_visits=64, evidence=('flow.record_refinement',))
    method.agent('summary', 'flow.summary', 'Synthesize the completed modular workflow result.', ('record_summary',), view=_view, max_visits=64, evidence=('flow.summary',))
    method.compute('record_summary', 'flow.summary.record', _compute, ('return',), max_visits=64, evidence=('flow.record_summary',))
    method.return_node('return', 'flow.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
