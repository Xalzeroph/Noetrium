from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.gsm8k import GSM8K_BENCHMARK_ID, GSM8K_SPLIT_COUNTS
from .fidelity import CHAIN_OF_THOUGHT_GSM8K_FIDELITY

def chain_of_thought_gsm8k_trial_protocol(benchmark):
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    if benchmark.benchmark_id != GSM8K_BENCHMARK_ID:
        raise ValueError('CoT study requires GSM8K benchmark')
    selected = benchmark.selected_tasks(f.benchmark_split)
    if len(selected) != GSM8K_SPLIT_COUNTS['test']:
        raise ValueError('CoT GSM8K paper lane requires the full 1319-task test split')
    return _rs.study_protocol('chain-of-thought.neurips-2022.gsm8k.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'task_ids': tuple((row.task_id for row in selected)), 'publication_lane_digest': f.publication.lane_digest, 'prompt_bundle': 'cot.gsm8k.neurips2022.appendix-table20', 'exemplar_count': f.exemplar_count, 'decoding': f.decoding, 'samples_per_task': f.samples_per_task, 'calculator_enabled': f.calculator_enabled, 'paper_reference_model': f.paper_reference_model}))

@_rs.study_factory('benchmark')
def build_chain_of_thought_gsm8k_study(benchmark):
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    protocol = chain_of_thought_gsm8k_trial_protocol(benchmark)
    return _rs.study_spec(project_id='chain-of-thought-neurips-2022-reproduction', study_id='cot-gsm8k-eight-shot-greedy', benchmark=benchmark, benchmark_split_id=f.benchmark_split, method=_rs.study_participant(role='reasoner', kind='agent_method', implementation='chain-of-thought', treatment='eight-shot-cot-greedy', configurations=('cot.gsm8k.neurips2022.appendix-table20', 'cot.gsm8k.greedy')), models={'cot.reasoner': _rs.study_model('model.palm-540b.paper-reference', prompt='cot.gsm8k.neurips2022.appendix-table20')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='exact_numeric_answer_success', scale='binary', domain='gsm8k'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='call', semantic_kind='resource_usage', scale='count', domain='chain_of_thought')), trial=protocol, repetitions=1, seeds=('paper-greedy',), limits=_rs.trial_budget('cot-gsm8k-single-greedy-path', max_steps=8, max_model_calls=1), replay_level='observational')
__all__ = ['build_chain_of_thought_gsm8k_study', 'chain_of_thought_gsm8k_trial_protocol']
