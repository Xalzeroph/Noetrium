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
    package="voyager_minecraft",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="voyager",
        title="Voyager: An Open-Ended Embodied Agent with Large Language Models",
        paper_uri="https://mlanthology.org/tmlr/2024/wang2024tmlr-voyager/",
        year=2024,
        paper_revision=(
            "TMLR 2024 / official paper-release executable commit "
            "edeee8383a22b96b54bff51c6cf809306a7b34a3"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "embodied-robotics",
            "game-worlds",
            "memory",
            "self-improvement",
        ),
        families=(
            "curriculum",
            "embodied",
            "self_improvement",
            "skill_library",
        ),
        priority=1,
        benchmark_ids=("voyager-minecraft",),
        platform_pressure=(
            "environment/minecraft",
            "execution/machines",
            "execution/workflow",
            "memory",
            "model/request",
            "participant/agent",
            "reliability/recovery",
        ),
        method_owned=(
            "automatic curriculum",
            "chest memory update semantics",
            "curriculum QA cache semantics",
            "iterative prompting strategy",
            "skill library write and retrieval semantics",
            "self-verification loop",
        ),
        platform_owned=(
            "Machine Journal authority",
            "MemoryMachine hosting",
            "MethodProgram hosting",
            "Minecraft provider and sandbox mechanics",
            "model invocation",
            "nested Machine composition",
            "recovery and effect receipts",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/voyager_minecraft/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/voyager_minecraft/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/voyager_minecraft/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/voyager_minecraft/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/voyager_minecraft/source.py",
        ),
    ),
    primary_executable="research/reproductions/voyager_minecraft/program.py",
    reported_results=(
        ReportedResult(
            claim_id="voyager_unique_items_multiplier",
            metric_id="unique_items_multiplier",
            value=3.3,
            qualifiers={
                "comparison": "prior-state-of-the-art",
                "source": "TMLR paper",
            },
        ),
        ReportedResult(
            claim_id="voyager_tech_tree_speed_multiplier",
            metric_id="tech_tree_unlock_speed_multiplier",
            value=15.3,
            qualifiers={
                "bound": "up-to",
                "comparison": "prior-state-of-the-art",
                "source": "TMLR paper",
            },
        ),
        ReportedResult(
            claim_id="voyager_traversal_distance_multiplier",
            metric_id="traversal_distance_multiplier",
            value=2.3,
            qualifiers={
                "comparison": "prior-state-of-the-art",
                "source": "TMLR paper",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="voyager_prior_minecraft_agents",
            description=(
                "Prior Minecraft embodied agents used for the lifelong-learning "
                "comparison in the Voyager paper."
            ),
            qualifiers={"source": "TMLR paper evaluation"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The paper-release curriculum human-message path uses ambient "
                "Python random.random() for independent 0.8 inclusion of "
                "warmed-up observation sections. The reproduction preserves "
                "that Bernoulli distribution but obtains the realized mask "
                "through research.random.bernoulli-mask so the decision and "
                "provider receipt are journaled and replayable."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "Voyager executes generated JavaScript together with learned "
                "Mineflayer control programs. Noetrium currently has typed "
                "Minecraft actions but no qualified arbitrary-program sandbox; "
                "the MethodProgram therefore declares "
                "voyager.minecraft.execute_program as an explicit capability "
                "contract rather than treating primitive actions as equivalent."
            ),
        ),
    ),
    blockers=(
        "qualified sandboxed Mineflayer JavaScript program executor is not yet available",
        "the paper does not publish the exact Minecraft world seeds for the three lifelong-learning trials; matched-result execution must bind acquired original worlds or a declared substitute seed policy",
        "exact historical hosted GPT-4/GPT-3.5 serving snapshots are not immutable public model artifacts",
        "no matched TMLR execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_web_embodied_fidelity_v1.py', 'tests/test_scientific_voyager_curriculum_v1.py'),
)

__all__ = ["REPRODUCTION"]
