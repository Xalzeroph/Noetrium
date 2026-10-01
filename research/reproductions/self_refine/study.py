from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.commongen import COMMONGEN_BENCHMARK_ID
from .fidelity import SELF_REFINE_FIDELITY

def self_refine_commongen_trial_protocol(benchmark, *, split_id: str):
    if benchmark.benchmark_id != COMMONGEN_BENCHMARK_ID:
        raise ValueError('Self-Refine CommonGen study requires CommonGen benchmark')
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError('Self-Refine CommonGen study requires a non-empty split')
    return _rs.study_protocol('self-refine.commongen.paper-era.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'source_commit': SELF_REFINE_FIDELITY.audited_commit, 'prompt_blobs': (SELF_REFINE_FIDELITY.commongen_init_prompt_blob, SELF_REFINE_FIDELITY.commongen_feedback_prompt_blob, SELF_REFINE_FIDELITY.commongen_iterate_prompt_blob), 'max_attempts': SELF_REFINE_FIDELITY.commongen_max_attempts, 'temperature': SELF_REFINE_FIDELITY.commongen_temperature, 'max_output_tokens': SELF_REFINE_FIDELITY.commongen_max_output_tokens, 'stop_condition': SELF_REFINE_FIDELITY.commongen_stop_condition, 'shared_model_across_init_feedback_iterate': True}))

@_rs.study_factory('benchmark')
def build_self_refine_commongen_study(benchmark, *, split_id: str):
    protocol = self_refine_commongen_trial_protocol(benchmark, split_id=split_id)
    measurements = (_rs.scalar_measurement('direct_concept_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='concept_coverage_success', scale='binary', domain='commongen'), _rs.scalar_measurement('direct_commonsense_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='commonsense_feedback_success', scale='binary', domain='commongen'), _rs.scalar_measurement('direct_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='direct_generation_success', scale='binary', domain='commongen'), _rs.scalar_measurement('iter_concept_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='concept_coverage_success_after_refinement', scale='binary', domain='commongen'), _rs.scalar_measurement('iter_commonsense_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='commonsense_feedback_success_after_refinement', scale='binary', domain='commongen'), _rs.scalar_measurement('iter_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='iterative_refinement_success', scale='binary', domain='commongen'), _rs.scalar_measurement('attempt_count', schema_id='noetrium.measurement.count.v1', unit='attempt', semantic_kind='refinement_attempt_count', scale='count', domain='self_refine'))
    return _rs.study_spec(project_id='self-refine-neurips-2023-reproduction', study_id=f'self-refine-commongen-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='self_refine', kind='agent_method', implementation='self-refine', treatment='paper-era-commongen', capabilities=(), configurations=('self-refine.commongen.paper-era', 'self-refine.commongen.prompt-bundle')), models={'self-refine.model': _rs.study_model('model.self-refine.shared', prompt='self-refine.commongen.paper-era-prompts')}, measurements=measurements, trial=protocol, repetitions=1, seeds=('0',), limits=_rs.trial_budget('self-refine-commongen-4-attempts', max_steps=64, max_turns=SELF_REFINE_FIDELITY.commongen_max_attempts * 2, max_model_calls=SELF_REFINE_FIDELITY.commongen_max_attempts * 2, max_working_seconds=1800.0), replay_level='observational')
__all__ = ['build_self_refine_commongen_study', 'self_refine_commongen_trial_protocol']
