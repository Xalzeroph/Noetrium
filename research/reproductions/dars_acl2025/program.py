from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import DARS_FIDELITY

DARS_PHASES = (
    AgentPhaseSpec("rollout", "dars.rollout", "Execute a coding-agent trajectory until success or a recoverable sub-optimal decision."),
    AgentPhaseSpec("branch", "dars.branch", "Identify a prior decision point using execution history and feedback."),
    AgentPhaseSpec("resample", "dars.resample", "Sample an alternative action conditioned on history and execution feedback."),
    AgentPhaseSpec("replay", "dars.replay", "Traverse the alternative software-agent branch from the selected decision point."),
    AgentPhaseSpec("select", "dars.select", "Aggregate branch outcomes and select the best repair trajectory."),
)

DARS_METHOD_PROGRAM = build_agent_phase_program(
    method_id="dars",
    implementation_version="2025-paper-protocol",
    schema_version="dars.phase-workflow.v1",
    phases=DARS_PHASES,
    configuration={
        "paper_uri": DARS_FIDELITY.paper_uri,
        "venue": DARS_FIDELITY.venue,
        "year": DARS_FIDELITY.year,
        "benchmark_ids": DARS_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("dars.phase-transcript", "dars.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("dars_trajectory",),
)
__all__ = ["DARS_METHOD_PROGRAM", "DARS_PHASES"]
