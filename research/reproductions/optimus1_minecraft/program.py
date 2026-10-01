from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'optimus1'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'retrieval'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'execute_controller': 'Execute STEVE-1 action in Minecraft.',
 'execute_helper': 'Execute helper action in Minecraft.',
 'load_memory': 'Load hybrid episodic and plan memory.',
 'persist_plan': 'Persist completed plan and experience.',
 'planner': 'Generate a knowledge-guided plan.',
 'prepare_controller': 'Prepare STEVE-1 controller action.',
 'prepare_helper': 'Prepare helper execution.',
 'prepare_reflection': 'Prepare failure context for reflection.',
 'prepare_replan_context': 'Prepare context for failure-aware replanning.',
 'record_controller': 'Record controller outcome and route reflection/retry/advance.',
 'record_helper': 'Record helper outcome and route retry/replan/advance.',
 'record_plan': 'Record the generated plan.',
 'record_reflection': 'Persist reflection into method memory.',
 'record_replan': 'Record revised plan.',
 'record_retrieval': 'Record retrieval evidence.',
 'reflector': 'Reflect on failed experience and produce corrective guidance.',
 'replan': 'Generate a revised plan after failure.',
 'retrieval': 'Retrieve goal-relevant visual knowledge.',
 'return': 'Return Optimus-1 task result.',
 'route_plan_source': 'Choose whether a fresh plan is required.',
 'select_subgoal': 'Choose helper, controller, or completion path for the next subgoal.'}
ROUTE_OPTIONS = {'record_controller': ('prepare_controller', 'select_subgoal', 'prepare_reflection', 'persist_plan'),
 'record_helper': ('prepare_helper', 'select_subgoal', 'prepare_replan_context', 'persist_plan'),
 'route_plan_source': ('planner', 'select_subgoal'),
 'select_subgoal': ('prepare_helper', 'prepare_controller', 'persist_plan')}
ROUTE_DEFAULTS = {'record_controller': 'prepare_controller',
 'record_helper': 'prepare_helper',
 'route_plan_source': 'planner',
 'select_subgoal': 'prepare_helper'}
