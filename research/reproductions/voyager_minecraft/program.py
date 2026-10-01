from __future__ import annotations

from collections.abc import Mapping
from research.reproductions._support import JsonObject, JsonValue, freeze_json

METHOD_ID = 'voyager'
METHOD_VERSION = 'paper-protocol'
METHOD_ENTRYPOINT = 'start_task'
METHOD_SPEC = {"method_id": METHOD_ID, "version": METHOD_VERSION, "semantic_contract": METHOD_ID + ".method.v3", "entrypoint": METHOD_ENTRYPOINT}
NODE_INSTRUCTIONS = {'action': 'Generate executable Minecraft program from current skills and observations.',
 'critic': 'Critique whether the task was completed.',
 'curriculum': 'Propose next automatic curriculum task.',
 'curriculum_qa_answer': 'Answer curriculum enrichment question.',
 'curriculum_qa_lookup': 'Use QA memory cache or request a new enrichment answer.',
 'curriculum_qa_questions': 'Generate curriculum enrichment questions.',
 'curriculum_random': 'Sample the paper curriculum mask.',
 'execute_program': 'Execute generated program in Minecraft.',
 'prepare_curriculum': 'Prepare automatic curriculum context.',
 'prepare_curriculum_random': 'Prepare random curriculum mask.',
 'prepare_execute': 'Prepare generated program for environment execution.',
 'progress': 'Update curriculum progress and start the next task.',
 'qa_answer': 'Generate task context answer.',
 'record_action': 'Validate generated action or proceed to execution/progress.',
 'record_critic': 'Route failure retry, skill write, or curriculum progress.',
 'record_curriculum': 'Record curriculum proposal.',
 'record_curriculum_qa_answer': 'Write QA enrichment memory.',
 'record_curriculum_qa_questions': 'Record curriculum questions.',
 'record_curriculum_random': 'Record sampled curriculum mask.',
 'record_execution': 'Record environment execution result.',
 'record_qa_answer': 'Record task context answer.',
 'retrieve_skills': 'Retrieve relevant executable skills.',
 'return': 'Return Voyager curriculum and skill-learning result.',
 'start_task': 'Route to curriculum generation, skill execution, or termination.',
 'task_context_lookup': 'Load task context from memory or generate QA context.',
 'write_skill': 'Persist successful skill in the skill library.'}
ROUTE_OPTIONS = {'curriculum_qa_lookup': ('curriculum_qa_lookup', 'curriculum_qa_answer', 'prepare_curriculum_random'),
 'prepare_curriculum': ('curriculum_qa_questions', 'prepare_curriculum_random'),
 'record_action': ('action', 'prepare_execute', 'progress'),
 'record_critic': ('retrieve_skills', 'write_skill', 'progress'),
 'start_task': ('prepare_curriculum', 'retrieve_skills', 'return'),
 'task_context_lookup': ('qa_answer', 'retrieve_skills')}
ROUTE_DEFAULTS = {'curriculum_qa_lookup': 'curriculum_qa_answer',
 'prepare_curriculum': 'curriculum_qa_questions',
 'record_action': 'action',
 'record_critic': 'retrieve_skills',
 'start_task': 'prepare_curriculum',
 'task_context_lookup': 'qa_answer'}
COMPONENT_NODE_MAP = {'curriculum_qa_lookup': 'voyager.qa-memory',
 'retrieve_skills': 'voyager.skill-memory',
 'task_context_lookup': 'voyager.chest-memory',
 'write_skill': 'voyager.skill-memory'}
