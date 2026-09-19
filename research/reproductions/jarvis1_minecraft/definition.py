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
    package="jarvis1_minecraft",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="jarvis1",
        title=(
            "JARVIS-1: Open-World Multi-Task Agents With "
            "Memory-Augmented Multimodal Language Models"
        ),
        paper_uri="https://ieeexplore.ieee.org/document/10778628/",
        year=2025,
        paper_revision=(
            "IEEE TPAMI 47(3), March 2025 / partial official executable "
            "commit aa9bd97debee045cb35b37564c71dee4c465b9ad"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "minecraft",
            "embodied-agent",
            "multimodal-memory",
        ),
        families=(
            "minecraft_agent",
            "multimodal_memory",
            "lifelong_learning",
            "hierarchical_control",
        ),
        priority=1,
        benchmark_ids=("jarvis1-offline-185",),
        platform_pressure=(
            "execution/machines/memory",
            "execution/workflow",
            "environment/minecraft",
            "environment/embodied",
            "model/multimodal",
            "participant/capability",
            "artifact/lineage",
        ),
        method_owned=(
            "multimodal-experience retrieval for planning",
            "memory-conditioned high-level planning",
            "skill selection from agent state",
            "goal-conditioned controller dispatch",
            "lifelong experience accumulation semantics",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "MethodProgram and child-machine composition",
            "Minecraft/embodied environment execution",
            "controller capability execution",
            "content-addressed multimodal artifacts",
            "model transport and implementation identity",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind.FIDELITY,
            path="research/reproductions/jarvis1_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.BENCHMARK,
            path="research/reproductions/jarvis1_minecraft/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.STUDY,
            path="research/reproductions/jarvis1_minecraft/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.METHOD_PROGRAM,
            path="research/reproductions/jarvis1_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.RESEARCH_PROGRAM,
            path="research/reproductions/jarvis1_minecraft/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.SUPPORT,
            path="research/reproductions/jarvis1_minecraft/source.py",
        ),
    ),
    primary_executable="research/reproductions/jarvis1_minecraft/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The public JARVIS-1 repository explicitly removes the "
                "multimodal state/action sequences from memory.json and does "
                "not release the multimodal descriptor or retrieval "
                "implementation. The MemoryProgram therefore exposes "
                "paper-semantic multimodal retrieval only through an explicit "
                "identity-bound retriever port; it is not represented as "
                "matched official executable code."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The public repository exposes offline evaluation with fixed "
                "memory only and does not release the online learning path "
                "needed for the paper's lifelong self-improvement claims."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The public implementation removes the paper self-check "
                "module. The reproduction must not use the reduced public "
                "planner as evidence for matched self-check results."
            ),
        ),
    ),
    blockers=(
        "Matched multimodal-memory retrieval requires the unreleased paper-era "
        "descriptor/retrieval implementation or an explicitly declared "
        "clean-room substitution.",
        "Matched lifelong-learning claims require the unreleased online "
        "learning implementation and growing-memory protocol.",
        "The canonical study binds the released 185-task public offline "
        "fixed-memory lane only; it does not turn the unreleased multimodal "
        "retrieval or online lifelong-learning path into matched evidence.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_jarvis1_memory_v1.py",
        "tests/test_scientific_jarvis1_method_program_v1.py",
        "tests/test_scientific_jarvis1_benchmark_study_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
