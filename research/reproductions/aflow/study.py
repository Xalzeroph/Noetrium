from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.humaneval import HUMANEVAL_BENCHMARK_ID, HUMANEVAL_SPLIT_ID, HUMANEVAL_TASK_COUNT
from .fidelity import AFLOW_FIDELITY

def aflow_iclr2025_humaneval_trial_protocol(benchmark):
    if benchmark.benchmark_id != HUMANEVAL_BENCHMARK_ID:
        raise ValueError('AFlow protocol requires HumanEval')
    selected = benchmark.selected_tasks(HUMANEVAL_SPLIT_ID)
    if len(selected) != HUMANEVAL_TASK_COUNT:
        raise ValueError('AFlow HumanEval protocol requires the 164-task cut')
    return _rs.study_protocol('aflow.iclr2025.humaneval.protocol-bound.v1', _rs.canonical_digest({'source_commit': AFLOW_FIDELITY.audited_commit, 'program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'task_ids': tuple((row.task_id for row in selected)), 'initial_round': AFLOW_FIDELITY.initial_round, 'optimization_iterations': AFLOW_FIDELITY.optimization_iterations, 'parent_pool_size': AFLOW_FIDELITY.parent_pool_size, 'softmax_alpha': AFLOW_FIDELITY.softmax_alpha, 'uniform_mix_weight': AFLOW_FIDELITY.uniform_mix_weight, 'validation_repetitions': AFLOW_FIDELITY.validation_repetitions, 'test_repetitions': AFLOW_FIDELITY.test_repetitions, 'convergence_top_k': AFLOW_FIDELITY.convergence_top_k, 'convergence_consecutive_rounds': AFLOW_FIDELITY.convergence_consecutive_rounds, 'optimizer_model': AFLOW_FIDELITY.optimizer_model, 'execution_model': AFLOW_FIDELITY.execution_model, 'paper_archive_status': 'external-archive-not-content-addressed'}))

@_rs.study_factory('benchmark')
def build_aflow_iclr2025_humaneval_study(benchmark):
    protocol = aflow_iclr2025_humaneval_trial_protocol(benchmark)
    return _rs.study_spec(project_id='aflow-iclr-2025-reproduction', study_id='aflow-iclr-2025-humaneval-protocol-bound', benchmark=benchmark, benchmark_split_id=HUMANEVAL_SPLIT_ID, method=_rs.study_participant(role='agentic_workflow_optimizer', kind='optimization_method', implementation='aflow-paper-era', treatment='iclr-2025-paper-era', configurations=('aflow.code-represented-workflows', 'aflow.mixed-weighted-parent-selection', 'aflow.experience-conditioned-mutation', 'aflow.top-k-convergence')), models={'optimizer': _rs.study_model(f'model.{AFLOW_FIDELITY.optimizer_model}', prompt='aflow.optimizer.paper-era'), 'executor': _rs.study_model(f'model.{AFLOW_FIDELITY.execution_model}', prompt='aflow.workflow-execution.paper-era')}, measurements=(_rs.scalar_measurement('best_validation_score', schema_id='noetrium.measurement.scalar.v1', unit='score', semantic_kind='best_workflow_validation_score', scale='continuous', domain='aflow'), _rs.scalar_measurement('workflow_candidates', schema_id='noetrium.measurement.count.v1', unit='workflow', semantic_kind='materialized_workflow_candidate_count', scale='count', domain='aflow'), _rs.scalar_measurement('optimization_rounds', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='workflow_optimization_round_count', scale='count', domain='aflow'), _rs.scalar_measurement('test_score', schema_id='noetrium.measurement.scalar.v1', unit='score', semantic_kind='selected_workflow_test_score', scale='continuous', domain='humaneval')), trial=protocol, repetitions=1, seeds=('paper-rng-ambient-unpinned',), limits=_rs.trial_budget('aflow-iclr2025-humaneval-safety', max_steps=256, max_turns=128, max_model_calls=512, max_working_seconds=7200.0), replay_level='observational', repetition_timeout_seconds=7200.0)
__all__ = ['aflow_iclr2025_humaneval_trial_protocol', 'build_aflow_iclr2025_humaneval_study']
