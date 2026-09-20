from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from .fidelity import EMBODIED_VIDEOAGENT_FIDELITY

EMBODIED_VIDEOAGENT_PHASES = (
    AgentPhaseSpec("ingest", "embodied_videoagent.ingest", "Fuse egocentric RGB observations with embodied depth and pose sensing."),
    AgentPhaseSpec("associate", "embodied_videoagent.associate", "Associate observations with persistent object identities in 3D."),
    AgentPhaseSpec("update", "embodied_videoagent.update", "Use VLM reasoning to update object state when activities alter the scene."),
    AgentPhaseSpec("retrieve", "embodied_videoagent.retrieve", "Retrieve persistent scene memory for reasoning or planning."),
    AgentPhaseSpec("respond", "embodied_videoagent.respond", "Generate the embodied answer, interaction or manipulation plan."),
)

EMBODIED_VIDEOAGENT_METHOD_PROGRAM = AgentMethodSpec(
    method_id="embodied-videoagent",
    implementation_version="2025-paper-protocol",
    schema_version="embodied-videoagent.phase-workflow.v1",
    phases=EMBODIED_VIDEOAGENT_PHASES,
    configuration={
        "paper_uri": EMBODIED_VIDEOAGENT_FIDELITY.paper_uri,
        "venue": EMBODIED_VIDEOAGENT_FIDELITY.venue,
        "year": EMBODIED_VIDEOAGENT_FIDELITY.year,
        "benchmark_ids": EMBODIED_VIDEOAGENT_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("embodied-videoagent.phase-transcript", "embodied-videoagent.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("embodied-videoagent_trajectory",),
).compile()
__all__ = ["EMBODIED_VIDEOAGENT_METHOD_PROGRAM", "EMBODIED_VIDEOAGENT_PHASES"]
