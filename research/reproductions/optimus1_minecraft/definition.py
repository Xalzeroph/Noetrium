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
    package="optimus1_minecraft",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="optimus1-minecraft",
        title=(
            "Optimus-1: Hybrid Multimodal Memory Empowered Agents "
            "Excel in Long-Horizon Tasks"
        ),
        paper_uri=(
            "https://proceedings.neurips.cc/paper_files/paper/2024/hash/"
            "5949a8750a110ce1f0631b1776c500a2-Abstract-Conference.html"
        ),
        year=2024,
        paper_revision=(
            "NeurIPS 2024 / official code release "
            "e789c58f53a4f831d67c4d6aaa008dbfd198a229"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "multimodal",
            "memory",
            "minecraft",
            "embodied-robotics",
            "long-horizon-planning",
        ),
        families=(
            "multimodal_memory",
            "minecraft",
            "hybrid_memory",
            "knowledge_graph_memory",
            "episodic_multimodal_memory",
            "planning_reflection",
        ),
        priority=1,
        benchmark_ids=("minecraft-long-horizon-67",),
        platform_pressure=(
            "execution/machines/memory",
            "execution/machines/method",
            "model/multimodal",
            "environment/minecraft",
            "artifact/multimodal",
            "experimentation/study",
        ),
        method_owned=(
            "Hierarchical Directed Knowledge Graph construction and retrieval",
            "Abstracted Multimodal Experience Pool semantics",
            "successful-plan experience storage and fuzzy retrieval",
            "multimodal reflection experience categories",
            "error-conditioned replan experience retrieval",
            "Knowledge-Guided Planner semantics",
            "Experience-Driven Reflector semantics",
            "periodic planner-reflector-controller interaction",
        ),
        platform_owned=(
            "MemoryMachine and MethodMachine journal authority",
            "multimodal content identity and transport",
            "Minecraft environment lifecycle and effects",
            "model invocation and participant identity",
            "artifact/evidence lineage",
            "Study/Experiment orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/optimus1_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/optimus1_minecraft/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/optimus1_minecraft/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/optimus1_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/optimus1_minecraft/source.py",
        ),
    ),
    primary_executable="research/reproductions/optimus1_minecraft/program.py",
    reported_results=(
        ReportedResult(
            claim_id="optimus1_wooden_pickaxe_success",
            metric_id="success_rate_percent",
            value=100.0,
            qualifiers={
                "task": "craft-wooden-pickaxe",
                "evaluation_times": 30,
                "average_steps": 1153.91,
                "average_time_seconds": 57.70,
                "source": "NeurIPS-2024 paper appendix",
            },
        ),
        ReportedResult(
            claim_id="optimus1_stone_pickaxe_success",
            metric_id="success_rate_percent",
            value=96.77,
            qualifiers={
                "task": "craft-stone-pickaxe",
                "evaluation_times": 31,
                "average_steps": 2310.09,
                "average_time_seconds": 115.50,
                "source": "NeurIPS-2024 paper appendix",
            },
        ),
        ReportedResult(
            claim_id="optimus1_paper_long_horizon_task_count",
            metric_id="evaluation_task_count",
            value=67,
            qualifiers={
                "scope": "paper-main-long-horizon-benchmark",
                "source": "NeurIPS-2024 paper",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="optimus1_minecraft_agents",
            description=(
                "Minecraft embodied-agent baselines used in the NeurIPS 2024 "
                "long-horizon task comparison."
            ),
            qualifiers={"source": "NeurIPS-2024 paper evaluation"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The paper analyzes GPT-4V and multiple MLLM backbones, while the "
                "2024-10 official planning implementation invokes gpt-4o. Model "
                "identity is therefore kept source-lane-specific until the exact "
                "main-result service cut is bound."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The paper/framework description says Experience-Driven Reflector "
                "feedback can trigger replanning, but the paper-era released "
                "main.py parses replan_type and stores reflection memory without "
                "branching on the replan label. The executable MethodProgram "
                "preserves that released control-flow fact; craft/smelt/equip "
                "failure remains the explicit source-level replan path."
            ),
        ),
    ),
    blockers=(
        "Matched execution requires the paper-era MCP-Reborn Minecraft runtime "
        "and STEVE-1 controller checkpoint under content-addressed authority.",
        "The later 2025 full-memory release must not be substituted for the "
        "NeurIPS 2024 paper-era memory state without explicit provenance.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)


__all__ = ["REPRODUCTION"]
