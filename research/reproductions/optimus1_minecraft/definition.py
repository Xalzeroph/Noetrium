from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
        benchmark_ids=(),
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
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/optimus1_minecraft/memory.py",
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
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The NeurIPS paper describes a 67-task long-horizon benchmark, "
                "while the paper-era official release contains 73 task rows across "
                "seven benchmark YAML files. The reproduction does not silently "
                "treat the release configuration union as the paper result cut."
            ),
        ),
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
        "The exact 67-task NeurIPS main-result cut must be recovered from the "
        "paper appendix rather than inferred from the 73 released YAML rows.",
        "Matched execution requires the paper-era MCP-Reborn Minecraft runtime "
        "and STEVE-1 controller checkpoint under content-addressed authority.",
        "The later 2025 full-memory release must not be substituted for the "
        "NeurIPS 2024 paper-era memory state without explicit provenance.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_optimus1_minecraft_v1.py",),
)


__all__ = ["REPRODUCTION"]
