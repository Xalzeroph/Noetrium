from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.vima_bench import VIMA_BENCHMARK_ID, VIMA_CAMERA_READY_EXECUTABLE_SEED, VIMA_PARTITION_TASKS
from .fidelity import VIMA_EXECUTION_SAFETY_LIMIT, VIMA_REFERENCE_FIDELITY
from .source import VIMA_BENCH_AUDITED_COMMIT, VIMA_POLICY_AUDITED_COMMIT

def vima_icml2023_trial_protocol(benchmark):
    if benchmark.benchmark_id != VIMA_BENCHMARK_ID:
        raise ValueError('VIMA protocol requires VIMA-Bench')
    if len(benchmark.selected_tasks('all')) != 43:
        raise ValueError('VIMA protocol requires 43 task-partition cells')
    return _rs.study_protocol('vima.icml2023.camera-ready.v1', _rs.canonical_digest({'policy_source_commit': VIMA_POLICY_AUDITED_COMMIT, 'benchmark_source_commit': VIMA_BENCH_AUDITED_COMMIT, 'benchmark_cut_digest': benchmark.cut_digest, 'method_spec_digest': canonical_digest(METHOD_SPEC), 'partition_tasks': VIMA_PARTITION_TASKS, 'camera_ready_executable_seed': VIMA_CAMERA_READY_EXECUTABLE_SEED, 'paper_success_semantics': 'binary-no-partial-reward', 'paper_final_metric': 'mean-success-rate-over-evaluated-tasks', 'episode_bonus_steps': VIMA_REFERENCE_FIDELITY.episode_bonus_steps, 'prompt_semantics': 'interleaved-text-object-tokens', 'observation_semantics': 'object-centric-front-top-ee', 'action_semantics': 'two-pose-six-component-discretized'}))

@_rs.study_factory('benchmark')
def build_vima_icml2023_study(benchmark):
    protocol = vima_icml2023_trial_protocol(benchmark)
    return _rs.study_spec(project_id='vima-icml-2023-reproduction', study_id='vima-icml-2023-vima-bench-camera-ready', benchmark=benchmark, benchmark_split_id='all', method=_rs.study_participant(role='multimodal_embodied_policy', kind='method', implementation='vima', treatment='icml-2023-camera-ready', capabilities=('environment.embodied', 'model.multimodal.policy', 'artifact.tensor.read', 'artifact.tensor.write'), configurations=('vima.object-centric', 'vima.cross-attention', 'vima.autoregressive-history', 'vima.position-bins-50x100', 'vima.rotation-bins-50x50x50x50')), models={'policy': _rs.study_model('model.vima.camera-ready-policy', prompt='vima.multimodal-prompt'), 'prompt_encoder': _rs.study_model('model.vima.t5-base-frozen', prompt='vima.prompt-encoder')}, measurements=(_rs.scalar_measurement('episode_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='binary_task_success', scale='binary', domain='vima_bench'), _rs.scalar_measurement('episode_steps', schema_id='noetrium.measurement.count.v1', unit='environment_step', semantic_kind='embodied_episode_length', scale='count', domain='vima_bench'), _rs.scalar_measurement('partition_success_rate', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='mean_binary_success_by_generalization_level', scale='continuous', domain='vima_bench')), trial=protocol, repetitions=1, seeds=(str(VIMA_CAMERA_READY_EXECUTABLE_SEED),), limits=_rs.trial_budget('vima-icml2023-camera-ready-budget', max_steps=VIMA_EXECUTION_SAFETY_LIMIT, max_turns=VIMA_EXECUTION_SAFETY_LIMIT, max_model_calls=VIMA_EXECUTION_SAFETY_LIMIT, max_working_seconds=1800.0), replay_level='observational', repetition_timeout_seconds=1800.0)
__all__ = ['build_vima_icml2023_study', 'vima_icml2023_trial_protocol']
