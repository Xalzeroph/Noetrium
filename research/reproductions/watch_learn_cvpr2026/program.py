from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from .fidelity import WATCH_AND_LEARN_FIDELITY

WATCH_AND_LEARN_PHASES = (
    AgentPhaseSpec("retrieve_video", "watch_learn.retrieve", "Retrieve task-relevant online human computer-use videos."),
    AgentPhaseSpec("inverse_dynamics", "watch_learn.inverse", "Infer executable user actions from consecutive screen states."),
    AgentPhaseSpec("label_trajectory", "watch_learn.label", "Construct and filter task-aware executable UI trajectories."),
    AgentPhaseSpec("condition_policy", "watch_learn.condition", "Inject retrieved trajectories as ICL exemplars or supervised training data."),
    AgentPhaseSpec("execute", "watch_learn.execute", "Run the computer-use agent on the target task."),
)

WATCH_AND_LEARN_METHOD_PROGRAM = AgentMethodSpec(
    method_id="watch-and-learn",
    implementation_version="2026-paper-protocol",
    schema_version="watch-and-learn.phase-workflow.v1",
    phases=WATCH_AND_LEARN_PHASES,
    configuration={
        "paper_uri": WATCH_AND_LEARN_FIDELITY.paper_uri,
        "venue": WATCH_AND_LEARN_FIDELITY.venue,
        "year": WATCH_AND_LEARN_FIDELITY.year,
        "benchmark_ids": WATCH_AND_LEARN_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("watch-and-learn.phase-transcript", "watch-and-learn.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("watch-and-learn_trajectory",),
).compile()
__all__ = ["WATCH_AND_LEARN_METHOD_PROGRAM", "WATCH_AND_LEARN_PHASES"]
