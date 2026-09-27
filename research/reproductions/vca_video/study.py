from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.egoschema import EGOSCHEMA_BENCHMARK_ID, EGOSCHEMA_PUBLIC_COUNT, EGOSCHEMA_PUBLIC_SPLIT
from .fidelity import VCA_REFERENCE_FIDELITY
from .program import VCA_EXECUTION_SAFETY_ROUNDS

def vca_egoschema_trial_protocol(benchmark, *, sampling_frame_number: int):
    if benchmark.benchmark_id != EGOSCHEMA_BENCHMARK_ID:
        raise ValueError('VCA study requires EgoSchema')
    selected = benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)
    if len(selected) != EGOSCHEMA_PUBLIC_COUNT:
        raise ValueError('VCA EgoSchema reproduction requires the 500-task public cut')
    if type(sampling_frame_number) is not int or sampling_frame_number < 1:
        raise ValueError('VCA sampling_frame_number must be positive')
    return _rs.study_protocol('vca.iccv2025.egoschema-public.paper-authoritative.v1', _rs.canonical_digest({'method_program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': EGOSCHEMA_PUBLIC_SPLIT, 'task_ids': tuple((row.task_id for row in selected)), 'sampling_frame_number': sampling_frame_number, 'memory_frames': VCA_REFERENCE_FIDELITY.egoschema_memory_frames, 'shared_reward_exploration_model': True, 'temperature': VCA_REFERENCE_FIDELITY.temperature, 'tree_search': True, 'reward_history_conditioning': True, 'memory_eviction': 'lowest_relevance_first', 'segment_choice': 'model_decision_reward_guided_non_greedy'}))

@_rs.study_factory('benchmark')
def build_vca_egoschema_public_study(benchmark, *, sampling_frame_number: int=VCA_REFERENCE_FIDELITY.egoschema_memory_frames, max_rounds: int=32):
    if type(max_rounds) is not int or not 1 <= max_rounds <= VCA_EXECUTION_SAFETY_ROUNDS:
        raise ValueError('VCA max_rounds is outside the reproduction safety ceiling')
    protocol = vca_egoschema_trial_protocol(benchmark, sampling_frame_number=sampling_frame_number)
    shared_requirement = 'model.vca.gpt4o-august-2024'
    return _rs.study_spec(project_id='vca-iccv-2025-reproduction', study_id='vca-iccv-2025-egoschema-public', benchmark=benchmark, benchmark_split_id=EGOSCHEMA_PUBLIC_SPLIT, method=_rs.study_participant(role='curiosity_driven_video_agent', kind='agent_method', implementation='vca-video-curious-agent', treatment='iccv-2025-paper-authoritative', capabilities=('artifact.video.decode', 'model.multimodal.generate'), configurations=('vca.segment-tree', 'vca.self-generated-intrinsic-reward', 'vca.fixed-relevance-memory-8')), models={'vca.shared-vlm.reward': _rs.study_model(shared_requirement, prompt='vca.iccv2025.reward-prompt'), 'vca.shared-vlm.exploration': _rs.study_model(shared_requirement, prompt='vca.iccv2025.exploration-prompt')}, measurements=(_rs.scalar_measurement('multiple_choice_accuracy', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='multiple_choice_accuracy', scale='continuous', domain='egoschema'), _rs.scalar_measurement('observed_frame_count', schema_id='noetrium.measurement.count.v1', unit='frame', semantic_kind='observed_frame_count', scale='count', domain='vca'), _rs.scalar_measurement('exploration_rounds', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='exploration_round_count', scale='count', domain='vca')), trial=protocol, repetitions=1, seeds=('paper-service-default',), limits=_rs.trial_budget('vca-egoschema-paper-authoritative-safety', max_steps=VCA_EXECUTION_SAFETY_ROUNDS * 8 + 1, max_turns=max_rounds * 2, max_model_calls=max_rounds * 2, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_vca_egoschema_public_study', 'vca_egoschema_trial_protocol']
