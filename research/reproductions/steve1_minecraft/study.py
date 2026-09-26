from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.steve1_paper_prompts import STEVE1_ALL_SPLIT, STEVE1_PAPER_PROMPT_NAMES, STEVE1_PAPER_PROMPTS_BENCHMARK_ID, STEVE1_PAPER_PROMPTS_BLOB_SHA, STEVE1_PAPER_PROMPTS_COMMIT, STEVE1_RELEASED_CELL_COUNT
from .fidelity import STEVE1_REFERENCE_FIDELITY

def steve1_neurips2023_prompt_trial_protocol(benchmark):
    if benchmark.benchmark_id != STEVE1_PAPER_PROMPTS_BENCHMARK_ID:
        raise ValueError('STEVE-1 protocol requires released paper-prompt benchmark')
    selected = benchmark.selected_tasks(STEVE1_ALL_SPLIT)
    if len(selected) != STEVE1_RELEASED_CELL_COUNT:
        raise ValueError('STEVE-1 protocol requires 22 released prompt cells')
    fidelity = STEVE1_REFERENCE_FIDELITY
    return _rs.study_protocol('steve1.neurips2023.released-paper-prompts.v1', _rs.canonical_digest({'source_commit': STEVE1_PAPER_PROMPTS_COMMIT, 'paper_prompts_blob_sha': STEVE1_PAPER_PROMPTS_BLOB_SHA, 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_split_id': STEVE1_ALL_SPLIT, 'task_ids': tuple((row.task_id for row in selected)), 'semantic_prompt_names': STEVE1_PAPER_PROMPT_NAMES, 'method_spec_digest': canonical_digest(METHOD_SPEC), 'gameplay_length': fidelity.released_runner_gameplay_length, 'fps': fidelity.runner_fps, 'text_cond_scale': fidelity.text_cond_scale, 'visual_cond_scale': fidelity.visual_cond_scale, 'stochastic_policy_sampling': fidelity.stochastic_policy_sampling, 'classifier_free_guidance': fidelity.classifier_free_guidance, 'programmatic_metrics': ('log', 'dirt', 'seed', 'travel_dist'), 'runner_seed': 'none-in-released-paper-video-runner', 'paper_13_task_claim_identity': 'not-released'}))

@_rs.study_factory('benchmark')
def build_steve1_neurips2023_prompt_study(benchmark):
    protocol = steve1_neurips2023_prompt_trial_protocol(benchmark)
    fidelity = STEVE1_REFERENCE_FIDELITY
    return _rs.study_spec(project_id='steve1-neurips-2023-reproduction', study_id='steve1-neurips-2023-released-paper-prompts', benchmark=benchmark, benchmark_split_id=STEVE1_ALL_SPLIT, method=_rs.study_participant(role='minecraft_vision_language_controller', kind='method', implementation='steve-1', treatment='neurips-2023-released-paper-prompts', capabilities=('environment.minecraft.raw-control', 'model.multimodal.policy', 'artifact.tensor.read', 'artifact.tensor.write'), configurations=('steve1.mineclip-latent-goal', 'steve1.classifier-free-guidance', 'steve1.recurrent-vpt-controller', 'steve1.text-cond-scale-6', 'steve1.visual-cond-scale-7')), models={'controller': _rs.study_model('model.steve1.paper-release-vpt', prompt='steve1.goal-conditioned-control'), 'goal_encoder': _rs.study_model('model.steve1.paper-release-mineclip-prior', prompt='steve1.text-or-visual-goal')}, measurements=(_rs.scalar_measurement('max_log_inventory_count', schema_id='noetrium.measurement.count.v1', unit='item', semantic_kind='steve1_programmatic_inventory_max', scale='count', domain='log'), _rs.scalar_measurement('max_dirt_inventory_count', schema_id='noetrium.measurement.count.v1', unit='item', semantic_kind='steve1_programmatic_inventory_max', scale='count', domain='dirt'), _rs.scalar_measurement('max_seed_inventory_count', schema_id='noetrium.measurement.count.v1', unit='item', semantic_kind='steve1_programmatic_inventory_max', scale='count', domain='seed'), _rs.scalar_measurement('max_travel_distance_blocks', schema_id='noetrium.measurement.distance.v1', unit='minecraft_block', semantic_kind='steve1_programmatic_horizontal_travel', scale='continuous', domain='minecraft'), _rs.scalar_measurement('episode_steps', schema_id='noetrium.measurement.count.v1', unit='environment_step', semantic_kind='minecraft_episode_length', scale='count', domain='steve1')), trial=protocol, repetitions=1, seeds=('released-runner-unseeded',), limits=_rs.trial_budget('steve1-neurips2023-released-prompt-budget', max_steps=fidelity.released_runner_gameplay_length, max_turns=fidelity.released_runner_gameplay_length, max_model_calls=fidelity.released_runner_gameplay_length + 1, max_working_seconds=1800.0), replay_level='observational', repetition_timeout_seconds=1800.0)
__all__ = ['build_steve1_neurips2023_prompt_study', 'steve1_neurips2023_prompt_trial_protocol']
