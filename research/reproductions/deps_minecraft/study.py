from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from .benchmark import DEPS_ALL_SPLIT, DEPS_MINECRAFT_BENCHMARK_ID, DEPS_TASK_COUNT, DEPS_TASK_IDENTITIES
from .fidelity import DEPS_MINECRAFT_FIDELITY
from .source import DEPS_RELEASE_COMMIT, DEPS_REPLAN_SEMANTICS_COMMIT

def deps_neurips2023_trial_protocol(benchmark):
    if benchmark.benchmark_id != DEPS_MINECRAFT_BENCHMARK_ID:
        raise ValueError('DEPS Study requires the official 70-task Minecraft cut')
    selected = benchmark.selected_tasks(DEPS_ALL_SPLIT)
    if len(selected) != DEPS_TASK_COUNT:
        raise ValueError('DEPS Study requires exactly 70 official tasks')
    fidelity = DEPS_MINECRAFT_FIDELITY
    return _rs.study_protocol('deps.neurips2023.minecraft-70.paper-release.v1', _rs.canonical_digest({'source_commit': DEPS_RELEASE_COMMIT, 'replan_semantics_commit': DEPS_REPLAN_SEMANTICS_COMMIT, 'method_spec_digest': canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_split_id': DEPS_ALL_SPLIT, 'task_ids': tuple((row.task_id for row in selected)), 'source_task_rows': DEPS_TASK_IDENTITIES, 'planner_model': fidelity.planner_model, 'planner_temperature': fidelity.planner_temperature, 'planner_max_tokens': fidelity.planner_max_tokens, 'parser_model': fidelity.parser_model, 'parser_temperature': fidelity.parser_temperature, 'parser_max_tokens': fidelity.parser_max_tokens, 'parser_prompt_tail_characters': fidelity.parser_prompt_tail_characters, 'model_query_retry_limit': fidelity.model_query_retry_limit, 'craft_replan_step_threshold': fidelity.craft_replan_step_threshold, 'smelt_replan_step_threshold': fidelity.smelt_replan_step_threshold, 'mine_replans_on_unsatisfied_precondition': fidelity.mine_replans_on_unsatisfied_precondition, 'replan_round_limit': fidelity.replan_round_limit, 'learned_goal_selector': fidelity.learned_goal_selector, 'selector_release_complete': fidelity.selector_release_complete, 'environment_episode_ceilings': tuple((row[4] for row in DEPS_TASK_IDENTITIES))}))

@_rs.study_factory('benchmark')
def build_deps_neurips2023_study(benchmark):
    protocol = deps_neurips2023_trial_protocol(benchmark)
    fidelity = DEPS_MINECRAFT_FIDELITY
    return _rs.study_spec(project_id='deps-neurips-2023-reproduction', study_id='deps-neurips-2023-minecraft-70', benchmark=benchmark, benchmark_split_id=DEPS_ALL_SPLIT, method=_rs.study_participant(role='interactive_minecraft_planner', kind='agent_method', implementation='deps-minecraft', treatment='neurips-2023-paper-release', capabilities=('environment.act',), configurations=('deps.describe-explain-plan-select', 'deps.failure-conditioned-replanning', 'deps.learned-horizon-goal-selector', 'deps.goal-conditioned-controller')), models={'planner': _rs.study_model('model.openai.code-davinci-002.paper-era', prompt='deps.task-and-replan-prompts'), 'parser': _rs.study_model('model.openai.text-davinci-003.paper-era', prompt='deps.goal-parser-prompt'), 'selector': _rs.study_model('model.deps.learned-goal-selector.paper-era', prompt='deps.horizon-ranking')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='minecraft_task_success', scale='binary', domain='deps'), _rs.scalar_measurement('episode_steps', schema_id='noetrium.measurement.count.v1', unit='environment_step', semantic_kind='minecraft_episode_length', scale='count', domain='deps'), _rs.scalar_measurement('replan_rounds', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='interactive_replanning_round_count', scale='count', domain='deps'), _rs.scalar_measurement('trajectory_steps', schema_id='noetrium.measurement.count.v1', unit='high_level_goal_execution', semantic_kind='goal_controller_invocation_count', scale='count', domain='deps')), trial=protocol, repetitions=1, seeds=('paper-environment-default',), limits=_rs.trial_budget('deps-neurips2023-minecraft-70-safety', max_steps=65536, max_turns=16384, max_model_calls=512, max_working_seconds=7200.0), replay_level='observational', repetition_timeout_seconds=7200.0)
__all__ = ['build_deps_neurips2023_study', 'deps_neurips2023_trial_protocol']
