from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionDelta,
    ReproductionDeltaKind,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package='camel_role_playing',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='camel',
        title='CAMEL: Communicative Agents for Mind Exploration of Large Language Model Society',
        paper_uri='https://proceedings.neurips.cc/paper_files/paper/2023/file/a3621ee907def47c1b952ade25c67698-Paper-Conference.pdf',
        year=2023,
        paper_revision='NeurIPS 2023',
    ),
    catalog=ReproductionCatalog(
        domains=('multi-agent',),
        families=('multi_agent', 'role_playing', 'communication', 'inception_prompting'),
        priority=1,
        benchmark_ids=('camel-ai-society',),
        platform_pressure=(
            'execution/workflow',
            'participant/agent',
            'model/request',
            'experimentation/study',
            'observability/telemetry',
        ),
        method_owned=(
            'inception prompting',
            'assistant-user role semantics',
            'task specification and task planning',
            'independent role histories',
            'alternating dialogue and termination protocol',
        ),
        platform_owned=(
            'participant lifecycle',
            'named model-role binding',
            'model invocation',
            'model-visible history projection',
            'transcript evidence',
            'evaluation isolation',
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/camel_role_playing/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/camel_role_playing/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/camel_role_playing/study.py',
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id='camel_ai_society_human_win',
            metric_id='human_pairwise_win_rate',
            value=76.3,
            qualifiers={'condition': 'CAMEL', 'judge': 'human', 'task_sample_size': 100, 'unit': 'percent'},
        ),
        ReportedResult(
            claim_id='single_shot_ai_society_human_win',
            metric_id='human_pairwise_win_rate',
            value=10.4,
            qualifiers={'condition': 'single_shot_gpt3.5', 'judge': 'human', 'task_sample_size': 100, 'unit': 'percent'},
        ),
        ReportedResult(
            claim_id='camel_ai_society_gpt4_win',
            metric_id='gpt4_pairwise_win_rate',
            value=73.0,
            qualifiers={'condition': 'CAMEL', 'judge': 'gpt-4', 'task_sample_size': 100, 'unit': 'percent'},
        ),
        ReportedResult(
            claim_id='single_shot_ai_society_gpt4_win',
            metric_id='gpt4_pairwise_win_rate',
            value=23.0,
            qualifiers={'condition': 'single_shot_gpt3.5', 'judge': 'gpt-4', 'task_sample_size': 100, 'unit': 'percent'},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='gpt3.5_single_shot',
            description='paper single-shot GPT-3.5-Turbo response used for pairwise agent evaluation',
            qualifiers={'task_sample_size': 100},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='the exact identities of the paper-randomized 100 AI-Society evaluation tasks are not published in the paper/source cut and must be supplied as an immutable benchmark cut rather than guessed',
        ),
    ),
    blockers=(
        'exact paper-randomized 100 AI-Society evaluation task ids are not publicly frozen',
        'historical GPT-3.5-Turbo and GPT-4 service revisions are not content-addressable model artifacts',
        'human pairwise rater assignment/order metadata is not fully reconstructable from the released source cut',
    ),
    evidence_refs=(),
    scientific_tests=(
        'tests/test_scientific_camel_role_playing_fidelity_v1.py',
        'tests/test_scientific_camel_method_program_v1.py',
        'tests/test_scientific_camel_ai_society_benchmark_v1.py',
    ),
)

__all__ = ["REPRODUCTION"]
