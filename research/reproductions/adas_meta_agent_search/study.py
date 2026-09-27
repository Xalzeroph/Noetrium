from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.mgsm import MGSM_ADAS_TEST_SPLIT, MGSM_ADAS_VALID_SIZE, MGSM_ADAS_VALID_SPLIT, MGSM_BENCHMARK_ID
from .fidelity import ADAS_META_AGENT_SEARCH_FIDELITY
_CANDIDATE_EXECUTION_CAPABILITY = 'workbench.candidate-program.execute'

def _validation_workload(benchmark):
    validation = benchmark.selected_tasks(MGSM_ADAS_VALID_SPLIT)
    if not validation:
        raise ValueError('ADAS validation workload cannot be empty')
    return _rs.assignment_workload(tuple((row.task_id for row in validation)))

def adas_mgsm_search_trial_protocol(benchmark):
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    if benchmark.benchmark_id != MGSM_BENCHMARK_ID:
        raise ValueError('ADAS formal search protocol requires MGSM')
    validation = benchmark.selected_tasks(MGSM_ADAS_VALID_SPLIT)
    if len(validation) != fidelity.validation_size:
        raise ValueError(f'ADAS MGSM validation split cardinality drifted: expected={fidelity.validation_size} actual={len(validation)}')
    test = benchmark.selected_tasks(MGSM_ADAS_TEST_SPLIT)
    if len(test) != fidelity.test_size:
        raise ValueError(f'ADAS MGSM test split cardinality drifted: expected={fidelity.test_size} actual={len(test)}')
    workload = _validation_workload(benchmark)
    return _rs.study_protocol('adas.meta-agent-search.mgsm.validation.v1', _rs.canonical_digest({'program_digest': canonical_digest(METHOD_SPEC), 'source_commit': fidelity.audited_commit, 'source_artifact': fidelity.source_artifact, 'prompt_artifact': fidelity.prompt_artifact, 'benchmark_cut_digest': benchmark.cut_digest, 'validation_split_id': MGSM_ADAS_VALID_SPLIT, 'validation_task_ids': tuple((row.task_id for row in validation)), 'test_split_id': MGSM_ADAS_TEST_SPLIT, 'test_task_ids': tuple((row.task_id for row in test)), 'assignment_workload_digest': _rs.canonical_digest(workload), 'generation_budget': fidelity.generation_budget, 'reflection_passes': fidelity.reflection_passes_per_generation, 'candidate_execution_attempt_budget': fidelity.candidate_execution_attempt_budget, 'low_accuracy_debug_threshold': fidelity.low_accuracy_debug_threshold, 'bootstrap_samples': fidelity.bootstrap_samples, 'bootstrap_confidence_level': fidelity.bootstrap_confidence_level, 'test_data_visible_to_search': False}))

@_rs.study_factory('benchmark')
def build_adas_mgsm_search_study(benchmark):
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    workload = _validation_workload(benchmark)
    protocol = adas_mgsm_search_trial_protocol(benchmark)
    return _rs.study_spec(project_id='adas-iclr-2025-reproduction', study_id='adas-iclr-2025-mgsm-meta-agent-search', benchmark=benchmark, benchmark_split_id=MGSM_ADAS_VALID_SPLIT, assignment_workloads=(workload,), method=_rs.study_participant(role='meta_search', kind='method', implementation='adas-meta-agent-search', treatment='paper-era-mgsm-meta-agent-search', capabilities=(_CANDIDATE_EXECUTION_CAPABILITY,), configurations=('adas.meta-agent-search.mgsm', 'adas.candidate-execution.mgsm-validation')), models={'meta_agent': _rs.study_model('model.adas.meta-agent', prompt='adas.meta-agent.mgsm.prompt')}, measurements=(_rs.scalar_measurement('best_validation_accuracy', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='best_search_validation_accuracy', scale='continuous', domain='mgsm'), _rs.scalar_measurement('best_fitness_median', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='best_bootstrap_fitness_median', scale='continuous', domain='mgsm'), _rs.scalar_measurement('archive_size', schema_id='noetrium.measurement.count.v1', unit='candidate', semantic_kind='agent_design_archive_size', scale='count', domain='meta_search'), _rs.scalar_measurement('successful_generation_count', schema_id='noetrium.measurement.count.v1', unit='generation', semantic_kind='accepted_agent_design_generation', scale='count', domain='meta_search'), _rs.scalar_measurement('failed_generation_count', schema_id='noetrium.measurement.count.v1', unit='generation', semantic_kind='skipped_agent_design_generation', scale='count', domain='meta_search')), trial=protocol, repetitions=1, seeds=(str(fidelity.shuffle_seed),), limits=_rs.trial_budget('adas-iclr-2025-mgsm-meta-search', max_steps=4096, max_turns=fidelity.generation_budget * (1 + fidelity.reflection_passes_per_generation + fidelity.candidate_execution_attempt_budget), max_model_calls=fidelity.generation_budget * (1 + fidelity.reflection_passes_per_generation + fidelity.candidate_execution_attempt_budget), max_working_seconds=86400.0), replay_level='observational', repetition_timeout_seconds=86400.0)
__all__ = ['adas_mgsm_search_trial_protocol', 'build_adas_mgsm_search_study']
