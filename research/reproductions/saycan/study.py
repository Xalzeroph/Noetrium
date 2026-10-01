from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from enum import StrEnum
from research.benchmarks.saycan_101 import SAYCAN_ALL_SPLIT, SAYCAN_BENCHMARK_ID, SAYCAN_DATA_COMMIT, SAYCAN_TASK_COUNT
from .fidelity import SAYCAN_FIDELITY
from .source import SAYCAN_PAPER_CODE_COMMIT

class SayCanEvaluationScene(StrEnum):
    MOCK_KITCHEN = 'mock_kitchen'
    REAL_KITCHEN = 'real_kitchen'

def saycan_corl2022_trial_protocol(benchmark, *, scene: SayCanEvaluationScene):
    if benchmark.benchmark_id != SAYCAN_BENCHMARK_ID:
        raise ValueError('SayCan protocol requires canonical SayCan-101 benchmark')
    if not isinstance(scene, SayCanEvaluationScene):
        raise TypeError('SayCan scene must be SayCanEvaluationScene')
    selected = benchmark.selected_tasks(SAYCAN_ALL_SPLIT)
    if len(selected) != SAYCAN_TASK_COUNT:
        raise ValueError('SayCan protocol requires exactly 101 tasks')
    return _rs.study_protocol(f'saycan.corl2022.{scene.value}.101.v1', _rs.canonical_digest({'paper_code_commit': SAYCAN_PAPER_CODE_COMMIT, 'evaluation_data_commit': SAYCAN_DATA_COMMIT, 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_split_id': SAYCAN_ALL_SPLIT, 'task_count': len(selected), 'method_spec_digest': canonical_digest(METHOD_SPEC), 'scene': scene.value, 'planning_semantics': {'language_transform': SAYCAN_FIDELITY.language_score_transform, 'combined_score_rule': SAYCAN_FIDELITY.combined_score_rule, 'selection_rule': SAYCAN_FIDELITY.selection_rule, 'termination_string': SAYCAN_FIDELITY.termination_string, 'termination_affordance': SAYCAN_FIDELITY.termination_affordance}, 'plan_success_verifier': {'judge_count': 3, 'required_positive_votes': 2, 'semantic': 'human-plan-validity'}, 'execution_success_verifier': {'judge_count': 3, 'required_positive_votes': 2, 'semantic': 'human-task-achievement'}}))

@_rs.study_factory('benchmark')
def build_saycan_corl2022_study(benchmark, *, scene: SayCanEvaluationScene=SayCanEvaluationScene.MOCK_KITCHEN):
    protocol = saycan_corl2022_trial_protocol(benchmark, scene=scene)
    return _rs.study_spec(project_id='saycan-corl-2022-reproduction', study_id=f'saycan-corl-2022-{scene.value}-101', benchmark=benchmark, benchmark_split_id=SAYCAN_ALL_SPLIT, method=_rs.study_participant(role='language_affordance_embodied_planner', kind='method', implementation='saycan', treatment='corl-2022-protocol', capabilities=('environment.embodied', 'model.text.score', 'participant.capability', 'evaluation.human-majority'), configurations=('saycan.language-affordance-product', 'saycan.done-termination', 'saycan.plan-before-execute', f'saycan.scene-{scene.value}')), models={'language': _rs.study_model('model.saycan.paper-era-language-model', prompt='saycan.skill-selection.prompt'), 'affordance': _rs.study_model('model.saycan.paper-era-affordance-value', prompt='saycan.affordance-estimator')}, measurements=(_rs.scalar_measurement('plan_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='human_majority_plan_success', scale='binary', domain='saycan'), _rs.scalar_measurement('execution_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='human_majority_task_execution_success', scale='binary', domain='saycan'), _rs.scalar_measurement('planning_calls', schema_id='noetrium.measurement.count.v1', unit='model_call', semantic_kind='saycan_planning_calls', scale='count', domain='saycan'), _rs.scalar_measurement('executed_skill_count', schema_id='noetrium.measurement.count.v1', unit='skill', semantic_kind='saycan_executed_skill_count', scale='count', domain='saycan')), trial=protocol, repetitions=1, seeds=('published-evaluation-cut',), limits=_rs.trial_budget(f'saycan-corl2022-{scene.value}-budget', max_steps=256, max_turns=SAYCAN_FIDELITY.demo_max_tasks, max_model_calls=SAYCAN_FIDELITY.demo_max_tasks, max_working_seconds=1800.0), replay_level='observational', repetition_timeout_seconds=1800.0)
__all__ = ['SayCanEvaluationScene', 'build_saycan_corl2022_study', 'saycan_corl2022_trial_protocol']
