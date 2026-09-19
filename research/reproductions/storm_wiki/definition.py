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
    package='storm_wiki',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='storm',
        title='Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models',
        paper_uri='https://aclanthology.org/2024.naacl-long.347/',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('scientific-research', 'retrieval-knowledge'),
        families=('research_agent', 'retrieval', 'question_asking', 'citation_grounding'),
        priority=1,
        benchmark_ids=('freshwiki',),
        platform_pressure=('participant/method', 'data/query', 'model/request', 'execution', 'artifact/lineage', 'experimentation/study'),
        method_owned=('perspective-guided question asking', 'simulated expert conversation', 'four-stage citation-grounded article pipeline'),
        platform_owned=('model invocation', 'retrieval transport', 'bounded stage execution', 'artifact lineage', 'evidence and evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/storm_wiki/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/storm_wiki/pipeline.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/storm_wiki/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/storm_wiki/study.py',
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id='storm_editor_organized_gain',
            metric_id='organized_absolute_gain_percentage_points',
            value=25.0,
            qualifiers={'comparison': 'outline-driven retrieval-augmented baseline'},
        ),
        ReportedResult(
            claim_id='storm_editor_breadth_gain',
            metric_id='broad_coverage_absolute_gain_percentage_points',
            value=10.0,
            qualifiers={'comparison': 'outline-driven retrieval-augmented baseline'},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='outline-driven-rag',
            description=(
                'outline-driven retrieval-augmented article generation baseline '
                'used by the NAACL paper editor study'
            ),
            qualifiers={},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description=(
                'The official runner can schedule independent perspective research '
                'threads concurrently. The MethodProgram preserves the same bounded '
                'perspective/turn dependency graph but commits them serially until '
                'generic ready-set parallel authoring is available.'
            ),
        ),
    ),
    blockers=(
        'the exact FreshWiki 100-topic article bytes must be materialized under immutable dataset authority',
        'matched search results require a frozen paper-era retrieval provider/index cut',
        'matched rubric grading requires the exact paper evaluator/model assignment',
        'no matched NAACL execution evidence has yet been produced',
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_storm_wiki_v1.py', 'tests/test_scientific_storm_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
