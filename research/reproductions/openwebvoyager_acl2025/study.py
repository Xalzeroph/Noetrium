from __future__ import annotations
from research.reproductions import _support as _rs
from .benchmark import require_openwebvoyager_benchmark
from .fidelity import OPENWEBVOYAGER_FIDELITY
from .program import METHOD_SPEC

def openwebvoyager_trial_protocol(benchmark, *, split_id: str):
    selected = require_openwebvoyager_benchmark(benchmark, split_id=split_id)
    return _rs.study_protocol('openwebvoyager.2025.paper-protocol.v1', _rs.canonical_digest({'paper_uri': OPENWEBVOYAGER_FIDELITY.paper_uri, 'method_spec_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_id': benchmark.benchmark_id, 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'phase_ids': OPENWEBVOYAGER_FIDELITY.phase_ids}))

@_rs.study_factory('benchmark')
def build_openwebvoyager_study(benchmark, *, split_id: str):
    trial = openwebvoyager_trial_protocol(benchmark, split_id=split_id)
    return _rs.study_spec(project_id='openwebvoyager-2025-reproduction', study_id=f'openwebvoyager-2025-{benchmark.benchmark_id}-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='openwebvoyager_agent', kind='agent_method', implementation='openwebvoyager', treatment='acl-2025-paper-protocol', capabilities=('model.generate',), configurations=OPENWEBVOYAGER_FIDELITY.phase_ids), models={'controller': _rs.study_model('model.openwebvoyager.paper-era', prompt='openwebvoyager.paper-protocol')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='task_success', scale='continuous', domain=benchmark.benchmark_id), _rs.scalar_measurement('agent_phase_count', schema_id='noetrium.measurement.count.v1', unit='phase', semantic_kind='agent_phase_count', scale='count', domain='openwebvoyager')), trial=trial, repetitions=1, seeds=('paper-protocol',), limits=_rs.trial_budget('openwebvoyager-2025-budget', max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_openwebvoyager_study', 'openwebvoyager_trial_protocol']
