from __future__ import annotations
from research.reproductions import _support as _rs
from .benchmark import require_r2d2_benchmark
from .fidelity import R2D2_FIDELITY
from .program import METHOD_SPEC

def r2d2_trial_protocol(benchmark, *, split_id: str):
    selected = require_r2d2_benchmark(benchmark, split_id=split_id)
    return _rs.study_protocol('r2d2.2025.paper-protocol.v1', _rs.canonical_digest({'paper_uri': R2D2_FIDELITY.paper_uri, 'method_spec_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_id': benchmark.benchmark_id, 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'phase_ids': R2D2_FIDELITY.phase_ids}))

@_rs.study_factory('benchmark')
def build_r2d2_study(benchmark, *, split_id: str):
    trial = r2d2_trial_protocol(benchmark, split_id=split_id)
    return _rs.study_spec(project_id='r2d2-2025-reproduction', study_id=f'r2d2-2025-{benchmark.benchmark_id}-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='r2d2_agent', kind='agent_method', implementation='r2d2', treatment='acl-2025-paper-protocol', capabilities=('model.generate',), configurations=R2D2_FIDELITY.phase_ids), models={'controller': _rs.study_model('model.r2d2.paper-era', prompt='r2d2.paper-protocol')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='task_success', scale='continuous', domain=benchmark.benchmark_id), _rs.scalar_measurement('agent_phase_count', schema_id='noetrium.measurement.count.v1', unit='phase', semantic_kind='agent_phase_count', scale='count', domain='r2d2')), trial=trial, repetitions=1, seeds=('paper-protocol',), limits=_rs.trial_budget('r2d2-2025-budget', max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_r2d2_study', 'r2d2_trial_protocol']
