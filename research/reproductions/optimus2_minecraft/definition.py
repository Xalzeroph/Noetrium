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
    package="optimus2_minecraft",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="optimus2-minecraft",
        title=(
            "Optimus-2: Multimodal Minecraft Agent with "
            "Goal-Observation-Action Conditioned Policy"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2025/html/"
            "Li_Optimus-2_Multimodal_Minecraft_Agent_with_"
            "Goal-Observation-Action_Conditioned_Policy_CVPR_2025_paper.html"
        ),
        year=2025,
        paper_revision=(
            "CVPR 2025 camera-ready / official paper repository "
            "8651b3177ac5c7fa73a36b74e4b350a35a679338"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "multimodal",
            "minecraft",
            "embodied-robotics",
            "vision-language-action",
        ),
        families=(
            "minecraft",
            "goal_conditioned_policy",
            "multimodal_policy",
            "behavior_modeling",
            "planner_controller",
        ),
        priority=1,
        benchmark_ids=(),
        platform_pressure=(
            "execution/machines/method",
            "participant/agent",
            "model/multimodal",
            "environment/minecraft",
            "artifact/trajectory",
            "experimentation/study",
        ),
        method_owned=(
            "MLLM high-level task planning",
            "Goal-Observation-Action Conditioned Policy semantics",
            "action-guided behavior encoding",
            "observation-action causal modeling",
            "fixed-length behavior-token consolidation",
            "language-conditioned autoregressive action prediction",
        ),
        platform_owned=(
            "MethodMachine journal authority",
            "multimodal model transport",
            "Minecraft environment lifecycle and effects",
            "trajectory/evidence identity",
            "Study/Experiment orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/optimus2_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/optimus2_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/optimus2_minecraft/source.py",
        ),
    ),
    primary_executable=(
        "research/reproductions/optimus2_minecraft/program.py"
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The official CVPR 2025 paper repository contains README, "
                "figures and tables but no executable GOAP/planner source at "
                "the paper-era cut or the later 2025-06 repository head. "
                "The Noetrium MethodProgram is therefore an explicitly "
                "independent reconstruction of paper-level control semantics, "
                "not an official-code reproduction."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "GOAP network internals, trained weights, MGOA dataset bytes "
                "and exact evaluation runtime are not bound to immutable "
                "public executable artifacts in this reproduction."
            ),
        ),
    ),
    blockers=(
        "The official repository does not publish executable paper-era code.",
        "MGOA training data and model/checkpoint identities are not yet "
        "content-addressed under reproduction authority.",
        "Atomic, long-horizon and open-ended evaluation cuts are not yet "
        "bound as exact BenchmarkTaskSet artifacts.",
        "Matched paper-result execution is therefore not claim-ready.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_optimus2_minecraft_v1.py",),
)


__all__ = ["REPRODUCTION"]
