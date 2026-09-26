from __future__ import annotations
from research.reproductions._support import canonical_digest
from .program import METHOD_SPEC
from research.reproductions import _support as _rs
from research.benchmarks.robocodegen_37 import ROBOCODEGEN_ALL_SPLIT, ROBOCODEGEN_BENCHMARK_ID, ROBOCODEGEN_NOTEBOOK_BLOB_SHA, ROBOCODEGEN_PROTOCOL_DIGEST, ROBOCODEGEN_TASK_COUNT, ROBOCODEGEN_TESTS_PER_TASK
from .source import CODE_AS_POLICIES_AUDITED_COMMIT

def code_as_policies_icra2023_robocodegen_protocol(benchmark):
    if benchmark.benchmark_id != ROBOCODEGEN_BENCHMARK_ID:
        raise ValueError('Code as Policies study requires RoboCodeGen 37')
    selected = benchmark.selected_tasks(ROBOCODEGEN_ALL_SPLIT)
    if len(selected) != ROBOCODEGEN_TASK_COUNT:
        raise ValueError('Code as Policies study requires all 37 tasks')
    return _rs.study_protocol('code-as-policies.icra2023.robocodegen-37.v1', _rs.canonical_digest({'source_commit': CODE_AS_POLICIES_AUDITED_COMMIT, 'notebook_blob_sha': ROBOCODEGEN_NOTEBOOK_BLOB_SHA, 'method_spec_digest': canonical_digest(METHOD_SPEC), 'benchmark_cut_digest': benchmark.cut_digest, 'benchmark_protocol_digest': ROBOCODEGEN_PROTOCOL_DIGEST, 'benchmark_split_id': ROBOCODEGEN_ALL_SPLIT, 'task_ids': tuple((row.task_id for row in selected)), 'tests_per_task': ROBOCODEGEN_TESTS_PER_TASK, 'test_seed': 'paper-notebook-unfixed', 'model': 'code-davinci-002', 'generation': 'hierarchical-code-gen', 'prompt': 'hierarchical', 'temperature': 0.0, 'max_tokens': 512}))

@_rs.study_factory('benchmark')
def build_code_as_policies_icra2023_robocodegen_study(benchmark):
    protocol = code_as_policies_icra2023_robocodegen_protocol(benchmark)
    return _rs.study_spec(project_id='code-as-policies-icra-2023-reproduction', study_id='code-as-policies-icra-2023-robocodegen-37', benchmark=benchmark, benchmark_split_id=ROBOCODEGEN_ALL_SPLIT, method=_rs.study_participant(role='hierarchical_language_model_program_generator', kind='method', implementation='code-as-policies', treatment='hierarchical-code-gen-hierarchical-prompt', capabilities=('model.generate', 'environment.software'), configurations=('code-as-policies.recursive-helper-synthesis', 'code-as-policies.hierarchical-prompt', 'code-as-policies.paper-era-codex')), models={'synthesizer': _rs.study_model('model.openai.code-davinci-002-paper-era', prompt='code-as-policies.robocodegen.hierarchical')}, measurements=(_rs.scalar_measurement('task_success', schema_id='noetrium.measurement.ratio.v1', unit='ratio', semantic_kind='reference_function_equivalence', scale='binary', domain='robocodegen_37'), _rs.scalar_measurement('generated_helper_count', schema_id='noetrium.measurement.count.v1', unit='helper', semantic_kind='recursive_generated_helper_count', scale='count', domain='robocodegen_37')), trial=protocol, repetitions=1, seeds=('paper-notebook-random-seed-unfixed',), limits=_rs.trial_budget('code-as-policies-robocodegen-37-budget', max_steps=256, max_turns=64, max_model_calls=256, max_working_seconds=600.0), replay_level='observational', repetition_timeout_seconds=600.0)
__all__ = ['build_code_as_policies_icra2023_robocodegen_study', 'code_as_policies_icra2023_robocodegen_protocol']
