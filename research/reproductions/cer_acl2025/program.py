from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
from .fidelity import CER_FIDELITY

CER_PHASES = (
    AgentPhaseSpec("retrieve_experience", "cer.retrieve", "Retrieve contextualized successful and failed prior interaction experiences."),
    AgentPhaseSpec("adapt_context", "cer.context", "Construct compact experience-conditioned context for the current task."),
    AgentPhaseSpec("act", "cer.act", "Execute the next language-agent action under replay-conditioned context."),
    AgentPhaseSpec("evaluate", "cer.evaluate", "Evaluate trajectory progress and task outcome."),
    AgentPhaseSpec("store_experience", "cer.store", "Store the contextualized experience for future self-improvement."),
)

CER_METHOD_PROGRAM = build_agent_phase_program(
    method_id="contextual-experience-replay",
    implementation_version="2025-paper-protocol",
    schema_version="contextual-experience-replay.phase-workflow.v1",
    phases=CER_PHASES,
    configuration={
        "paper_uri": CER_FIDELITY.paper_uri,
        "venue": CER_FIDELITY.venue,
        "year": CER_FIDELITY.year,
        "benchmark_ids": CER_FIDELITY.benchmark_ids,
    },
    evidence_obligations=("contextual-experience-replay.phase-transcript", "contextual-experience-replay.model-receipts"),
    metric_names=("task_success", "agent_phase_count"),
    artifact_kinds=("contextual-experience-replay_trajectory",),
)
__all__ = ["CER_METHOD_PROGRAM", "CER_PHASES"]
