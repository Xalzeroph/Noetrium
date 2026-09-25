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
    package="os_symphony_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="os_symphony_acl2026",
        title="OS-Symphony: A Holistic Framework for Robust and Generalist Computer-Using Agents",
        paper_uri="https://aclanthology.org/2026.acl-long.1021/",
        year=2026,
        paper_revision="ACL 2026 final proceedings",
    ),
    catalog=ReproductionCatalog(
        domains=("agent", "frontier-2026", "gui-agent"),
        families=("gui-agent", "multimodal-memory", "tool-agent", "long-horizon"),
        priority=1,
        benchmark_ids=("osworld-verified", "windowsagentarena", "macosarena"),
        platform_pressure=("benchmark", "evidence", "execution/workflow", "experimentation/study", "model/request"),
        method_owned=("Route work between reflection-memory and versatile tool agents.", "Retrieve milestone-driven long-term trajectory memory.", "Use a SeeAct multimodal browser searcher to synthesize a visually aligned tutorial when needed.", "Execute the next computer action using current tutorial and memory context.", "Curate/prune visual history and record trajectory-level corrective memory."),
        platform_owned=(
            "MethodProgram execution and Machine Journal truth",
            "provider-independent model/tool dispatch and receipts",
            "content-addressed benchmark task identity",
            "Study/Experiment orchestration and measurement artifacts",
            "run/evidence provenance and replay",
        ),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/os_symphony_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/os_symphony_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/os_symphony_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/os_symphony_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="os_symphony_osworld", metric_id="task_success_rate", value=65.84, qualifiers={"benchmark": "OSWorld", "source": "ACL 2026 final paper abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01", description="backbone computer-use agent without OS-Symphony"),
        ReferenceBaseline(baseline_id="baseline_02", description="paper online CUA baselines"),
    ),
    blockers=("Matched execution requires frozen OS images, online benchmark revisions, browser sandbox, prompts and model snapshots.", "Online OS claims require replayable VM and Machine Journal receipts."),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)

__all__ = ["REPRODUCTION"]
