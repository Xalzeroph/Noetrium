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
    package='ui_tars_desktop_v001',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='ui-tars',
        title='UI-TARS: Pioneering Automated GUI Interaction with Native Agents',
        paper_uri='https://arxiv.org/abs/2501.12326',
        year=2025,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('gui-computer-use', 'multimodal'),
        families=('gui_agent', 'multimodal', 'computer_use', 'agent_loop'),
        priority=1,
        benchmark_ids=('osworld',),
        platform_pressure=('participant/agent', 'environment/gui', 'model/request', 'execution', 'reliability/recovery', 'observability/telemetry'),
        method_owned=('visual grounding and normalized coordinate semantics', 'desktop action grammar', 'multimodal conversation and loop policy'),
        platform_owned=('multimodal content transport', 'GUI action execution', 'bounded lifecycle', 'effect evidence', 'recovery and telemetry'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/ui_tars_desktop_v001/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/ui_tars_desktop_v001/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/ui_tars_desktop_v001/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/ui_tars_desktop_v001/scaffold.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=('matched execution still requires an exact immutable OSWorld task/harness cut plus deployment-qualified GUI and VLM bindings',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_ui_tars_desktop_v001.py', 'tests/test_scientific_ui_tars_method_program_v1.py'),
)

__all__ = ["REPRODUCTION"]
