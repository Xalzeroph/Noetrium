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
    package="toolformer",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="toolformer",
        title="Toolformer: Language Models Can Teach Themselves to Use Tools",
        paper_uri=(
            "https://proceedings.neurips.cc/paper/2023/hash/"
            "d842425e4bf79ba039352da0f658a906-Abstract-Conference.html"
        ),
        year=2023,
        paper_revision="NeurIPS 2023 final",
    ),
    catalog=ReproductionCatalog(
        domains=("tool-use", "training"),
        families=("tool_use", "self_supervision", "training"),
        priority=1,
        benchmark_ids=("toolformer-eval",),
        platform_pressure=(
            "model/request",
            "participant/method",
            "participant/capability",
            "execution",
            "experimentation/study",
            "artifact/lineage",
        ),
        method_owned=(
            "few-shot API-call annotation prompts",
            "candidate API position and call sampling",
            "future-token loss based API-call filtering",
            "API-call augmented language-model finetuning semantics",
            "API-aware interrupted decoding policy",
        ),
        platform_owned=(
            "model invocation and immutable model identity",
            "capability execution and effect evidence",
            "benchmark cut identity",
            "study and measurement authority",
            "training artifact lineage when a qualified trainer is bound",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/toolformer/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/toolformer/filtering.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/toolformer/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/toolformer/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="toolformer_asdiv",
            metric_id="task_success_percent",
            value=40.4,
            qualifiers={"dataset": "ASDiv", "model": "Toolformer"},
        ),
        ReportedResult(
            claim_id="toolformer_svamp",
            metric_id="task_success_percent",
            value=29.4,
            qualifiers={"dataset": "SVAMP", "model": "Toolformer"},
        ),
        ReportedResult(
            claim_id="toolformer_mawps",
            metric_id="task_success_percent",
            value=44.0,
            qualifiers={"dataset": "MAWPS", "model": "Toolformer"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="toolformer-disabled",
            description=(
                "the same finetuned Toolformer checkpoint with the API token "
                "probability forced to zero during decoding"
            ),
            qualifiers={
                "ASDiv": 14.8,
                "SVAMP": 6.3,
                "MAWPS": 15.0,
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "Paper inference interrupts one continuous decoding stream when "
                "the API result marker is emitted, inserts the external result, "
                "and resumes the same generation. The current MethodProgram "
                "represents the continuation as a second explicitly bound model "
                "invocation so both model-visible cuts remain auditable."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The exact CCNet subset, sampled candidate calls, and finetuned "
                "GPT-J Toolformer checkpoint are not yet materialized under "
                "immutable Artifact authority; filtering semantics are reproduced "
                "but matched training is not claim-ready."
            ),
        ),
    ),
    blockers=(
        "exact paper-era CCNet subset and API-annotated C* bytes are not yet materialized",
        "the paper-era Toolformer GPT-J finetuned checkpoint is not available as an immutable bound artifact",
        "historical Atlas, KILT Wikipedia, NLLB/fastText and calendar provider cuts must be frozen for matched execution",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_toolformer_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
