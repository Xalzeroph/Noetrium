from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import VIDEOARM_FIDELITY

VIDEOARM_PHASES = (
    AgentPhaseSpec("observe", "videoarm.observe", "Observe coarse global video evidence and the current hierarchical memory."),
    AgentPhaseSpec("think", "videoarm.think", "Reason about the question and decide which evidence operation should run next."),
    AgentPhaseSpec("act", "videoarm.act", "Use the selected coarse-to-fine video or audio interpretation operation."),
    AgentPhaseSpec("memorize", "videoarm.memorize", "Insert and compress newly acquired multimodal evidence into hierarchical memory."),
    AgentPhaseSpec("answer", "videoarm.answer", "Integrate hierarchical evidence and produce the final answer."),
)

VIDEOARM_METHOD_PROGRAM = build_agent_phase_program(
    method_id="videoarm",
    implementation_version="2026-paper-protocol",
    schema_version="videoarm.phase-workflow.v1",
    phases=VIDEOARM_PHASES,
    configuration={
        "paper_uri": VIDEOARM_FIDELITY.paper_uri,
        "venue": VIDEOARM_FIDELITY.venue,
        "year": VIDEOARM_FIDELITY.year,
        "benchmark_ids": VIDEOARM_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("videoarm.phase-transcript", "videoarm.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("videoarm_trajectory",),
)
__all__ = ["VIDEOARM_METHOD_PROGRAM", "VIDEOARM_PHASES"]
