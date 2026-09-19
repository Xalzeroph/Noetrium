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
    package="chain_of_thought_gsm8k",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="chain-of-thought",
        title="Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        paper_uri="https://proceedings.neurips.cc/paper_files/paper/2022/hash/9d5609613524ecf4f15af0f7b31abca4-Abstract-Conference.html",
        year=2022,
        paper_revision="NeurIPS 2022 final",
    ),
    catalog=ReproductionCatalog(
        domains=("reasoning",),
        families=("reasoning", "chain_of_thought", "few_shot_prompting"),
        priority=1,
        benchmark_ids=("gsm8k",),
        platform_pressure=(
            "research/provenance",
            "participant/method",
            "model/request",
            "experimentation/study",
            "experimentation/evaluation",
        ),
        method_owned=(
            "eight-shot chain-of-thought exemplar prompt",
            "single greedy reasoning-path generation",
        ),
        platform_owned=(
            "publication provenance",
            "model invocation",
            "benchmark cut identity",
            "isolated exact-answer evaluation",
            "measurement evidence",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/chain_of_thought_gsm8k/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/chain_of_thought_gsm8k/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/chain_of_thought_gsm8k/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="palm540b_cot_gsm8k",
            metric_id="task_success_percent",
            value=56.9,
            qualifiers={
                "model": "PaLM-540B",
                "benchmark": "GSM8K",
                "prompt": "8-shot chain-of-thought",
                "decoding": "greedy",
                "calculator": False,
            },
        ),
        ReportedResult(
            claim_id="palm540b_standard_gsm8k",
            metric_id="task_success_percent",
            value=17.9,
            qualifiers={
                "model": "PaLM-540B",
                "benchmark": "GSM8K",
                "prompt": "8-shot standard",
                "decoding": "greedy",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="standard_eight_shot_prompting",
            description="same eight arithmetic exemplars without intermediate chain-of-thought reasoning",
            qualifiers={"model": "PaLM-540B", "benchmark": "GSM8K"},
        ),
    ),
    deltas=(
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
        "tests/test_scientific_chain_of_thought_gsm8k_v1.py",
        "tests/test_scientific_gsm8k_cut_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
