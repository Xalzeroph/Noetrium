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
    package="chatdev_v1",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="chatdev",
        title="ChatDev: Communicative Agents for Software Development",
        paper_uri="https://aclanthology.org/2024.acl-long.810/",
        year=2024,
        paper_revision=(
            "ACL 2024 / official v1.0.0 commit "
            "acb93cf3d15cec5b9ee6eec0850ddd3932164329"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multi-agent", "software-engineering"),
        families=(
            "multi_agent",
            "software_agent",
            "communication",
            "role_playing",
        ),
        priority=1,
        benchmark_ids=("srdd",),
        platform_pressure=(
            "execution/workflow",
            "execution/machines",
            "participant/agent",
            "environment/software",
            "model/request",
            "artifact/lineage",
            "experimentation/study",
        ),
        method_owned=(
            "software-company role specialization",
            "eight-stage phase-chain orchestration",
            "bounded composed-phase loops",
            "two-role phase conversation semantics",
            "reflection phase semantics",
        ),
        platform_owned=(
            "MethodProgram host and journal authority",
            "nested ResearchMachine execution and child links",
            "RuntimeProgram host and journal authority",
            "participant/model binding",
            "software workspace execution",
            "artifact lineage",
            "evaluation",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/chatdev_v1/chain.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/chatdev_v1/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/chatdev_v1/runtime.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/chatdev_v1/environment.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/chatdev_v1/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/chatdev_v1/source.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/chatdev_v1/workspace.py",
        ),
    ),
    primary_executable="research/reproductions/chatdev_v1/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "Released ChatDev invokes filesystem/process mechanics through "
                "ambient os/subprocess shell calls. The reproduction preserves "
                "the phase semantics but binds them to the platform "
                "software.repository provider and exact-argv process authority, "
                "with content-addressed workspace state and effect receipts."
            ),
        ),
    ),
    blockers=(
        "Software workspace effect receipts are preserved inside the nested "
        "EnvironmentMachine result, but formal claim-ready runs still need "
        "promotion into the shared durable effect authority.",
        "Exact historical hosted model serving used by the released ChatDev "
        "configuration is not an immutable public model artifact.",
        "The frozen SRDD benchmark cut is bound, but formal runnable studies "
        "still need the paper-metric evaluator and Study protocol.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_chatdev_v1.py",
        "tests/test_scientific_chatdev_phase_runtime_v1.py",
        "tests/test_scientific_chatdev_method_program_v1.py",
        "tests/test_scientific_chatdev_workspace_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