COMPONENT_NODE_MAP = {'load_memory': 'optimus1.memory', 'persist_plan': 'optimus1.memory', 'prepare_reflection': 'optimus1.memory'}
COMPONENTS = (('optimus1.memory', 'memory'),)
CAPABILITY_NODES = {'execute_controller': 'environment.act', 'execute_helper': 'environment.act'}

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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('agent', 'retrieval', 'optimus1.goal-visual-retrieval', ('record_retrieval',), 'Retrieve goal-relevant visual knowledge.'),
 ('compute', 'record_retrieval', 'optimus1.retrieval.record', ('load_memory',), 'Record retrieval evidence.'),
 ('compute', 'load_memory', 'optimus1.memory.load', ('route_plan_source',), 'Load hybrid episodic and plan memory.'),
 ('route', 'route_plan_source', 'optimus1.plan.source', ('planner', 'select_subgoal'), 'Choose whether a fresh plan is required.'),
 ('agent', 'planner', 'optimus1.planner.knowledge-guided', ('record_plan',), 'Generate a knowledge-guided plan.'),
 ('compute', 'record_plan', 'optimus1.plan.record', ('select_subgoal',), 'Record the generated plan.'),
 ('route',
  'select_subgoal',
  'optimus1.plan.select-subgoal',
  ('prepare_helper', 'prepare_controller', 'persist_plan'),
  'Choose helper, controller, or completion path for the next subgoal.'),
 ('compute', 'prepare_helper', 'optimus1.helper.prepare', ('execute_helper',), 'Prepare helper execution.'),
 ('capability', 'execute_helper', 'optimus1.minecraft.helper-execute', ('record_helper',), 'Execute helper action in Minecraft.'),
 ('route',
  'record_helper',
  'optimus1.helper.record',
  ('prepare_helper', 'select_subgoal', 'prepare_replan_context', 'persist_plan'),
  'Record helper outcome and route retry/replan/advance.'),
 ('compute', 'prepare_controller', 'optimus1.steve1.prepare', ('execute_controller',), 'Prepare STEVE-1 controller action.'),
 ('capability', 'execute_controller', 'optimus1.minecraft.steve1-execute', ('record_controller',), 'Execute STEVE-1 action in Minecraft.'),
 ('route',
  'record_controller',
  'optimus1.steve1.record',
  ('prepare_controller', 'select_subgoal', 'prepare_reflection', 'persist_plan'),
  'Record controller outcome and route reflection/retry/advance.'),
 ('compute', 'prepare_reflection', 'optimus1.memory.prepare-reflection', ('reflector',), 'Prepare failure context for reflection.'),
 ('agent',
  'reflector',
  'optimus1.reflector.experience-driven',
  ('record_reflection',),
  'Reflect on failed experience and produce corrective guidance.'),
 ('compute', 'record_reflection', 'optimus1.reflection.record', ('prepare_controller',), 'Persist reflection into method memory.'),
 ('compute', 'prepare_replan_context', 'optimus1.replan.prepare', ('replan',), 'Prepare context for failure-aware replanning.'),
 ('agent', 'replan', 'optimus1.planner.failure-replan', ('record_replan',), 'Generate a revised plan after failure.'),
 ('compute', 'record_replan', 'optimus1.replan.record', ('select_subgoal',), 'Record revised plan.'),
 ('compute', 'persist_plan', 'optimus1.memory.persist-plan', ('return',), 'Persist completed plan and experience.'),
 ('return', 'return', 'optimus1.result', (), 'Return Optimus-1 task result.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.agent('retrieval', 'optimus1.goal-visual-retrieval', 'Retrieve goal-relevant visual knowledge.', ('record_retrieval',), view=_view, max_visits=64, evidence=('optimus1.retrieval',))
    method.compute('record_retrieval', 'optimus1.retrieval.record', _compute, ('load_memory',), max_visits=64, evidence=('optimus1.record_retrieval',))
    method.compute('load_memory', 'optimus1.memory.load', _compute, ('route_plan_source',), max_visits=64, evidence=('optimus1.load_memory',))
    method.route('route_plan_source', 'optimus1.plan.source', _route, ('planner', 'select_subgoal'), max_visits=64)
    method.agent('planner', 'optimus1.planner.knowledge-guided', 'Generate a knowledge-guided plan.', ('record_plan',), view=_view, max_visits=64, evidence=('optimus1.planner',))
    method.compute('record_plan', 'optimus1.plan.record', _compute, ('select_subgoal',), max_visits=64, evidence=('optimus1.record_plan',))
    method.route('select_subgoal', 'optimus1.plan.select-subgoal', _route, ('prepare_helper', 'prepare_controller', 'persist_plan'), max_visits=64)
    method.compute('prepare_helper', 'optimus1.helper.prepare', _compute, ('execute_helper',), max_visits=64, evidence=('optimus1.prepare_helper',))
    method.capability('execute_helper', 'optimus1.minecraft.helper-execute', 'environment.act', ('record_helper',), effect="reconcilable", max_visits=64, evidence=('optimus1.execute_helper.effect',))
    method.route('record_helper', 'optimus1.helper.record', _route, ('prepare_helper', 'select_subgoal', 'prepare_replan_context', 'persist_plan'), max_visits=64)
    method.compute('prepare_controller', 'optimus1.steve1.prepare', _compute, ('execute_controller',), max_visits=64, evidence=('optimus1.prepare_controller',))
    method.capability('execute_controller', 'optimus1.minecraft.steve1-execute', 'environment.act', ('record_controller',), effect="reconcilable", max_visits=64, evidence=('optimus1.execute_controller.effect',))
    method.route('record_controller', 'optimus1.steve1.record', _route, ('prepare_controller', 'select_subgoal', 'prepare_reflection', 'persist_plan'), max_visits=64)
    method.compute('prepare_reflection', 'optimus1.memory.prepare-reflection', _compute, ('reflector',), max_visits=64, evidence=('optimus1.prepare_reflection',))
    method.agent('reflector', 'optimus1.reflector.experience-driven', 'Reflect on failed experience and produce corrective guidance.', ('record_reflection',), view=_view, max_visits=64, evidence=('optimus1.reflector',))
    method.compute('record_reflection', 'optimus1.reflection.record', _compute, ('prepare_controller',), max_visits=64, evidence=('optimus1.record_reflection',))
    method.compute('prepare_replan_context', 'optimus1.replan.prepare', _compute, ('replan',), max_visits=64, evidence=('optimus1.prepare_replan_context',))
    method.agent('replan', 'optimus1.planner.failure-replan', 'Generate a revised plan after failure.', ('record_replan',), view=_view, max_visits=64, evidence=('optimus1.replan',))
    method.compute('record_replan', 'optimus1.replan.record', _compute, ('select_subgoal',), max_visits=64, evidence=('optimus1.record_replan',))
    method.compute('persist_plan', 'optimus1.memory.persist-plan', _compute, ('return',), max_visits=64, evidence=('optimus1.persist_plan',))
    method.return_node('return', 'optimus1.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
