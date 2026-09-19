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
    package="minedojo",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="minedojo",
        title=(
            "MineDojo: Building Open-Ended Embodied Agents "
            "with Internet-Scale Knowledge"
        ),
        paper_uri=(
            "https://proceedings.neurips.cc/paper_files/paper/2022/hash/"
            "74a67268c5cc5910f64938cac4526a90-Abstract.html"
        ),
        year=2022,
        paper_revision=(
            "NeurIPS 2022 Datasets and Benchmarks / MineDojo "
            "1fc46f58aaeed5eb8018abf030c95a13d41ab4a4 / MineCLIP "
            "5ec098c1660da44933ae9a221ea3ee180f973e0d"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "embodied-robotics",
            "minecraft",
            "multimodal",
            "benchmark",
        ),
        families=(
            "open_ended_embodied",
            "minecraft",
            "multimodal_knowledge",
            "video_language_reward",
            "language_conditioned_control",
        ),
        priority=1,
        benchmark_ids=("minedojo",),
        platform_pressure=(
            "environment/minecraft",
            "artifact/content",
            "model/request",
            "participant/policy",
            "experimentation/benchmark",
            "experimentation/study",
            "evaluation",
        ),
        method_owned=(
            "3,142-task paper-consistent benchmark taxonomy",
            "language-prompted Minecraft task semantics",
            "logical-any programmatic success aggregation",
            "MineCLIP video-language reward semantics",
            "language-conditioned MineAgent policy semantics",
        ),
        platform_owned=(
            "immutable benchmark cut identity",
            "Minecraft environment provider and lifecycle",
            "content-addressed video/tensor artifacts",
            "model deployment and serving identity",
            "effect evidence and reconciliation",
            "Study/Experiment orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/minedojo/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/minedojo/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("semantics"),
            path="research/reproductions/minedojo/reward.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/minedojo/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/minedojo/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/minedojo/source.py",
        ),
    ),
    primary_executable="research/reproductions/minedojo/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The released run_env_in_loop.py uses random placeholder "
                "vectors for observation preprocessing and explicitly says "
                "real preprocessing must extract MineCLIP image/prompt "
                "features and other observation features. The MethodProgram "
                "therefore treats preprocessed MineAgent observation as an "
                "explicit model input seam instead of reproducing the random "
                "demo placeholder as scientific semantics."
            ),
        ),
    ),
    blockers=(
        "The paper-era task loader and five YAML authorities are frozen by "
        "Git tree/blob identity and a deterministic official-registry "
        "materializer now derives per-task digests. Formal runs still require "
        "the audited MineDojo runtime image to materialize that registry under "
        "Artifact authority.",
        "The released MineCLIP checkpoint bytes are externally hosted and have "
        "not yet been acquired into the content-addressed model/artifact store; "
        "the paper-release repository records MD5 identifiers but formal runs "
        "require immutable acquired artifact identity.",
        "Full MineCLIP/MineAgent matched-result reproduction additionally "
        "requires the released MineDojo video/data cuts, policy checkpoint, "
        "and real observation/prompt frontend artifacts to be materialized "
        "under immutable content identity.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_minedojo_v1.py",
        "tests/test_scientific_minedojo_materializer_v1.py",
    ),
)


__all__ = ["REPRODUCTION"]