COMPONENTS = (('voyager.skill-memory', 'memory'), ('voyager.chest-memory', 'memory'), ('voyager.qa-memory', 'memory'))
CAPABILITY_NODES = {'curriculum_random': 'random.sample', 'execute_program': 'environment.act'}

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
    method.configure({"paper_method": METHOD_ID, "paper_graph": tuple((kind,node,op,nexts) for kind,node,op,nexts,_ in [('route',
  'start_task',
  'voyager.curriculum.route',
  ('prepare_curriculum', 'retrieve_skills', 'return'),
  'Route to curriculum generation, skill execution, or termination.'),
 ('route',
  'prepare_curriculum',
  'voyager.curriculum.prepare',
  ('curriculum_qa_questions', 'prepare_curriculum_random'),
  'Prepare automatic curriculum context.'),
 ('agent',
  'curriculum_qa_questions',
  'voyager.curriculum.qa-questions',
  ('record_curriculum_qa_questions',),
  'Generate curriculum enrichment questions.'),
 ('compute',
  'record_curriculum_qa_questions',
  'voyager.curriculum.qa-questions-record',
  ('curriculum_qa_lookup',),
  'Record curriculum questions.'),
 ('route',
  'curriculum_qa_lookup',
  'voyager.curriculum.qa-enrichment-cache',
  ('curriculum_qa_lookup', 'curriculum_qa_answer', 'prepare_curriculum_random'),
  'Use QA memory cache or request a new enrichment answer.'),
 ('agent',
  'curriculum_qa_answer',
  'voyager.curriculum.qa-enrichment-answer',
  ('record_curriculum_qa_answer',),
  'Answer curriculum enrichment question.'),
 ('compute',
  'record_curriculum_qa_answer',
  'voyager.curriculum.qa-enrichment-record',
  ('curriculum_qa_lookup',),
  'Write QA enrichment memory.'),
 ('compute',
  'prepare_curriculum_random',
  'voyager.curriculum.random-mask-prepare',
  ('curriculum_random',),
  'Prepare random curriculum mask.'),
 ('capability', 'curriculum_random', 'voyager.curriculum.random-mask', ('record_curriculum_random',), 'Sample the paper curriculum mask.'),
 ('compute', 'record_curriculum_random', 'voyager.curriculum.random-mask-record', ('curriculum',), 'Record sampled curriculum mask.'),
 ('agent', 'curriculum', 'voyager.curriculum.propose', ('record_curriculum',), 'Propose next automatic curriculum task.'),
 ('compute', 'record_curriculum', 'voyager.curriculum.record', ('task_context_lookup',), 'Record curriculum proposal.'),
 ('route',
  'task_context_lookup',
  'voyager.curriculum.task-context-cache',
  ('qa_answer', 'retrieve_skills'),
  'Load task context from memory or generate QA context.'),
 ('agent', 'qa_answer', 'voyager.curriculum.qa-answer', ('record_qa_answer',), 'Generate task context answer.'),
 ('compute', 'record_qa_answer', 'voyager.curriculum.qa-record', ('retrieve_skills',), 'Record task context answer.'),
 ('compute', 'retrieve_skills', 'voyager.skill-memory.retrieve', ('action',), 'Retrieve relevant executable skills.'),
 ('agent',
  'action',
  'voyager.action.generate',
  ('record_action',),
  'Generate executable Minecraft program from current skills and observations.'),
 ('route',
  'record_action',
  'voyager.action.record',
  ('action', 'prepare_execute', 'progress'),
  'Validate generated action or proceed to execution/progress.'),
 ('compute',
  'prepare_execute',
  'voyager.minecraft.prepare-program',
  ('execute_program',),
  'Prepare generated program for environment execution.'),
 ('capability', 'execute_program', 'voyager.minecraft.execute-program', ('record_execution',), 'Execute generated program in Minecraft.'),
 ('compute', 'record_execution', 'voyager.minecraft.record-program', ('critic',), 'Record environment execution result.'),
 ('agent', 'critic', 'voyager.critic.verify', ('record_critic',), 'Critique whether the task was completed.'),
 ('route',
  'record_critic',
  'voyager.critic.record',
  ('retrieve_skills', 'write_skill', 'progress'),
  'Route failure retry, skill write, or curriculum progress.'),
 ('compute', 'write_skill', 'voyager.skill-memory.write', ('progress',), 'Persist successful skill in the skill library.'),
 ('compute', 'progress', 'voyager.curriculum.progress', ('start_task',), 'Update curriculum progress and start the next task.'),
 ('return', 'return', 'voyager.result', (), 'Return Voyager curriculum and skill-learning result.')]), "architecture": "method-owned-components-on-shared-machine-kernel"})
    for host_id, domain in COMPONENTS:
        component = getattr(method, domain)(host_id, entrypoint="dispatch", version=METHOD_VERSION, state_schema=METHOD_ID + "." + host_id + ".state.v1")
        component.custom("dispatch", host_id + ".dispatch", _component_dispatch, next_node="dispatch").end()
    method.route('start_task', 'voyager.curriculum.route', _route, ('prepare_curriculum', 'retrieve_skills', 'return'), max_visits=64)
    method.route('prepare_curriculum', 'voyager.curriculum.prepare', _route, ('curriculum_qa_questions', 'prepare_curriculum_random'), max_visits=64)
    method.agent('curriculum_qa_questions', 'voyager.curriculum.qa-questions', 'Generate curriculum enrichment questions.', ('record_curriculum_qa_questions',), view=_view, max_visits=64, evidence=('voyager.curriculum_qa_questions',))
    method.compute('record_curriculum_qa_questions', 'voyager.curriculum.qa-questions-record', _compute, ('curriculum_qa_lookup',), max_visits=64, evidence=('voyager.record_curriculum_qa_questions',))
    method.route('curriculum_qa_lookup', 'voyager.curriculum.qa-enrichment-cache', _route, ('curriculum_qa_lookup', 'curriculum_qa_answer', 'prepare_curriculum_random'), max_visits=64)
    method.agent('curriculum_qa_answer', 'voyager.curriculum.qa-enrichment-answer', 'Answer curriculum enrichment question.', ('record_curriculum_qa_answer',), view=_view, max_visits=64, evidence=('voyager.curriculum_qa_answer',))
    method.compute('record_curriculum_qa_answer', 'voyager.curriculum.qa-enrichment-record', _compute, ('curriculum_qa_lookup',), max_visits=64, evidence=('voyager.record_curriculum_qa_answer',))
    method.compute('prepare_curriculum_random', 'voyager.curriculum.random-mask-prepare', _compute, ('curriculum_random',), max_visits=64, evidence=('voyager.prepare_curriculum_random',))
    method.capability('curriculum_random', 'voyager.curriculum.random-mask', 'random.sample', ('record_curriculum_random',), effect="reconcilable", max_visits=64, evidence=('voyager.curriculum_random.effect',))
    method.compute('record_curriculum_random', 'voyager.curriculum.random-mask-record', _compute, ('curriculum',), max_visits=64, evidence=('voyager.record_curriculum_random',))
    method.agent('curriculum', 'voyager.curriculum.propose', 'Propose next automatic curriculum task.', ('record_curriculum',), view=_view, max_visits=64, evidence=('voyager.curriculum',))
    method.compute('record_curriculum', 'voyager.curriculum.record', _compute, ('task_context_lookup',), max_visits=64, evidence=('voyager.record_curriculum',))
    method.route('task_context_lookup', 'voyager.curriculum.task-context-cache', _route, ('qa_answer', 'retrieve_skills'), max_visits=64)
    method.agent('qa_answer', 'voyager.curriculum.qa-answer', 'Generate task context answer.', ('record_qa_answer',), view=_view, max_visits=64, evidence=('voyager.qa_answer',))
    method.compute('record_qa_answer', 'voyager.curriculum.qa-record', _compute, ('retrieve_skills',), max_visits=64, evidence=('voyager.record_qa_answer',))
    method.compute('retrieve_skills', 'voyager.skill-memory.retrieve', _compute, ('action',), max_visits=64, evidence=('voyager.retrieve_skills',))
    method.agent('action', 'voyager.action.generate', 'Generate executable Minecraft program from current skills and observations.', ('record_action',), view=_view, max_visits=64, evidence=('voyager.action',))
    method.route('record_action', 'voyager.action.record', _route, ('action', 'prepare_execute', 'progress'), max_visits=64)
    method.compute('prepare_execute', 'voyager.minecraft.prepare-program', _compute, ('execute_program',), max_visits=64, evidence=('voyager.prepare_execute',))
    method.capability('execute_program', 'voyager.minecraft.execute-program', 'environment.act', ('record_execution',), effect="reconcilable", max_visits=64, evidence=('voyager.execute_program.effect',))
    method.compute('record_execution', 'voyager.minecraft.record-program', _compute, ('critic',), max_visits=64, evidence=('voyager.record_execution',))
    method.agent('critic', 'voyager.critic.verify', 'Critique whether the task was completed.', ('record_critic',), view=_view, max_visits=64, evidence=('voyager.critic',))
    method.route('record_critic', 'voyager.critic.record', _route, ('retrieve_skills', 'write_skill', 'progress'), max_visits=64)
    method.compute('write_skill', 'voyager.skill-memory.write', _compute, ('progress',), max_visits=64, evidence=('voyager.write_skill',))
    method.compute('progress', 'voyager.curriculum.progress', _compute, ('start_task',), max_visits=64, evidence=('voyager.progress',))
    method.return_node('return', 'voyager.result', _return)
    method.requires(*tuple(sorted(set(CAPABILITY_NODES.values()))))
    method.policy(execution="effect_recorded", evidence=(METHOD_ID + ".trajectory",), metrics=("task_success", "method_steps"), artifacts=(METHOD_ID + "_trajectory",))
    return method

METHOD_CONFIGURER = configure_method
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ("METHOD_SPEC", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", "configure_method")
