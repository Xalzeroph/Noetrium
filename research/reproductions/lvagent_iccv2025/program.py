from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from .fidelity import LVAGENT_FIDELITY

LVAGENT_PHASES = (
    AgentPhaseSpec("select_team", "lvagent.select", "Select a complementary MLLM agent team for the current long-video task."),
    AgentPhaseSpec("perceive", "lvagent.perceive", "Retrieve critical temporal segments while controlling video-context cost."),
    AgentPhaseSpec("discuss", "lvagent.discuss", "Have agents answer and exchange reasons for the current question."),
    AgentPhaseSpec("reflect", "lvagent.reflect", "Evaluate per-agent behavior and update the collaboration configuration."),
    AgentPhaseSpec("consensus", "lvagent.consensus", "Aggregate the final answer after multi-round collaboration."),
)

LVAGENT_METHOD_PROGRAM = AgentMethodSpec(
    method_id="lvagent",
    implementation_version="2025-paper-protocol",
    schema_version="lvagent.phase-workflow.v1",
    phases=LVAGENT_PHASES,
    configuration={
        "paper_uri": LVAGENT_FIDELITY.paper_uri,
        "venue": LVAGENT_FIDELITY.venue,
        "year": LVAGENT_FIDELITY.year,
        "benchmark_ids": LVAGENT_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("lvagent.phase-transcript", "lvagent.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("lvagent_trajectory",),
).compile()
__all__ = ["LVAGENT_METHOD_PROGRAM", "LVAGENT_PHASES"]
