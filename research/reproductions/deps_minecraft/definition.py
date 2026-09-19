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
    package="deps_minecraft",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="deps-minecraft",
        title=(
            "Describe, Explain, Plan and Select: Interactive Planning with "
            "Large Language Models Enables Open-World Multi-Task Agents"
        ),
        paper_uri=(
            "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
            "6b8dfb8c0c12e6fafc6c256cb08a5ca7-Abstract-Conference.html"
        ),
        year=2023,
        paper_revision=(
            "NeurIPS 2023 / official MC-Planner release "
            "df7067614ed527a2b56262441472886f1eb628ca"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "game-worlds",
            "embodied-robotics",
            "planning-search",
            "minecraft",
        ),
        families=(
            "minecraft",
            "interactive_planning",
            "failure_explanation",
            "goal_selection",
            "hierarchical_control",
        ),
        priority=1,
        benchmark_ids=(),
        platform_pressure=(
            "execution/workflow",
            "participant/agent",
            "environment/minecraft",
            "model/request",
            "experimentation/study",
            "evaluation",
        ),
        method_owned=(
            "Describe-Explain-Plan-Select interaction order",
            "LLM planner dialogue state",
            "failure-conditioned explanation and replanning",
            "learned horizon-based sub-goal selection",
            "craft/smelt/mine replanning triggers",
            "replanning round boundary",
        ),
        platform_owned=(
            "MethodProgram host and journal authority",
            "model invocation and model identity",
            "Minecraft environment lifecycle",
            "goal-conditioned controller capability execution",
            "effect evidence and reconciliation",
            "Study/Experiment orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/deps_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/deps_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/deps_minecraft/source.py",
        ),
    ),
    primary_executable="research/reproductions/deps_minecraft/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The official MC-Planner repository exposes selector.py only "
                "as an abstract shell, while the paper and default configuration "
                "require a learned horizon/ranking selector. The reproduction "
                "therefore preserves Selector as an explicit identity-bound "
                "method seam and does not invent a replacement implementation."
            ),
        ),
    ),
    blockers=(
        "Matched execution requires the unreleased paper-era learned Selector "
        "implementation/checkpoint or an authoritatively identified equivalent.",
        "The released planner targets historical code-davinci-002/text-davinci-003 "
        "serving; exact hosted model snapshots are not immutable public artifacts.",
        "Matched Minecraft results additionally require the paper-era "
        "goal-conditioned controller checkpoint, modified MineDojo simulator "
        "runtime, and evaluated task/environment cuts under Artifact authority.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_deps_minecraft_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
