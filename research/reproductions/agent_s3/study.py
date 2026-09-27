from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.osworld import OSWORLD_BENCHMARK_ID
from .fidelity import AGENT_S3_FIDELITY

def agent_s3_osworld_trial_protocol(benchmark, *, split_id: str):
    f = AGENT_S3_FIDELITY
    if benchmark.benchmark_id != OSWORLD_BENCHMARK_ID:
        raise ValueError('Agent S3 study requires OSWorld')
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError('Agent S3 OSWorld study requires a non-empty split')
    return _rs.study_protocol('agent-s3.osworld.v0.3.2.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'split_id': split_id, 'task_ids': tuple((row.task_id for row in selected)), 'release': f.release, 'release_commit': f.release_commit, 'reflection_enabled': f.default_reflection_enabled, 'max_trajectory_length': f.default_max_trajectory_length, 'action_interface': f.action_interface, 'one_action_per_turn': f.one_action_per_turn, 'runtime_tool_creation': f.runtime_tool_creation, 'code_agent_budget': f.code_agent_budget, 'paper_default_step_limit': f.default_step_limit, 'paper_default_cost_limit': f.default_cost_limit}))

@_rs.study_factory('benchmark')
def build_agent_s3_osworld_study(benchmark, *, split_id: str):
    protocol = agent_s3_osworld_trial_protocol(benchmark, split_id=split_id)
    return _rs.study_spec(project_id='agent-s3-reproduction', study_id=f'agent-s3-osworld-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='agent', kind='gui_agent_method', implementation='agent-s3', treatment='v0.3.2-single-worker-reflection', capabilities=('environment.act',), configurations=('agent-s3.reflection', 'agent-s3.context-projection', 'agent-s3.runtime-tool-creation')), models={'agent-s3.reflection': _rs.study_model('model.agent-s3.vlm', prompt='agent-s3.reflection.v0.3.2'), 'agent-s3.worker': _rs.study_model('model.agent-s3.vlm', prompt='agent-s3.worker.v0.3.2'), 'agent-s3.code-agent': _rs.study_model('model.agent-s3.code', prompt='agent-s3.code-agent.v0.3.2')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='task_success', scale='binary', domain='osworld'), _rs.scalar_measurement('model_call_count', schema_id='noetrium.measurement.count.v1', unit='call', semantic_kind='model_usage', scale='count', domain='osworld'), _rs.scalar_measurement('device_action_count', schema_id='noetrium.measurement.count.v1', unit='action', semantic_kind='tool_usage', scale='count', domain='osworld'), _rs.scalar_measurement('iteration_count', schema_id='noetrium.measurement.count.v1', unit='iteration', semantic_kind='resource_usage', scale='count', domain='osworld')), trial=protocol, repetitions=1, seeds=('0',), limits=_rs.trial_budget('agent-s3-v0.3.2-host-safety', max_steps=4096, max_turns=256, max_model_calls=532, max_working_seconds=3600.0), replay_level='observational')
__all__ = ['agent_s3_osworld_trial_protocol', 'build_agent_s3_osworld_study']
