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
    package="vima_embodied",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="vima",
        title="VIMA: Robot Manipulation with Multimodal Prompts",
        paper_uri="https://proceedings.mlr.press/v202/jiang23b.html",
        year=2023,
        paper_revision=(
            "ICML 2023 camera-ready / VIMA policy "
            "a16536f55780738ec2ce932f882f15bc011d7307 / "
            "VIMA-Bench 224c2d870d6063d90215201ba42d4211ddc957d7"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("embodied-robotics", "multimodal"),
        families=(
            "embodied",
            "multimodal_prompting",
            "robot_manipulation",
            "object_centric_policy",
            "autoregressive_control",
        ),
        priority=1,
        benchmark_ids=("vima-bench",),
        platform_pressure=(
            "execution/workflow",
            "environment/embodied",
            "artifact/content",
            "model/request",
            "participant/agent",
            "experimentation/study",
        ),
        method_owned=(
            "interleaved language/object prompt sequence semantics",
            "object-centric observation history semantics",
            "autoregressive observation/action-token interleaving",
            "six-component discretized pick/place action policy",
            "camera-ready action de-discretization semantics",
        ),
        platform_owned=(
            "MethodProgram host and journal authority",
            "multimodal tensor content identity and transport",
            "embodied environment execution",
            "model serving and policy execution",
            "effect evidence",
            "benchmark/study orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/vima_embodied/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/vima_embodied/environment.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/vima_embodied/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/vima_embodied/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/vima_embodied/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/vima_embodied/policy.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/vima_embodied/source.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "A qualified concrete VIMA-Bench embodied simulator adapter is still "
        "required for formal environment execution.",
        "The paper specifies multiple test episodes but the complete paper-result "
        "episode seed/count schedule is not content-addressed in the audited "
        "camera-ready executable; the formal cut therefore freezes the official "
        "seed-42 executable protocol without claiming matched aggregate results.",
        "Full checkpoint-level result reproduction requires immutable released "
        "policy checkpoints and the camera-ready observation/prompt frontend.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_vima_embodied_v1.py",
        "tests/test_scientific_vima_benchmark_study_v1.py",
        "tests/test_scientific_vima_environment_adapter_v1.py",
    ),
)


__all__ = ["REPRODUCTION"]
