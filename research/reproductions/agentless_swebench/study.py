from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.swe_bench import SWEBENCH_BENCHMARK_ID
from .fidelity import AGENTLESS_FIDELITY
AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL = _rs.study_protocol('agentless.fse2025.swe-bench-lite.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'source_commit': AGENTLESS_FIDELITY.audited_commit, 'release': AGENTLESS_FIDELITY.release, 'stages': AGENTLESS_FIDELITY.stages, 'localization_levels': AGENTLESS_FIDELITY.localization_levels, 'benchmark_subset': AGENTLESS_FIDELITY.benchmark_subset, 'benchmark_task_count': AGENTLESS_FIDELITY.benchmark_task_count, 'autonomous_agent_loop': False}))

@_rs.study_factory('benchmark')
def build_agentless_swebench_lite_study(benchmark, *, split_id: str):
    if benchmark.benchmark_id != SWEBENCH_BENCHMARK_ID:
        raise ValueError('Agentless study requires SWE-bench')
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError('Agentless study requires a non-empty SWE-bench split')
    return _rs.study_spec(project_id='agentless-fse2025-reproduction', study_id=f'agentless-swe-bench-lite-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='workflow', kind='software_repair_method', implementation='agentless-v1.5.0', treatment='localize-repair-validate', capabilities=('software.command',), configurations=('agentless.hierarchical-localization', 'agentless.patch-sampling', 'agentless.patch-validation')), models={'file_localizer': _rs.study_model('model.agentless.file-localizer', prompt='agentless.localization.files'), 'symbol_localizer': _rs.study_model('model.agentless.symbol-localizer', prompt='agentless.localization.symbols'), 'edit_localizer': _rs.study_model('model.agentless.edit-localizer', prompt='agentless.localization.edits'), 'repair': _rs.study_model('model.agentless.repair', prompt='agentless.repair'), 'validation': _rs.study_model('model.agentless.validation', prompt='agentless.validation'), 'rerank': _rs.study_model('model.agentless.rerank', prompt='agentless.rerank')}, measurements=(_rs.scalar_measurement('task_resolved', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='task_success', scale='binary', domain='swe-bench'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='model_call', semantic_kind='model_usage', scale='count', domain='agentless'), _rs.scalar_measurement('validation_count', schema_id='noetrium.measurement.count.v1', unit='validation_batch', semantic_kind='validation_usage', scale='count', domain='agentless')), trial=AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL, repetitions=1, seeds=('0',), limits=_rs.trial_budget('agentless-fse2025', max_steps=32, max_model_calls=16, max_working_seconds=3600.0), replay_level='observational')
__all__ = ['AGENTLESS_SWEBENCH_LITE_TRIAL_PROTOCOL', 'build_agentless_swebench_lite_study']
