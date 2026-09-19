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
    package='webvoyager',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='webvoyager',
        title='WebVoyager: Building an End-to-End Web Agent with Large Multimodal Models',
        paper_uri='https://aclanthology.org/2024.acl-long.371/',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('web-agents', 'gui-computer-use', 'multimodal'),
        families=('web_agent', 'multimodal', 'gui', 'agent_loop'),
        priority=1,
        benchmark_ids=('webvoyager',),
        platform_pressure=('participant/agent', 'environment/web', 'environment/gui', 'model/request', 'experimentation/study', 'observability/telemetry'),
        method_owned=('numerically labeled browser observation policy', 'one-action browser grammar', 'browser reasoning policy'),
        platform_owned=('multimodal content transport', 'web and GUI environment execution', 'model invocation', 'evidence and metrics'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/webvoyager/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/webvoyager/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/webvoyager/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=(
        'matched ACL results require the exact historical multimodal model service revision used by the paper',
        'live-web reproduction requires a frozen browser/site-state cut or equivalent environment evidence for every task',
        'the official 643-task source bytes and verifier outputs must be materialized under immutable evidence authority before matched claims',
    ),
    evidence_refs=(),
    scientific_tests=(
        'tests/test_scientific_web_embodied_fidelity_v1.py',
        'tests/test_scientific_webvoyager_method_program_v1.py',
    ),
)

__all__ = ["REPRODUCTION"]
