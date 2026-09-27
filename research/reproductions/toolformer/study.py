from __future__ import annotations
from .program import METHOD_SPEC, TOOLFORMER_PAPER_CAPABILITY_IDS
from research.reproductions import _support as _rs
from research.benchmarks.toolformer_eval import TOOLFORMER_BENCHMARK_ID
from .fidelity import TOOLFORMER_FIDELITY

def toolformer_trial_protocol(tool_capability_ids: tuple[str, ...], *, tools_enabled: bool):
    return _rs.study_protocol('toolformer.neurips2023.tools-enabled.v1' if tools_enabled else 'toolformer.neurips2023.tools-disabled.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'publication_id': TOOLFORMER_FIDELITY.publication_id, 'tools_enabled': tools_enabled, 'tool_capability_ids': tool_capability_ids if tools_enabled else (), 'api_top_k': TOOLFORMER_FIDELITY.evaluation_api_top_k, 'max_api_calls_per_input': TOOLFORMER_FIDELITY.evaluation_max_api_calls_per_input}))

@_rs.study_factory('benchmark')
def build_toolformer_study(benchmark, *, split_id: str, tool_capability_ids: tuple[str, ...]=TOOLFORMER_PAPER_CAPABILITY_IDS, tools_enabled: bool=True):
    if benchmark.benchmark_id != TOOLFORMER_BENCHMARK_ID:
        raise ValueError('Toolformer study requires toolformer-eval')
    if not benchmark.selected_tasks(split_id):
        raise ValueError('Toolformer study requires a non-empty split')
    treatment = 'toolformer' if tools_enabled else 'toolformer-disabled'
    return _rs.study_spec(project_id='toolformer-neurips2023-reproduction', study_id=f'toolformer-{split_id}-{treatment}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='toolformer', kind='agent_method', implementation='toolformer-paper-era', treatment=treatment, capabilities=tool_capability_ids if tools_enabled else (), configurations=('toolformer.gpt-j-api-aware-decoding', f'toolformer.tools-enabled:{str(tools_enabled).lower()}')), models={'toolformer': _rs.study_model('model.toolformer.gpt-j', prompt='toolformer.zero-shot.paper-era')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='task_success', scale='binary', domain='toolformer'), _rs.scalar_measurement('tool_call_count', schema_id='noetrium.measurement.count.v1', unit='tool_call', semantic_kind='tool_usage', scale='count', domain='toolformer'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='model_call', semantic_kind='model_usage', scale='count', domain='toolformer')), trial=toolformer_trial_protocol(tool_capability_ids, tools_enabled=tools_enabled), repetitions=1, seeds=('0',), limits=_rs.trial_budget(f'toolformer-{treatment}', max_steps=8, max_model_calls=2 if tools_enabled else 1, max_working_seconds=300.0), replay_level='observational')
__all__ = ['build_toolformer_study', 'toolformer_trial_protocol']
