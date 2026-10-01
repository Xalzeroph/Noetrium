from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.mind2web import MIND2WEB_BENCHMARK_ID
from .fidelity import COGAGENT_FIDELITY
COGAGENT_MIND2WEB_TRIAL_PROTOCOL = _rs.study_protocol('cogagent.cvpr2024.mind2web.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'paper_input_resolution': COGAGENT_FIDELITY.input_resolution, 'input_representation': COGAGENT_FIDELITY.gui_input_representation, 'operation_types': COGAGENT_FIDELITY.mind2web_operation_types, 'candidate_policy': 'benchmark-provided-top-k'}))

@_rs.study_factory('benchmark')
def build_cogagent_mind2web_study(benchmark, *, split_id: str):
    if benchmark.benchmark_id != MIND2WEB_BENCHMARK_ID:
        raise ValueError('CogAgent study requires Mind2Web')
    if not benchmark.selected_tasks(split_id):
        raise ValueError('CogAgent Mind2Web study requires a non-empty split')
    return _rs.study_spec(project_id='cogagent-cvpr2024-reproduction', study_id=f'cogagent-mind2web-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='cogagent', kind='visual_gui_agent', implementation='cogagent-18b-paper-era', treatment='screenshot-only', configurations=('cogagent.cvpr2024.gui-policy',)), models={'cogagent': _rs.study_model('model.cogagent-18b', prompt='cogagent.mind2web.paper-era')}, measurements=(_rs.scalar_measurement('step_success_rate', schema_id='noetrium.measurement.scalar.v1', unit='ratio', semantic_kind='step_success', scale='ratio', domain='mind2web'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='model_call', semantic_kind='model_usage', scale='count', domain='mind2web')), trial=COGAGENT_MIND2WEB_TRIAL_PROTOCOL, repetitions=1, seeds=('0',), limits=_rs.trial_budget('cogagent-mind2web', max_steps=4, max_model_calls=1, max_working_seconds=300.0), replay_level='observational')
__all__ = ['COGAGENT_MIND2WEB_TRIAL_PROTOCOL', 'build_cogagent_mind2web_study']
