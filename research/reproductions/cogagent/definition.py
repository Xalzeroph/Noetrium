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
    package="cogagent",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="cogagent",
        title="CogAgent: A Visual Language Model for GUI Agents",
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2024/html/"
            "Hong_CogAgent_A_Visual_Language_Model_for_GUI_Agents_CVPR_2024_paper.html"
        ),
        year=2024,
        paper_revision="CVPR 2024 final",
    ),
    catalog=ReproductionCatalog(
        domains=("gui-agent", "multimodal"),
        families=("gui_agent", "multimodal", "visual_grounding"),
        priority=1,
        benchmark_ids=("mind2web",),
        platform_pressure=(
            "model/request",
            "environment/gui",
            "artifact/lineage",
            "experimentation/study",
        ),
        method_owned=(
            "dual-resolution GUI visual representation",
            "screenshot-only GUI policy",
            "candidate-element target selection and operation prediction",
        ),
        platform_owned=(
            "multimodal content references",
            "model binding and immutable checkpoint identity",
            "Mind2Web task cut and verifier",
            "measurement and evidence lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/cogagent/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/cogagent/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/cogagent/study.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The MethodProgram reproduces paper-era screenshot-only GUI "
                "policy semantics while the dual-resolution CogAgent network is "
                "treated as a separately bound model artifact/provider rather "
                "than reimplemented inside the method package."
            ),
        ),
    ),
    blockers=(
        "the exact CVPR paper-era CogAgent-18B checkpoint must be materialized with immutable model identity",
        "matched AITW execution awaits an AITW benchmark cut with exact paper evaluator identity",
        "no matched CVPR execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_cogagent_v1.py",),
)

__all__ = ["REPRODUCTION"]
