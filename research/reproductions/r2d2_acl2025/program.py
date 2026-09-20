from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from .fidelity import R2D2_FIDELITY

R2D2_PHASES = (
    AgentPhaseSpec("remember", "r2d2.remember", "Store interaction history in the replay buffer."),
    AgentPhaseSpec("replay", "r2d2.replay", "Replay memory to reconstruct a navigational map of visited web states."),
    AgentPhaseSpec("decide", "r2d2.decide", "Choose the next action from the reconstructed map and task objective."),
    AgentPhaseSpec("act", "r2d2.act", "Execute the action and record the transition."),
    AgentPhaseSpec("reflect", "r2d2.reflect", "Analyze navigational mistakes and refine subsequent strategy."),
)

R2D2_METHOD_PROGRAM = AgentMethodSpec(
    method_id="r2d2",
    implementation_version="2025-paper-protocol",
    schema_version="r2d2.phase-workflow.v1",
    phases=R2D2_PHASES,
    configuration={
        "paper_uri": R2D2_FIDELITY.paper_uri,
        "venue": R2D2_FIDELITY.venue,
        "year": R2D2_FIDELITY.year,
        "benchmark_ids": R2D2_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("r2d2.phase-transcript", "r2d2.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("r2d2_trajectory",),
).compile()
__all__ = ["R2D2_METHOD_PROGRAM", "R2D2_PHASES"]
