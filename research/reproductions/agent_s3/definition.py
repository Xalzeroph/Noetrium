from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
    package='agent_s3',
    lifecycle=ReproductionLifecycle('catalogued'),
    identity=ReproductionIdentity(
        method_id='agent-s3',
        title='The Unreasonable Effectiveness of Scaling Agents for Computer Use',
        paper_uri='https://arxiv.org/abs/2510.02250',
        year=2025,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('gui-computer-use', 'multimodal', 'context-management', 'runtime-systems'),
        families=('gui', 'computer_use', 'multimodal', 'reflection'),
        priority=1,
        benchmark_ids=('osworld',),
        platform_pressure=('participant/agent', 'environment/gui', 'model/request', 'execution', 'observability/telemetry'),
        method_owned=('single-worker computer-use policy', 'trajectory reflection policy', 'single-action grounding policy', 'optional bounded code-agent policy'),
        platform_owned=('GUI environment execution', 'multimodal transport', 'model-view projection', 'controlled code execution', 'evidence and telemetry'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/agent_s3/context.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/agent_s3/fidelity.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=(),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_agent_s3_v1.py',),
)

__all__ = ["REPRODUCTION"]
