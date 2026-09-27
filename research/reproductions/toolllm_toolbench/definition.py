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
    ReproductionMethodConfigurerBinding,
)

REPRODUCTION = ReproductionDefinition(
    package='toolllm_toolbench',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='toolllm',
        title='ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs',
        paper_uri='https://proceedings.iclr.cc/paper_files/paper/2024/hash/28e50ee5b72e90b50e7196fde8ea260e-Abstract-Conference.html',
        year=2024,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('tool-use', 'training'),
        families=('tool_use', 'retrieval', 'search', 'api_agent'),
        priority=1,
        benchmark_ids=('toolbench',),
        platform_pressure=('participant/capability', 'data/projection', 'data/query', 'model/request', 'execution', 'observability/telemetry'),
        method_owned=('API Retriever task-conditioned top-k policy', 'function-schema materialization and Finish injection semantics', 'DFSDT tool-search policy'),
        platform_owned=('capability descriptor authority', 'semantic projection and query', 'capability invocation and effect evidence', 'evaluation'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/toolllm_toolbench/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/toolllm_toolbench/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/toolllm_toolbench/study.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/toolllm_toolbench/search.py',
        ),
    ),
    method_configurer=ReproductionMethodConfigurerBinding(
        qualname="build_toolllm_toolbench_method_program",
        kwargs={"retrieval_mode": "oracle"},
        unresolved_parameters=("capability_ids",),
    ),
    primary_executable="research/reproductions/toolllm_toolbench/program.py",
    reported_results=(
        ReportedResult(
            claim_id="toolllama_dfsdt_average_pass",
            metric_id="average_pass_rate_percent",
            value=66.7,
            qualifiers={"benchmark": "toolbench", "model": "toollama", "inference": "dfsdt", "source": "ICLR-2024 paper Table 4"},
        ),
        ReportedResult(
            claim_id="toolllama_dfsdt_average_win",
            metric_id="average_win_rate_percent",
            value=60.0,
            qualifiers={"benchmark": "toolbench", "model": "toollama", "inference": "dfsdt", "source": "ICLR-2024 paper Table 4"},
        ),
        ReportedResult(
            claim_id="toolllama_dfsdt_retriever_average_pass",
            metric_id="average_pass_rate_percent",
            value=67.3,
            qualifiers={"benchmark": "toolbench", "model": "toollama", "inference": "dfsdt-retriever", "source": "ICLR-2024 paper Table 4"},
        ),
        ReportedResult(
            claim_id="toolllama_dfsdt_retriever_average_win",
            metric_id="average_win_rate_percent",
            value=63.1,
            qualifiers={"benchmark": "toolbench", "model": "toollama", "inference": "dfsdt-retriever", "source": "ICLR-2024 paper Table 4"},
        ),
        ReportedResult(
            claim_id="tooleval_pass_human_agreement",
            metric_id="human_agreement_percent",
            value=87.1,
            qualifiers={"evaluation": "pass-rate", "source": "ICLR-2024 paper evaluator analysis"},
        ),
        ReportedResult(
            claim_id="tooleval_win_human_agreement",
            metric_id="human_agreement_percent",
            value=80.3,
            qualifiers={"evaluation": "win-rate", "source": "ICLR-2024 paper evaluator analysis"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="chatgpt_react_toolbench",
            description="ChatGPT ReAct baseline reported in ToolBench.",
            qualifiers={"average_pass_rate_percent": 40.2, "source": "ICLR-2024 paper Table 4"},
        ),
        ReferenceBaseline(
            baseline_id="gpt4_dfsdt_toolbench",
            description="GPT-4 DFSDT comparison reported in ToolBench.",
            qualifiers={"average_pass_rate_percent": 71.1, "average_win_rate_percent": 70.4, "source": "ICLR-2024 paper Table 4"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "Paper Table 4 combines ToolLLaMA checkpoint identity, "
                "paper-era RapidAPI availability and ToolEval model judging. "
                "Those external identities are not fully content-addressed by "
                "the current executable Study."
            ),
        ),
    ),
    blockers=(
        "the exact paper-era ToolLLaMA checkpoint used for Table 4 must be "
        "materialized under immutable model identity",
        "the paper-era RapidAPI inventory, availability and response behavior "
        "must be frozen before matched ToolBench execution",
        "ToolEval pass/win claims require the historical evaluator model and "
        "prompt/service revisions under immutable authority",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_toolllm_dfsdt_v1.py', 'tests/test_scientific_toolbench_cut_v1.py'),
)

__all__ = ["REPRODUCTION"]
