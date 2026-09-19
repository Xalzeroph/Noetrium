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
    package="flow_modularized_agentic_workflow",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="flow-modularized-agentic-workflow",
        title="Flow: Modularized Agentic Workflow Automation",
        paper_uri=(
            "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
            "ba84da6921f3040b74ee163aa7451f53-Abstract-Conference.html"
        ),
        year=2025,
        paper_revision="ICLR 2025 final paper",
    ),
    catalog=ReproductionCatalog(
        domains=("multi-agent", "planning-search", "runtime-systems"),
        families=(
            "multi_agent",
            "dynamic_workflow",
            "aov_graph",
            "workflow_refinement",
            "parallel_scheduling",
        ),
        priority=1,
        benchmark_ids=("flow-practical-tasks",),
        platform_pressure=(
            "execution/workflow",
            "execution/research_program",
            "execution/scheduling",
            "participant/agent",
            "experimentation/study",
            "artifact/lineage",
        ),
        method_owned=(
            "AOV workflow representation",
            "dependency-complexity and parallelism candidate selection",
            "dynamic subtask allocation",
            "history-conditioned workflow refinement",
            "lazy wait-for-active-tasks refinement strategy",
            "subtask completion validation",
        ),
        platform_owned=(
            "MethodProgram execution",
            "nested child ResearchMachine execution",
            "concurrent child-batch mechanics",
            "model invocation",
            "checkpoint and replay",
            "journal authority",
            "experiment compilation",
            "evidence and artifact lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/flow_modularized_agentic_workflow/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/flow_modularized_agentic_workflow/aov.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/flow_modularized_agentic_workflow/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/flow_modularized_agentic_workflow/subtask.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/flow_modularized_agentic_workflow/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="flow_three_task_average_success",
            metric_id="task_success_rate_percent",
            value=93.0,
            qualifiers={"tasks": "gobang, latex-beamer, website"},
        ),
        ReportedResult(
            claim_id="flow_three_task_average_human_rating",
            metric_id="human_rating_1_to_4",
            value=3.54,
            qualifiers={"human_participants": "50"},
        ),
        ReportedResult(
            claim_id="flow_gobang_success",
            metric_id="task_success_rate_percent",
            value=100.0,
            qualifiers={"task": "gobang-game-development"},
        ),
        ReportedResult(
            claim_id="flow_latex_success",
            metric_id="task_success_rate_percent",
            value=100.0,
            qualifiers={"task": "latex-beamer-writing"},
        ),
        ReportedResult(
            claim_id="flow_website_success",
            metric_id="task_success_rate_percent",
            value=80.0,
            qualifiers={"task": "website-design"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="autogen",
            description="AutoGen multi-agent framework baseline used by the ICLR paper",
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id="camel",
            description="CAMEL multi-agent framework baseline used by the ICLR paper",
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id="metagpt",
            description="MetaGPT multi-agent framework baseline used by the ICLR paper",
            qualifiers={},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The official repository commit used to freeze executable defaults "
                "post-dates the conference publication. The ICLR paper is the semantic "
                "authority; later code is used only for explicitly identified runner "
                "defaults and implementation details."
            ),
        ),
    ),
    blockers=(
        "exact historical GPT-4o-mini and GPT-3.5-Turbo service revisions are not immutable public model artifacts",
        "the paper reports five trials but does not publish an immutable stochastic seed schedule",
        "matched human-rating evidence requires the paper's 50-rater assignment and scoring protocol",
        "matched software/document outputs require frozen execution environments and verifier implementations for all three paper tasks",
        "no matched ICLR three-task execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_flow_modularized_workflow_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
