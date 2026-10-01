from __future__ import annotations
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.swe_bench import SWEBENCH_BENCHMARK_ID
from .fidelity import SWE_AGENT_PAPER_ERA_FIDELITY
SWE_AGENT_SWEBENCH_TRIAL_PROTOCOL = _rs.study_protocol('swe-agent.paper-era.swe-bench.v1', _rs.canonical_digest({'program_digest': _rs.canonical_digest(METHOD_SPEC), 'paper_era_commit': SWE_AGENT_PAPER_ERA_FIDELITY.audited_repository_commit, 'parser': SWE_AGENT_PAPER_ERA_FIDELITY.parser, 'file_window_lines': SWE_AGENT_PAPER_ERA_FIDELITY.file_window_lines, 'file_window_overlap': SWE_AGENT_PAPER_ERA_FIDELITY.file_window_overlap, 'history_observations_kept': SWE_AGENT_PAPER_ERA_FIDELITY.history_observations_kept, 'one_command_per_turn': SWE_AGENT_PAPER_ERA_FIDELITY.one_command_per_turn, 'wait_for_observation_after_command': SWE_AGENT_PAPER_ERA_FIDELITY.wait_for_observation_after_command}))

@_rs.study_factory('benchmark')
def build_swe_agent_swebench_study(benchmark, *, split_id: str):
    """Build a native SWE-agent/SWE-bench pressure protocol.

    The benchmark adapter owns exact task/harness/dataset identity. The method
    package owns ACI and model-view semantics. The platform owns isolated
    software execution, effect evidence, study expansion and measurement
    authority.
    """
    if benchmark.benchmark_id != SWEBENCH_BENCHMARK_ID:
        raise ValueError('SWE-agent study requires SWE-bench')
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError('SWE-agent SWE-bench study requires a non-empty split')
    return _rs.study_spec(project_id='swe-agent-paper-era-reproduction', study_id=f'swe-agent-paper-era-swe-bench-{split_id}', benchmark=benchmark, benchmark_split_id=split_id, method=_rs.study_participant(role='agent', kind='agent', implementation='swe-agent-paper-era', treatment='paper-era-0.7-aci', capabilities=('software.command',), configurations=('swe-agent.paper-era.prompt',)), models={'agent': _rs.study_model('model.swe-agent.agent', prompt='swe-agent.paper-era.prompt')}, measurements=(_rs.scalar_measurement('task_resolved', schema_id='noetrium.measurement.binary-scalar.v1', unit='ratio', semantic_kind='task_success', scale='binary', domain='swe-bench'), _rs.scalar_measurement('turn_count', schema_id='noetrium.measurement.count.v1', unit='turn', semantic_kind='resource_usage', scale='count', domain='swe-bench'), _rs.scalar_measurement('command_count', schema_id='noetrium.measurement.count.v1', unit='command', semantic_kind='tool_usage', scale='count', domain='swe-bench')), trial=SWE_AGENT_SWEBENCH_TRIAL_PROTOCOL, repetitions=1, seeds=('0',), limits=_rs.trial_budget('swe-agent-paper-era-host-safety', max_steps=2048, max_turns=512, max_model_calls=512, max_working_seconds=3600.0), replay_level='observational')
__all__ = ['SWE_AGENT_SWEBENCH_TRIAL_PROTOCOL', 'build_swe_agent_swebench_study']
