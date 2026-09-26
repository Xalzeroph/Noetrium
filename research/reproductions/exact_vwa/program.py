from __future__ import annotations
from .fidelity import EXACT_VWA_FIDELITY

def configure_method(method):
    """Compile the released ExACT VWA R-MCTS semantics into canonical MethodProgram IR."""
    fidelity = EXACT_VWA_FIDELITY
    phases = ({'phase_id': 'reconstruct_parent', 'role': 'exact.environment', 'instruction': 'Reset the browser task and replay the committed action history before evaluating a new search branch. Preserve replay receipts as evidence.', 'max_visits': 1}, {'phase_id': 'expand_policy', 'role': 'exact.policy', 'instruction': 'Generate the bounded Reflective-MCTS candidate action set from the current image-SOM observation and accumulated reflections.', 'max_visits': 1}, {'phase_id': 'debate_value', 'role': 'exact.value', 'instruction': 'Evaluate candidate branches with the released multi-agent debate value function under the exact value-function budget.', 'max_visits': 1}, {'phase_id': 'puct_select', 'role': 'exact.search', 'instruction': 'Select the next branch/action using the released PUCT search rule and bounded search depth.', 'max_visits': 1}, {'phase_id': 'commit_action', 'role': 'exact.policy', 'instruction': 'Commit the selected browser action to the authoritative environment trajectory and record the resulting observation.', 'max_visits': 1}, {'phase_id': 'contrastive_reflect', 'role': 'exact.reflection', 'instruction': 'When the released reflection threshold is met, construct contrastive reflection from explored alternatives and feed it into later policy steps.', 'max_visits': 1})
    method.configure({'source_lane_digest': fidelity.source.lane_digest, 'agent_type': fidelity.agent_type, 'benchmark_site': fidelity.benchmark_site, 'observation_type': fidelity.observation_type, 'action_set_tag': fidelity.action_set_tag, 'environment_branch_strategy': fidelity.environment_branch_strategy, 'max_depth': fidelity.max_depth, 'lookahead_steps': fidelity.lookahead_steps, 'branching_factor': fidelity.branching_factor, 'value_function_budget': fidelity.value_function_budget, 'puct': fidelity.puct, 'max_reflections_per_task': fidelity.max_reflections_per_task, 'reflection_threshold': fidelity.reflection_threshold, 'value_function_method': fidelity.value_function_method, 'value_max_reflections_per_task': fidelity.value_max_reflections_per_task, 'value_reflection_threshold': fidelity.value_reflection_threshold, 'policy_model_role': fidelity.policy_model, 'value_model_role': fidelity.value_model, 'reflective_model_role': fidelity.reflective_language_model, 'embedding_model_role': fidelity.embedding_model})
    method.phases(phases, max_cycles=fidelity.max_environment_steps)
    method.policy(evidence=('exact.phase-transcript', 'exact.model-receipts', 'exact.environment-replay', 'exact.search-decision', 'exact.reflection'), metrics=('task_success', 'environment_steps'), artifacts=('exact_vwa_trajectory', 'exact_vwa_search_tree', 'exact_vwa_reflections'))
    return method
METHOD_SPEC = {'method_id': 'exact', 'version': 'vwa-later-released-protocol', 'semantic_contract': 'exact.vwa.reflective-mcts.method.v1', 'entrypoint': 'reconstruct_parent'}
METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = 'reconstruct_parent'
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ['METHOD_SPEC', 'METHOD_CONFIGURER', 'METHOD_ENTRYPOINT', 'METHOD_CONFIGURER_ARGS', 'METHOD_CONFIGURER_KWARGS', 'configure_method']
