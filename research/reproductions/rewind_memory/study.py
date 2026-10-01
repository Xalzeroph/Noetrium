from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.moviechat_1k import MOVIECHAT_1K_BENCHMARK_ID, MOVIECHAT_1K_TEST_SPLIT, MOVIECHAT_1K_VIDEO_COUNT
from .fidelity import REWIND_REFERENCE_FIDELITY

def rewind_cvpr2025_trial_protocol(benchmark):
    if benchmark.benchmark_id != MOVIECHAT_1K_BENCHMARK_ID:
        raise ValueError('ReWind CVPR 2025 protocol requires MovieChat-1K')
    selected = benchmark.selected_tasks(MOVIECHAT_1K_TEST_SPLIT)
    if len(selected) != MOVIECHAT_1K_VIDEO_COUNT:
        raise ValueError('ReWind CVPR 2025 protocol requires 1000-video test cut')
    fidelity = REWIND_REFERENCE_FIDELITY
    return _rs.study_protocol('rewind.cvpr2025.moviechat-1k.v1', _rs.canonical_digest({'memory_program_digest': _rs.canonical_digest(METHOD_SPEC), 'publication_revision': fidelity.source_revision, 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_split_id': MOVIECHAT_1K_TEST_SPLIT, 'video_task_ids': tuple((row.task_id for row in selected)), 'video_count': MOVIECHAT_1K_VIDEO_COUNT, 'sampling_fps': fidelity.sampling_fps, 'perceiver_layers': fidelity.perceiver_layers, 'read_queries': fidelity.read_query_count, 'write_queries': fidelity.write_query_count, 'memory_tokens_per_frame': fidelity.memory_tokens_per_frame, 'dfs_instruction_selection_count': fidelity.dfs_instruction_selection_count, 'dfs_final_frame_count': fidelity.dfs_final_frame_count, 'dfs_selected_frame_tokens': fidelity.dfs_selected_frame_tokens, 'dfs_clustering': fidelity.dfs_clustering, 'execution_semantics': 'full-video-read-perceive-write-before-dfs'}))

@_rs.study_factory('benchmark')
def build_rewind_cvpr2025_study(benchmark):
    fidelity = REWIND_REFERENCE_FIDELITY
    protocol = rewind_cvpr2025_trial_protocol(benchmark)
    return _rs.study_spec(project_id='rewind-cvpr-2025-reproduction', study_id='rewind-cvpr-2025-moviechat-1k', benchmark=benchmark, benchmark_split_id=MOVIECHAT_1K_TEST_SPLIT, method=_rs.study_participant(role='instructed_multimodal_memory_model', kind='method', implementation='rewind', treatment='cvpr-2025-camera-ready', capabilities=('memory.tensor.read', 'memory.tensor.write', 'model.multimodal.generate', 'evaluation.semantic-qa-judge'), configurations=('rewind.read-perceive-write', 'rewind.memory-2-tokens-per-frame', 'rewind.dfs-64-to-8', 'rewind.selected-frame-32-tokens', 'rewind.1fps')), models={'multimodal': _rs.study_model('model.rewind.llama2-7b-paper-described', prompt='rewind.long-video-qa.prompt'), 'judge': _rs.study_model('model.moviechat.paper-era-qa-judge', prompt='moviechat.qa-evaluation.prompt')}, measurements=(_rs.scalar_measurement('global_accuracy', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='semantic_qa_accuracy', scale='continuous', domain='moviechat_global'), _rs.scalar_measurement('breakpoint_accuracy', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='semantic_qa_accuracy', scale='continuous', domain='moviechat_breakpoint'), _rs.scalar_measurement('global_semantic_score', schema_id='noetrium.measurement.score.v1', unit='score_0_to_5', semantic_kind='semantic_qa_match_score', scale='continuous', domain='moviechat_global'), _rs.scalar_measurement('breakpoint_semantic_score', schema_id='noetrium.measurement.score.v1', unit='score_0_to_5', semantic_kind='semantic_qa_match_score', scale='continuous', domain='moviechat_breakpoint'), _rs.scalar_measurement('memory_tokens_per_frame', schema_id='noetrium.measurement.count.v1', unit='token', semantic_kind='memory_token_density', scale='count', domain='rewind'), _rs.scalar_measurement('dfs_selected_frame_count', schema_id='noetrium.measurement.count.v1', unit='frame', semantic_kind='high_resolution_frame_count', scale='count', domain='rewind')), trial=protocol, repetitions=1, seeds=('paper-described-evaluation',), limits=_rs.trial_budget('rewind-cvpr2025-moviechat-1k-budget', max_steps=4096, max_turns=32, max_model_calls=64, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_rewind_cvpr2025_study', 'rewind_cvpr2025_trial_protocol']
