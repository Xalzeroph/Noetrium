from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.gsm8k import GSM8K_BENCHMARK_ID, GSM8K_SPLIT_COUNTS
from .fidelity import MULTIAGENT_DEBATE_FIDELITY
_GSM8K_SPLIT = 'test'

def multiagent_debate_gsm8k_trial_protocol(benchmark):
    f = MULTIAGENT_DEBATE_FIDELITY
    if benchmark.benchmark_id != GSM8K_BENCHMARK_ID:
        raise ValueError('multi-agent debate study requires GSM8K')
    selected = benchmark.selected_tasks(_GSM8K_SPLIT)
    if len(selected) != GSM8K_SPLIT_COUNTS[_GSM8K_SPLIT]:
        raise ValueError('multi-agent debate GSM8K lane requires the complete test split')
    return _rs.study_protocol('multiagent-debate.gsm8k.paper-era.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'task_ids': tuple((row.task_id for row in selected)), 'source_commit': f.audited_commit, 'agent_count': f.default_agent_count, 'round_count': f.default_round_count, 'independent_agent_contexts': f.independent_agent_contexts, 'round_information_semantics': f.round_information_semantics, 'peer_responses_are_injected_as_user_information': f.peer_responses_are_injected_as_user_information, 'reference_model': f.model_at_audited_gsm_script, 'final_answer_format': f.final_answer_format}))

@_rs.study_factory('benchmark')
def build_multiagent_debate_gsm8k_study(benchmark):
    f = MULTIAGENT_DEBATE_FIDELITY
    protocol = multiagent_debate_gsm8k_trial_protocol(benchmark)
    model_id = 'model.multiagent-debate.gpt-3.5-turbo-0301'
    return _rs.study_spec(project_id='multiagent-debate-reproduction', study_id='multiagent-debate-gsm8k-3-agent-2-round', benchmark=benchmark, benchmark_split_id=_GSM8K_SPLIT, method=_rs.study_participant(role='debate', kind='multi_agent_method', implementation='multiagent-debate', treatment='three-agent-two-round-paper-era', capabilities=(), configurations=('multiagent-debate.independent-contexts', 'multiagent-debate.previous-round-peer-snapshot', 'multiagent-debate.boxed-answer')), models={'multiagent-debate.agent-0': _rs.study_model(model_id, prompt='multiagent-debate.gsm8k.paper-era'), 'multiagent-debate.agent-1': _rs.study_model(model_id, prompt='multiagent-debate.gsm8k.paper-era'), 'multiagent-debate.agent-2': _rs.study_model(model_id, prompt='multiagent-debate.gsm8k.paper-era')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='exact_numeric_answer_success', scale='binary', domain='gsm8k'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='call', semantic_kind='resource_usage', scale='count', domain='multiagent_debate'), _rs.scalar_measurement('debate_round_count', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='debate_round_count', scale='count', domain='multiagent_debate')), trial=protocol, repetitions=1, seeds=('paper-era',), limits=_rs.trial_budget('multiagent-debate-3x2', max_steps=20, max_turns=6, max_model_calls=6, max_working_seconds=600.0), replay_level='observational')
__all__ = ['build_multiagent_debate_gsm8k_study', 'multiagent_debate_gsm8k_trial_protocol']
