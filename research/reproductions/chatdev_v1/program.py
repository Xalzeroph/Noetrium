from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'chatdev-v1'
METHOD_VERSION = 'chatdev-v1'
METHOD_ENTRYPOINT = 'demand_analysis'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'code_complete': 'Continue code completion until the phase termination condition is met.',
 'code_review_comment': 'Review the generated code and produce modification comments.',
 'code_review_modification': 'Apply review modifications and decide whether another review round is '
                             'required.',
 'coding': 'Generate the initial software implementation.',
 'demand_analysis': 'Analyze software demand using the ChatDev role protocol.',
 'environment_doc': 'Materialize environment documentation from the finished software workspace.',
 'language_choose': 'Choose implementation language under the ChatDev phase protocol.',
 'manual': 'Write the user manual from the completed project.',
 'return': 'Return the ChatDev software artifact and phase transcript.',
 'test_error_summary': 'Summarize test errors and decide whether repair is needed.',
 'test_modification': 'Repair test failures and either retest or continue.'}
ROUTE_OPTIONS = {'code_complete': ('code_complete', 'code_review_comment'),
 'code_review_modification': ('code_review_comment', 'test_error_summary'),
 'test_error_summary': ('test_modification', 'environment_doc'),
 'test_modification': ('test_error_summary', 'environment_doc')}
ROUTE_DEFAULTS = {'code_complete': 'code_review_comment',
 'code_review_modification': 'code_review_comment',
 'test_error_summary': 'test_modification',
 'test_modification': 'test_error_summary'}
COMPONENT_NODE_MAP = {'code_review_comment': 'chatdev.runtime',
 'coding': 'chatdev.runtime',
 'demand_analysis': 'chatdev.runtime',
 'environment_doc': 'chatdev.environment',
 'language_choose': 'chatdev.runtime',
 'manual': 'chatdev.runtime'}
COMPONENTS = (('chatdev.runtime', 'runtime'), ('chatdev.environment', 'environment'))
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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('compute',
  'demand_analysis',
  'chatdev.v1.phase.demand-analysis',
  ('language_choose',),
  'Analyze software demand using the ChatDev role protocol.'),
 ('compute',
  'language_choose',
  'chatdev.v1.phase.language-choose',
  ('coding',),
  'Choose implementation language under the ChatDev phase protocol.'),
 ('compute', 'coding', 'chatdev.v1.phase.coding', ('code_complete',), 'Generate the initial software implementation.'),
 ('route',
  'code_complete',
  'chatdev.v1.composed.code-complete',
  ('code_complete', 'code_review_comment'),
  'Continue code completion until the phase termination condition is met.'),
 ('compute',
  'code_review_comment',
  'chatdev.v1.phase.code-review-comment',
  ('code_review_modification',),
  'Review the generated code and produce modification comments.'),
 ('route',
  'code_review_modification',
  'chatdev.v1.composed.code-review-modification',
  ('code_review_comment', 'test_error_summary'),
  'Apply review modifications and decide whether another review round is required.'),
 ('route',
  'test_error_summary',
  'chatdev.v1.composed.test-error-summary',
  ('test_modification', 'environment_doc'),
  'Summarize test errors and decide whether repair is needed.'),
 ('route',
  'test_modification',
  'chatdev.v1.composed.test-modification',
  ('test_error_summary', 'environment_doc'),
  'Repair test failures and either retest or continue.'),
 ('compute',
  'environment_doc',
  'chatdev.v1.phase.environment-doc',
  ('manual',),
  'Materialize environment documentation from the finished software workspace.'),
 ('compute', 'manual', 'chatdev.v1.phase.manual', ('return',), 'Write the user manual from the completed project.'),
 ('return', 'return', 'chatdev.v1.result', (), 'Return the ChatDev software artifact and phase transcript.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.compute('demand_analysis', 'chatdev.v1.phase.demand-analysis', _compute, ('language_choose',), max_visits=64, evidence=('chatdev-v1.demand_analysis',))
    method.compute('language_choose', 'chatdev.v1.phase.language-choose', _compute, ('coding',), max_visits=64, evidence=('chatdev-v1.language_choose',))
    method.compute('coding', 'chatdev.v1.phase.coding', _compute, ('code_complete',), max_visits=64, evidence=('chatdev-v1.coding',))
    method.route('code_complete', 'chatdev.v1.composed.code-complete', _route, ('code_complete', 'code_review_comment'), max_visits=64)
    method.compute('code_review_comment', 'chatdev.v1.phase.code-review-comment', _compute, ('code_review_modification',), max_visits=64, evidence=('chatdev-v1.code_review_comment',))
    method.route('code_review_modification', 'chatdev.v1.composed.code-review-modification', _route, ('code_review_comment', 'test_error_summary'), max_visits=64)
    method.route('test_error_summary', 'chatdev.v1.composed.test-error-summary', _route, ('test_modification', 'environment_doc'), max_visits=64)
    method.route('test_modification', 'chatdev.v1.composed.test-modification', _route, ('test_error_summary', 'environment_doc'), max_visits=64)
    method.compute('environment_doc', 'chatdev.v1.phase.environment-doc', _compute, ('manual',), max_visits=64, evidence=('chatdev-v1.environment_doc',))
    method.compute('manual', 'chatdev.v1.phase.manual', _compute, ('return',), max_visits=64, evidence=('chatdev-v1.manual',))
    method.return_node('return', 'chatdev.v1.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
