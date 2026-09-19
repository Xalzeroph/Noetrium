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
    package='mars_automated_ai_research',
    lifecycle=ReproductionLifecycle('artifact_only'),
    identity=ReproductionIdentity(
        method_id='mars-automated-ai-research',
        title='MARS: Modular Agent with Reflective Search for Automated AI Research',
        paper_uri='https://arxiv.org/abs/2602.02660',
        year=2026,
        paper_revision='arXiv:2602.02660',
    ),
    catalog=ReproductionCatalog(
        domains=('scientific-research', 'planning-search', 'reflection-self-correction', 'memory'),
        families=('cost_constrained_mcts', 'modular_research_agent', 'reflective_memory'),
        priority=1,
        benchmark_ids=('mle-bench',),
        platform_pressure=('artifact/lineage', 'experimentation/evaluation', 'experimentation/study'),
        method_owned=('budget-aware cost-constrained MCTS', 'Design-Decompose-Implement modular construction', 'comparative reflective memory and cross-branch lesson transfer'),
        platform_owned=('source-lane provenance', 'benchmark cut identity', 'artifact and grading-report lineage', 'metric reconstruction and evidence ingestion'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/mars_automated_ai_research/fidelity.py',
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id='mars_low_mean',
            metric_id='low_any_medal_mean_pct',
            value=74.24242424242425,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_low_sem',
            metric_id='low_any_medal_sem_pct',
            value=1.515151515151511,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_medium_mean',
            metric_id='medium_any_medal_mean_pct',
            value=52.63157894736842,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_medium_sem',
            metric_id='medium_any_medal_sem_pct',
            value=3.0386856273138223,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_high_mean',
            metric_id='high_any_medal_mean_pct',
            value=37.77777777777778,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_high_sem',
            metric_id='high_any_medal_sem_pct',
            value=2.2222222222222237,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_all_mean',
            metric_id='all_any_medal_mean_pct',
            value=56,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
        ReportedResult(
            claim_id='mars_all_sem',
            metric_id='all_any_medal_sem_pct',
            value=1.5396007178390008,
            qualifiers={'model_lane_id': 'paper_reported_mars',
 'reported_model_lane': {'kind': 'paper_reported',
                         'lane_id': 'paper_reported_mars',
                         'roles': [{'availability': 'paper/artifact reported model identity; exact '
                                                    'provider revision and decoding are not '
                                                    'released',
                                    'decoding': {},
                                    'model': 'Gemini-3-Pro-Preview',
                                    'role': 'research_agent_backbone'}]}},
        ),
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='executable MARS implementation remains unavailable',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='full method prompts, model revision and runtime orchestration remain unreleased',
        ),
    ),
    blockers=('official repository does not contain executable MARS agent source', 'provider/model revision, prompts and decoding required to replay MARS execution are not released in the artifact repository', 'artifact results can be reconstructed but method execution cannot yet be source-matched'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_mars_artifact_v1.py',),
)

__all__ = ["REPRODUCTION"]
