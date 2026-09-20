from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import OPENWEBVOYAGER_FIDELITY

OPENWEBVOYAGER_PHASES = (
    AgentPhaseSpec("imitate", "openwebvoyager.imitate", "Warm-start a multimodal web policy from imitation trajectories."),
    AgentPhaseSpec("explore", "openwebvoyager.explore", "Explore real websites and collect new task trajectories."),
    AgentPhaseSpec("judge", "openwebvoyager.judge", "Score trajectories with an external general-purpose judge."),
    AgentPhaseSpec("filter", "openwebvoyager.filter", "Retain successful trajectories as improved training evidence."),
    AgentPhaseSpec("optimize", "openwebvoyager.optimize", "Update the policy and continue the exploration-feedback-optimization cycle."),
)

OPENWEBVOYAGER_METHOD_PROGRAM = build_agent_phase_program(
    method_id="openwebvoyager",
    implementation_version="2025-paper-protocol",
    schema_version="openwebvoyager.phase-workflow.v1",
    phases=OPENWEBVOYAGER_PHASES,
    configuration={
        "paper_uri": OPENWEBVOYAGER_FIDELITY.paper_uri,
        "venue": OPENWEBVOYAGER_FIDELITY.venue,
        "year": OPENWEBVOYAGER_FIDELITY.year,
        "benchmark_ids": OPENWEBVOYAGER_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("openwebvoyager.phase-transcript", "openwebvoyager.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("openwebvoyager_trajectory",),
)
__all__ = ["OPENWEBVOYAGER_METHOD_PROGRAM", "OPENWEBVOYAGER_PHASES"]
