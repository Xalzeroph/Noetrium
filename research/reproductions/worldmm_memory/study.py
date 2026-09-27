from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.egolifeqa import EGOLIFEQA_BENCHMARK_ID
from .fidelity import WORLDMM_REFERENCE_FIDELITY
from .source import WORLDMM_INITIAL_RELEASE_COMMIT

def worldmm_egolifeqa_trial_protocol(benchmark, *, subject_id: str='A1_JAKE'):
    if benchmark.benchmark_id != EGOLIFEQA_BENCHMARK_ID:
        raise ValueError('WorldMM study requires EgoLifeQA')
    split_id = f'subject:{subject_id}'
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError(f'WorldMM EgoLifeQA split has no tasks: {split_id}')
    f = WORLDMM_REFERENCE_FIDELITY
    return _rs.study_protocol(f'worldmm.cvpr2026.egolifeqa.{subject_id}.v1', _rs.canonical_digest({'source_commit': WORLDMM_INITIAL_RELEASE_COMMIT, 'method_program_digest': _rs.canonical_digest(METHOD_SPEC), 'memory_program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'memory_types': f.memory_types, 'episodic_granularities': f.episodic_granularities, 'retrieval_top_k': (f.episodic_public_top_k, f.semantic_public_top_k, f.visual_public_top_k), 'max_retrieval_rounds': f.max_retrieval_rounds, 'max_reasoning_errors': f.max_reasoning_errors, 'visual_fps': f.visual_frame_fps, 'visual_max_frames': f.visual_max_frames, 'retriever_model': 'gpt-5-mini', 'respond_model': 'gpt-5', 'evaluation': 'worldmm-source-compatible-mcq'}))

@_rs.study_factory('benchmark')
def build_worldmm_egolifeqa_study(benchmark, *, subject_id: str='A1_JAKE'):
    f = WORLDMM_REFERENCE_FIDELITY
    split_id = f'subject:{subject_id}'
    trial = worldmm_egolifeqa_trial_protocol(benchmark, subject_id=subject_id)
    return _rs.study_spec(project_id='worldmm-cvpr-2026-reproduction', study_id=f'worldmm-cvpr-2026-egolifeqa-{subject_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='dynamic_multimodal_memory_agent', kind='method', implementation='worldmm-memory', treatment='initial-public-executable', capabilities=('memory.worldmm.index', 'memory.worldmm.retrieve', 'model.worldmm.reasoning', 'model.worldmm.answer', 'artifact.video.decode'), configurations=('worldmm.episodic-multiscale', 'worldmm.semantic-ppr', 'worldmm.visual-memory', 'worldmm.adaptive-retrieval-5round')), models={'retriever': _rs.study_model('model.worldmm.gpt-5-mini', prompt='worldmm.memory-reasoning.prompt'), 'responder': _rs.study_model('model.worldmm.gpt-5', prompt='worldmm.qa-egolife.prompt')}, measurements=(_rs.scalar_measurement('multiple_choice_accuracy', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='multiple_choice_accuracy', scale='continuous', domain='egolifeqa'), _rs.scalar_measurement('retrieval_rounds', schema_id='noetrium.measurement.count.v1', unit='round', semantic_kind='retrieval_rounds', scale='count', domain='worldmm'), _rs.scalar_measurement('reasoning_errors', schema_id='noetrium.measurement.count.v1', unit='error', semantic_kind='reasoning_errors', scale='count', domain='worldmm'), _rs.scalar_measurement('retrieved_item_count', schema_id='noetrium.measurement.count.v1', unit='item', semantic_kind='retrieved_item_count', scale='count', domain='worldmm')), trial=trial, repetitions=1, seeds=('paper-default',), limits=_rs.trial_budget(f'worldmm-cvpr2026-egolifeqa-{subject_id}-budget', max_steps=64, max_turns=f.max_retrieval_rounds, max_model_calls=128, max_working_seconds=3600.0), replay_level='observational', repetition_timeout_seconds=3600.0)
__all__ = ['build_worldmm_egolifeqa_study', 'worldmm_egolifeqa_trial_protocol']
