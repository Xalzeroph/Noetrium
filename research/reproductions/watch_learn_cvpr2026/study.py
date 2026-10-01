from __future__ import annotations
from research.reproductions import _support as _rs
from .benchmark import require_watch_and_learn_benchmark
from .fidelity import WATCH_AND_LEARN_FIDELITY
from .program import METHOD_SPEC

def watch_and_learn_trial_protocol(benchmark, *, split_id: str):
    selected = require_watch_and_learn_benchmark(benchmark, split_id=split_id)
    return _rs.study_protocol('watch-and-learn.2026.paper-protocol.v1', _rs.canonical_digest({'paper_uri': WATCH_AND_LEARN_FIDELITY.paper_uri, 'method_spec_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_id': benchmark.benchmark_id, 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'phase_ids': WATCH_AND_LEARN_FIDELITY.phase_ids}))

@_rs.study_factory('benchmark')
def build_watch_and_learn_study(benchmark, *, split_id: str):
    trial = watch_and_learn_trial_protocol(benchmark, split_id=split_id)
    return _rs.study_spec(project_id='watch-and-learn-2026-reproduction', study_id=f'watch-and-learn-2026-{benchmark.benchmark_id}-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='watch-and-learn_agent', kind='agent_method', implementation='watch-and-learn', treatment='cvpr-2026-paper-protocol', capabilities=('model.generate',), configurations=WATCH_AND_LEARN_FIDELITY.phase_ids), models={'controller': _rs.study_model('model.watch-and-learn.paper-era', prompt='watch-and-learn.paper-protocol')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='task_success', scale='continuous', domain=benchmark.benchmark_id), _rs.scalar_measurement('agent_phase_count', schema_id='noetrium.measurement.count.v1', unit='phase', semantic_kind='agent_phase_count', scale='count', domain='watch-and-learn')), trial=trial, repetitions=1, seeds=('paper-protocol',), limits=_rs.trial_budget('watch-and-learn-2026-budget', max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_watch_and_learn_study', 'watch_and_learn_trial_protocol']
