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
    package='swe_agent_swebench',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='swe-agent',
        title='SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering',
        paper_uri='https://proceedings.neurips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('software-engineering', 'tool-use'),
        families=('software_agent', 'tool_use', 'agent_computer_interface'),
        priority=1,
        benchmark_ids=('swe-bench',),
        platform_pressure=('participant/agent', 'environment/software', 'execution', 'reliability/recovery', 'observability/telemetry'),
        method_owned=('agent-computer interface design', 'software navigation policy'),
        platform_owned=('software environment', 'tool execution', 'checkpoint and recovery', 'telemetry'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/swe_agent_swebench/aci.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/swe_agent_swebench/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/swe_agent_swebench/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/swe_agent_swebench/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/swe_agent_swebench/history.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
    ),
    blockers=('matched execution still requires exact paper-era model/prompt binding plus a deployment-qualified SWE-bench software environment cut',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_swe_agent_07_v1.py', 'tests/test_scientific_swe_agent_method_program_v1.py', 'tests/test_scientific_swe_agent_swebench_fidelity_v1.py'),
)

__all__ = ["REPRODUCTION"]
