from __future__ import annotations

from research.reproductions.contracts import (
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
    package='rap_reasoning',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='rap',
        title='Reasoning with Language Model is Planning with World Model',
        paper_uri='https://aclanthology.org/2023.emnlp-main.507/',
        year=2023,
        paper_revision='arXiv:2305.14992 / EMNLP 2023',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'world-models', 'reasoning'),
        families=('mcts', 'world_model', 'reasoning'),
        priority=1,
        benchmark_ids=('blocksworld',),
        platform_pressure=('model/request', 'model/assignment', 'experimentation/study', 'experimentation/evaluation'),
        method_owned=('MCTS reasoning policy', 'reasoner/world-model role semantics', 'RAP reward aggregation'),
        platform_owned=('named model-role binding', 'benchmark cut identity', 'evaluator binding', 'study execution and evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/rap_reasoning/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/rap_reasoning/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/rap_reasoning/search.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/rap_reasoning/study.py',
        ),
    ),
    primary_executable="research/reproductions/rap_reasoning/program.py",
    reported_results=(
        ReportedResult(
            claim_id="rap_llama33b_plan_generation_relative_gain",
            metric_id="relative_improvement_percent",
            value=33.0,
            qualifiers={
                "task": "plan generation",
                "model": "LLaMA-33B",
                "comparison": "CoT on GPT-4",
                "source": "EMNLP 2023 abstract",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="cot_gpt4_plan_generation",
            description=(
                "GPT-4 chain-of-thought plan-generation baseline used by the "
                "RAP paper for the reported relative improvement comparison."
            ),
            qualifiers={"source": "EMNLP 2023 paper"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='exact paper-era LLaMA deployment/checkpoint provenance remains incomplete',
        ),
    ),
    blockers=('exact historical LLaMA checkpoint/deployment identity is not yet rebound',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_rap_reproduction_v1.py',),
)

__all__ = ["REPRODUCTION"]
