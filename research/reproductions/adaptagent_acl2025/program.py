from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import ADAPTAGENT_FIDELITY

ADAPTAGENT_PHASES = (
    AgentPhaseSpec("select_demo", "adaptagent.select", "Select up to two demonstrations relevant to the unseen website or domain."),
    AgentPhaseSpec("encode_demo", "adaptagent.encode", "Encode multimodal screenshots and action demonstrations."),
    AgentPhaseSpec("adapt", "adaptagent.adapt", "Adapt the web agent in context or through the paper's meta-adaptation route."),
    AgentPhaseSpec("plan", "adaptagent.plan", "Plan the next website interaction from adapted context."),
    AgentPhaseSpec("act", "adaptagent.act", "Execute and observe the target website action."),
)

ADAPTAGENT_METHOD_PROGRAM = build_agent_phase_program(
    method_id="adaptagent",
    implementation_version="2025-paper-protocol",
    schema_version="adaptagent.phase-workflow.v1",
    phases=ADAPTAGENT_PHASES,
    configuration={
        "paper_uri": ADAPTAGENT_FIDELITY.paper_uri,
        "venue": ADAPTAGENT_FIDELITY.venue,
        "year": ADAPTAGENT_FIDELITY.year,
        "benchmark_ids": ADAPTAGENT_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("adaptagent.phase-transcript", "adaptagent.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("adaptagent_trajectory",),
)
__all__ = ["ADAPTAGENT_METHOD_PROGRAM", "ADAPTAGENT_PHASES"]
