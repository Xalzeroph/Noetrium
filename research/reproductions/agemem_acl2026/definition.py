from __future__ import annotations

from research.reproductions.contracts import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="agemem_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="agemem_acl2026",
        title="Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents",
        paper_uri="https://aclanthology.org/2026.acl-long.981/",
        year=2026,
        paper_revision="ACL 2026 final proceedings",
    ),
    catalog=ReproductionCatalog(
        domains=("agent", "frontier-2026", "memory"),
        families=("memory", "long-horizon", "reinforcement-learning", "tool-use"),
        priority=1,
        benchmark_ids=("alfworld", "scienceworld", "agentboard-pddl", "babyai", "hotpotqa"),
        platform_pressure=("benchmark", "evidence", "execution/workflow", "experimentation/study", "model/request"),
        method_owned=("Observe task state plus current short-term and long-term memory.", "Choose store, retrieve, update, summarize, discard, or no-op as a memory tool action.", "Apply the selected memory action while leaving memory authority to the platform.", "Reason over the resulting memory view and emit the next environment action.", "Record step-wise process/outcome signals required by progressive RL and step-wise GRPO."),
        platform_owned=(
            "MethodProgram execution and Machine Journal truth",
            "provider-independent model/tool dispatch and receipts",
            "content-addressed benchmark task identity",
            "Study/Experiment orchestration and measurement artifacts",
            "run/evidence provenance and replay",
        ),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/agemem_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/agemem_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/agemem_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/agemem_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="agemem_qwen25_avg", metric_id="average_score", value=41.96, qualifiers={"model": "Qwen2.5-7B-Instruct", "benchmarks": "ALFWorld/SciWorld/PDDL/BabyAI/HotpotQA"}),
        ReportedResult(claim_id="agemem_qwen3_avg", metric_id="average_score", value=54.31, qualifiers={"model": "Qwen3-4B-Instruct", "benchmarks": "ALFWorld/SciWorld/PDDL/BabyAI/HotpotQA"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01", description="No-Memory"),
        ReferenceBaseline(baseline_id="baseline_02", description="LangMem"),
        ReferenceBaseline(baseline_id="baseline_03", description="A-Mem"),
        ReferenceBaseline(baseline_id="baseline_04", description="Mem0"),
        ReferenceBaseline(baseline_id="baseline_05", description="Mem0g"),
        ReferenceBaseline(baseline_id="baseline_06", description="AgeMem-noRL"),
    ),
    blockers=("Matched execution requires the released AgeMem training/checkpoint revision and exact five benchmark cuts.", "Step-wise GRPO claims require real model training receipts rather than paper-reported numbers."),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_frontier_2026_wave_01.py',),
)

__all__ = ["REPRODUCTION"]
