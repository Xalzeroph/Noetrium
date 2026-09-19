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
    package='saycan',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='saycan',
        title='Do As I Can, Not As I Say: Grounding Language in Robotic Affordances',
        paper_uri='https://proceedings.mlr.press/v205/ichter23a.html',
        year=2022,
        paper_revision=(
            "CoRL 2022 / official released notebook commit "
            "8c56e5dfc49613a57b80d6cfa2c9d6605cc08d10"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=('embodied-robotics', 'planning-search'),
        families=('embodied', 'planning', 'affordance', 'language_grounding'),
        priority=1,
        benchmark_ids=('saycan-101',),
        platform_pressure=('participant/method', 'environment/embodied', 'model/request', 'participant/capability', 'experimentation/study'),
        method_owned=(
            'language-score and affordance composition',
            'frozen-affordance recursive planning loop',
            'done() termination semantics',
            'plan-first then skill-execution ordering',
            'skill selection policy',
        ),
        platform_owned=(
            'MethodProgram host and journal authority',
            'model invocation',
            'embodied skill capability execution',
            'effect evidence',
            'evaluation',
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('benchmark'),
            path='research/reproductions/saycan/benchmark.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/saycan/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/saycan/policy.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/saycan/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/saycan/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/saycan/source.py',
        ),
    ),
    primary_executable='research/reproductions/saycan/program.py',
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('substitution'),
            description=(
                'The public Google Research notebook demonstrates SayCan with '
                'ViLD-derived binary affordances and CLIPort skill execution in '
                'place of the full paper robot value-function/policy stack. '
                'The reproduction preserves that released executable lane and '
                'does not relabel it as matched full-paper robot execution.'
            ),
        ),
    ),
    blockers=(
        'Matched CoRL robot-result reproduction still requires immutable '
        'paper-era robot skill/value-function artifacts and the evaluated task '
        'scene/instruction cuts.',
        'The historical hosted language-model serving snapshot used by the '
        'paper is not an immutable public model artifact.',
        'Formal execution still requires the official SayCan v0 TSV bytes to '
        'be materialized under Artifact authority and an eligible human-majority '
        'evaluation provider for plan/execution judgments.',
    ),
    evidence_refs=(),
    scientific_tests=(
        'tests/test_scientific_saycan_v1.py',
        'tests/test_scientific_saycan_benchmark_study_v1.py',
    ),
)

__all__ = ["REPRODUCTION"]
