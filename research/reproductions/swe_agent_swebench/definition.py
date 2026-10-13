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
    primary_executable="research/reproductions/swe_agent_swebench/program.py",
    reported_results=(
        ReportedResult(
            claim_id="swe_agent_swebench_pass_at_1",
            metric_id="pass_at_1_percent",
            value=12.5,
            qualifiers={
                "benchmark": "SWE-bench",
                "source": "NeurIPS 2024 abstract",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="noninteractive_swebench_prior_sota",
            description=(
                "Previous non-interactive language-model approaches surpassed "
                "by SWE-agent on SWE-bench in the NeurIPS 2024 paper."
            ),
            qualifiers={"source": "NeurIPS 2024 paper"},
        ),
    ),
    deltas=(
    ),
    blockers=('matched execution still requires exact paper-era model/prompt binding plus a deployment-qualified SWE-bench software environment cut',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)

__all__ = ["REPRODUCTION"]
