from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.generative_agents_smallville import GENERATIVE_AGENTS_BENCHMARK_ID, GENERATIVE_AGENTS_SPLIT_ID, build_generative_agents_smallville_cut
from .fidelity import GENERATIVE_AGENTS_AUDITED_COMMIT
from .program import METHOD_SPEC

def generative_agents_trial_protocol(*, enable_reflection: bool, enable_planning: bool):
    return _rs.study_protocol('generative-agents.uist2023.smallville.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'source_commit': GENERATIVE_AGENTS_AUDITED_COMMIT, 'reflection': enable_reflection, 'planning': enable_planning, 'population_size': 25}))

@_rs.study_factory('benchmark')
def build_generative_agents_smallville_study(benchmark=None, *, enable_reflection: bool=True, enable_planning: bool=True):
    benchmark = benchmark or build_generative_agents_smallville_cut()
    if benchmark.benchmark_id != GENERATIVE_AGENTS_BENCHMARK_ID:
        raise ValueError('Generative Agents study requires Smallville protocol cut')
    treatment = 'full' if enable_reflection and enable_planning else 'no-reflection' if not enable_reflection and enable_planning else 'no-planning' if enable_reflection and (not enable_planning) else 'memory-only'
    return _rs.study_spec(project_id='generative-agents-uist2023-reproduction', study_id=f'generative-agents-smallville-{treatment}', benchmark=benchmark, benchmark_split_id=GENERATIVE_AGENTS_SPLIT_ID, method=_rs.study_participant(role='generative-agents', kind='agent_method', implementation='generative-agents-paper-era', treatment=treatment, configurations=('generative-agents.memory-reflection-planning',)), models={'reflection': _rs.study_model('model.generative-agents.reflection', prompt='generative-agents.reflection.paper-era', required=enable_reflection), 'planning': _rs.study_model('model.generative-agents.planning', prompt='generative-agents.planning.paper-era', required=enable_planning), 'behavior': _rs.study_model('model.generative-agents.behavior', prompt='generative-agents.behavior.paper-era')}, measurements=(_rs.scalar_measurement('believability_score', schema_id='noetrium.measurement.scalar.v1', unit='score', semantic_kind='human_believability', scale='interval', domain='generative-agents'), _rs.scalar_measurement('reflection_count', schema_id='noetrium.measurement.count.v1', unit='reflection', semantic_kind='reflection_usage', scale='count', domain='generative-agents'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='model_call', semantic_kind='model_usage', scale='count', domain='generative-agents')), trial=generative_agents_trial_protocol(enable_reflection=enable_reflection, enable_planning=enable_planning), repetitions=1, seeds=('0',), limits=_rs.trial_budget(f'generative-agents-smallville-{treatment}', max_steps=4096, max_model_calls=4096, max_working_seconds=86400.0), replay_level='observational')
__all__ = ['build_generative_agents_smallville_study', 'generative_agents_trial_protocol']
