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
    package="self_consistency_gsm8k",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="self-consistency",
        title="Self-Consistency Improves Chain of Thought Reasoning in Language Models",
        paper_uri="https://openreview.net/forum?id=1PL1NIMMrw",
        year=2023,
        paper_revision="ICLR 2023 published conference paper",
    ),
    catalog=ReproductionCatalog(
        domains=("reasoning",),
        families=("reasoning", "chain_of_thought", "self_consistency", "sampling"),
        priority=1,
        benchmark_ids=("gsm8k",),
        platform_pressure=(
            "research/provenance",
            "participant/method",
            "model/request",
            "execution/workflow",
            "experimentation/study",
            "experimentation/evaluation",
            "observability/telemetry",
        ),
        method_owned=(
            "diverse chain-of-thought path sampling",
            "task-specific final-answer projection",
            "answer-frequency marginalization",
        ),
        platform_owned=(
            "publication provenance",
            "independent model invocation accounting",
            "benchmark cut identity",
            "repetition identity",
            "isolated exact-answer evaluation",
            "measurement evidence",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/self_consistency_gsm8k/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/self_consistency_gsm8k/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/self_consistency_gsm8k/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="palm540b_self_consistency_gsm8k",
            metric_id="task_success_percent",
            value=74.4,
            qualifiers={
                "model": "PaLM-540B",
                "benchmark": "GSM8K",
                "reasoning_paths": 40,
                "temperature": 0.7,
                "top_k": 40,
            },
        ),
        ReportedResult(
            claim_id="palm540b_greedy_cot_gsm8k",
            metric_id="task_success_percent",
            value=56.5,
            qualifiers={
                "model": "PaLM-540B",
                "benchmark": "GSM8K",
                "reasoning_paths": 1,
                "decoding": "greedy",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="greedy_single_path_cot",
            description="same chain-of-thought prompt with one greedily decoded reasoning path",
            qualifiers={"model": "PaLM-540B", "benchmark": "GSM8K"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description="the paper does not define a scientifically meaningful tie-break rule when multiple final answers have equal maximum frequency; native reproduction uses earliest sampled answer only for deterministic execution",
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description="the historical PaLM-540B serving snapshot is not available as a public immutable model artifact",
        ),
    ),
    blockers=(
        "exact historical PaLM-540B provider artifact is unavailable for matched execution",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_self_consistency_gsm8k_v1.py",
        "tests/test_scientific_gsm8k_cut_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
