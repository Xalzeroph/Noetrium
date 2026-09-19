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
    package='metagpt_software_company',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='metagpt',
        title='MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework',
        paper_uri='https://proceedings.iclr.cc/paper_files/paper/2024/hash/6507b115562bb0a305f1958ccc87355a-Abstract-Conference.html',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('multi-agent', 'software-engineering'),
        families=('multi_agent', 'software_agent', 'sop', 'artifact_pipeline'),
        priority=1,
        benchmark_ids=('humaneval',),
        platform_pressure=('execution/workflow', 'participant/agent', 'environment/software', 'artifact/lineage', 'execution', 'experimentation/study'),
        method_owned=('software-company role specialization', 'SOP dependency graph', 'artifact-to-role workflow semantics'),
        platform_owned=('participant topology', 'message transport', 'software workspace execution', 'artifact lineage', 'bounded orchestration', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/metagpt_software_company/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/metagpt_software_company/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/metagpt_software_company/study.py',
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
    scientific_tests=('tests/test_scientific_metagpt_fidelity_v1.py', 'tests/test_scientific_metagpt_method_program_v1.py', 'tests/test_scientific_metagpt_humaneval_study_v1.py', 'tests/test_scientific_humaneval_cut_v1.py'),
)

__all__ = ["REPRODUCTION"]
