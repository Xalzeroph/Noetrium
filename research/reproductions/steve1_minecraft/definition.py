from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionIdentity,
    ReproductionLifecycle,
)


REPRODUCTION = ReproductionDefinition(
    package="steve1_minecraft",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="steve-1",
        title="STEVE-1: A Generative Model for Text-to-Behavior in Minecraft",
        paper_uri=(
            "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
            "dd03f856fc7f2efeec8b1c796284561d-Abstract-Conference.html"
        ),
        year=2023,
        paper_revision=(
            "NeurIPS 2023 / official paper-consistent commit "
            "874cf9b808c9dd0a5d4446ef2e008e3789c55c57"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("minecraft", "embodied-agent", "vision-language-control"),
        families=(
            "minecraft_agent",
            "goal_conditioned_control",
            "vision_language_action",
        ),
        priority=1,
        benchmark_ids=("steve1-paper-prompts",),
        platform_pressure=(
            "execution/workflow",
            "environment/minecraft",
            "model/multimodal",
            "artifact/content",
            "participant/capability",
        ),
        method_owned=(
            "MineCLIP-latent goal conditioning",
            "text-to-latent prior conditioning",
            "visual-prompt latent conditioning",
            "classifier-free-guided recurrent VPT policy",
            "stochastic low-level keyboard/mouse action sampling",
        ),
        platform_owned=(
            "MethodProgram execution and checkpoints",
            "raw-pixel Minecraft environment provider",
            "content-addressed goal embeddings and recurrent controller state",
            "model weight/provider binding",
            "trajectory/effect evidence",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind.FIDELITY,
            path="research/reproductions/steve1_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.BENCHMARK,
            path="research/reproductions/steve1_minecraft/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.STUDY,
            path="research/reproductions/steve1_minecraft/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.METHOD_PROGRAM,
            path="research/reproductions/steve1_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.SUPPORT,
            path="research/reproductions/steve1_minecraft/source.py",
        ),
    ),
    primary_executable="research/reproductions/steve1_minecraft/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "Formal numerical claims require immutable VPT, MineCLIP, STEVE-1 "
        "policy and prior weight artifacts plus the paper-era MineRL runtime.",
        "The released repository exposes 11 named paper prompts for both text "
        "and visual conditioning (22 executable cells), but does not expose "
        "the complete identity of the separate 13-task early-game result "
        "suite; that numerical claim remains unmatched rather than fabricated.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_steve1_minecraft_v1.py",
        "tests/test_scientific_steve1_benchmark_study_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
