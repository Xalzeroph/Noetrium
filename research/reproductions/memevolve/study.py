from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.memoryarena import MEMORYARENA_BENCHMARK_ID
from .fidelity import MEMEVOLVE_FIDELITY
_SUPPORTED_BENCHMARKS = frozenset({MEMORYARENA_BENCHMARK_ID, 'evomembench'})

def memevolve_trial_protocol(benchmark, *, split_id: str):
    f = MEMEVOLVE_FIDELITY
    if benchmark.benchmark_id not in _SUPPORTED_BENCHMARKS:
        raise ValueError('MemEvolve study requires MemoryArena or EvoMemBench')
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError('MemEvolve study requires a non-empty benchmark split')
    return _rs.study_protocol(f'memevolve.{benchmark.benchmark_id}.meta-evolution.v1', _rs.canonical_digest({'program_digest': canonical_digest(METHOD_SPEC), 'benchmark_id': benchmark.benchmark_id, 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'source_commit': f.audited_code_commit, 'manual_phases': f.manual_phases, 'round_process': f.round_process, 'candidate_generation_independent': f.candidate_generation_independent, 'same_task_tournament_required': f.same_task_tournament_required, 'winner_becomes_next_round_base': f.winner_becomes_next_round_base}))

@_rs.study_factory('benchmark')
def build_memevolve_study(benchmark, *, split_id: str):
    protocol = memevolve_trial_protocol(benchmark, split_id=split_id)
    domain = benchmark.benchmark_id
    return _rs.study_spec(project_id='memevolve-reproduction', study_id=f'memevolve-{domain}-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='meta_memory_search', kind='memory_meta_evolution', implementation='memevolve', treatment='dual-content-architecture-evolution', capabilities=('workbench.candidate-program.execute',), configurations=('memevolve.manual-evolution', 'memevolve.same-task-tournament', 'memevolve.extended-task-finals')), models={'memevolve.analyzer': _rs.study_model('model.memevolve.meta', prompt='memevolve.analyze-trajectories'), 'memevolve.memory-generator': _rs.study_model('model.memevolve.meta', prompt='memevolve.generate-memory-system'), 'memevolve.implementation-generator': _rs.study_model('model.memevolve.meta', prompt='memevolve.create-implementation')}, measurements=(_rs.scalar_measurement('memory_score', schema_id='noetrium.measurement.scalar.v1', unit='score', semantic_kind='memory_system_quality', scale='continuous', domain=domain), _rs.scalar_measurement('round_count', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='meta_evolution_round_count', scale='count', domain=domain), _rs.scalar_measurement('candidate_execution_count', schema_id='noetrium.measurement.count.v1', unit='execution', semantic_kind='candidate_evaluation_usage', scale='count', domain=domain)), trial=protocol, repetitions=1, seeds=('0',), limits=_rs.trial_budget('memevolve-host-safety', max_steps=8192, max_turns=2048, max_model_calls=2048, max_working_seconds=7200.0), replay_level='observational')
__all__ = ['build_memevolve_study', 'memevolve_trial_protocol']
