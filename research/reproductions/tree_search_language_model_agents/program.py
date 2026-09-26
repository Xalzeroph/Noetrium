from __future__ import annotations
from .fidelity import TREE_SEARCH_VWA_FIDELITY

def configure_method(method):
    """Compile the released value-function tree-search loop into MethodProgram IR."""
    fidelity = TREE_SEARCH_VWA_FIDELITY
    phases = ({'phase_id': 'reconstruct_parent', 'role': 'tree-search.environment', 'instruction': 'Open a fresh task session and replay the committed action prefix before evaluating a candidate branch.', 'max_visits': 1}, {'phase_id': 'expand', 'role': 'tree-search.policy', 'instruction': 'Generate at most the released branching-factor candidate browser actions from the current image-SOM observation.', 'max_visits': 1}, {'phase_id': 'evaluate', 'role': 'tree-search.value', 'instruction': 'Score candidate partial trajectories with the frozen value-function role under the released per-step evaluation budget.', 'max_visits': 1}, {'phase_id': 'select', 'role': 'tree-search.search', 'instruction': 'Select the best branch under the released value-function tree-search policy and bounded lookahead depth.', 'max_visits': 1}, {'phase_id': 'commit', 'role': 'tree-search.policy', 'instruction': 'Commit the selected browser action, retain the partial trajectory, and advance the authoritative environment state.', 'max_visits': 1})
    method.configure({'source_lane_digest': fidelity.source.lane_digest, 'benchmark': fidelity.benchmark, 'site': fidelity.site, 'agent_type': fidelity.agent_type, 'search_algorithm': fidelity.search_algorithm, 'policy_model_role': fidelity.policy_model, 'value_model_role': fidelity.value_model, 'evaluation_captioner_model': fidelity.evaluation_captioner_model, 'max_steps': fidelity.max_steps, 'max_depth': fidelity.max_depth, 'lookahead_steps': fidelity.lookahead_steps, 'branching_factor': fidelity.branching_factor, 'value_function_budget': fidelity.value_function_budget, 'environment_branch_strategy': fidelity.environment_branch_strategy, 'observation_type': fidelity.observation_type, 'action_set_tag': fidelity.action_set_tag, 'prompt_path': fidelity.prompt_path})
    method.phases(phases, max_cycles=fidelity.max_steps)
    method.policy(evidence=('tree-search.phase-transcript', 'tree-search.model-receipts', 'tree-search.environment-replay', 'tree-search.value-evaluations', 'tree-search.branch-selection'), metrics=('task_score', 'task_success', 'committed_steps', 'value_evaluations'), artifacts=('tree_search_vwa_trajectory', 'tree_search_vwa_search_tree'))
    return method
METHOD_SPEC = {'method_id': 'tree-search-language-model-agents', 'version': 'official-released-vwa-search', 'semantic_contract': 'tree-search-language-model-agents.vwa.method.v1', 'entrypoint': 'reconstruct_parent'}
METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = 'reconstruct_parent'
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ['METHOD_SPEC', 'METHOD_CONFIGURER', 'METHOD_ENTRYPOINT', 'METHOD_CONFIGURER_ARGS', 'METHOD_CONFIGURER_KWARGS', 'configure_method']
