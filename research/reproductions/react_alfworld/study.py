from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.alfworld import ALFWORLD_BENCHMARK_ID, ALFWORLD_PAPER_EVAL_REVISION, ALFWORLD_PAPER_EVAL_SPLIT
from .fidelity import REACT_ALFWORLD_FIDELITY
REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL = _rs.study_protocol('react.alfworld.released-code.v1', _rs.canonical_digest({'program_digest': canonical_digest(METHOD_SPEC), 'model': REACT_ALFWORLD_FIDELITY.reference_model, 'temperature': REACT_ALFWORLD_FIDELITY.temperature, 'max_output_tokens': REACT_ALFWORLD_FIDELITY.max_output_tokens, 'stop_sequences': REACT_ALFWORLD_FIDELITY.stop_sequences, 'max_turns': REACT_ALFWORLD_FIDELITY.max_turns}))

@_rs.requires_benchmark_cut(ALFWORLD_BENCHMARK_ID, ALFWORLD_PAPER_EVAL_REVISION, split_ids=(ALFWORLD_PAPER_EVAL_SPLIT,))
@_rs.study_factory('benchmark')
def build_react_alfworld_released_study(benchmark):
    """Author the released-code ReAct ALFWorld sweep through the generic Study compiler."""
    if benchmark.benchmark_id != ALFWORLD_BENCHMARK_ID:
        raise ValueError('ReAct ALFWorld study requires the shared ALFWorld benchmark cut')
    benchmark.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)
    return _rs.study_spec(project_id='react-alfworld-reproduction', study_id='react-alfworld-released-code', benchmark=benchmark, benchmark_split_id=ALFWORLD_PAPER_EVAL_SPLIT, method=_rs.study_participant(role='agent', kind='agent', implementation='react', treatment='released-code', capabilities=('environment.act',), configurations=('react.alfworld.prompt',)), models={'action': _rs.study_model('model.react.action', prompt='react.alfworld.prompt')}, measurements=(_rs.scalar_measurement('episode_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='task_success', scale='binary', domain='alfworld'), _rs.scalar_measurement('turn_count', schema_id='noetrium.measurement.count.v1', unit='turn', semantic_kind='resource_usage', scale='count', domain='alfworld')), trial=REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL, repetitions=1, seeds=('42',), limits=_rs.trial_budget('react-alfworld-49-turn', max_steps=49), replay_level='observational')
__all__ = ['REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL', 'build_react_alfworld_released_study']
