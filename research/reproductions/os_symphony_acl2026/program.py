from __future__ import annotations

from noetrium.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID = "os_symphony_acl2026"
PAPER_URI = "https://aclanthology.org/2026.acl-long.1021/"
BENCHMARK_IDS = ("osworld-verified", "windowsagentarena", "macosarena")
PROTOCOL = ("match paper step budgets", "evaluate proprietary and open VLM backbones separately", "preserve browser-sandbox tutorial search and visual-context pruning", "record trajectory-level corrections in long-term memory")
METRICS = ("task_success_rate", "steps", "tutorial_search_count", "memory_corrections", "model_calls", "token_cost")
ABLATIONS = ("without reflection-memory agent", "without multimodal searcher", "without visual-history pruning")
PHASES = (
    AgentPhaseSpec("orchestrate", "os_symphony.orchestrator", "Route work between reflection-memory and versatile tool agents."),
    AgentPhaseSpec("retrieve_milestones", "os_symphony.memory", "Retrieve milestone-driven long-term trajectory memory."),
    AgentPhaseSpec("search_tutorial", "os_symphony.searcher", "Use a SeeAct multimodal browser searcher to synthesize a visually aligned tutorial when needed."),
    AgentPhaseSpec("execute", "os_symphony.tool_agent", "Execute the next computer action using current tutorial and memory context."),
    AgentPhaseSpec("reflect", "os_symphony.memory", "Curate/prune visual history and record trajectory-level corrective memory."),
)

METHOD_PROGRAM = AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="os_symphony_acl2026.phase-workflow.v1",
    phases=PHASES,
    max_cycles=100,
    configuration={
        "paper_uri": PAPER_URI,
        "venue": "ACL 2026",
        "benchmark_ids": BENCHMARK_IDS,
        "protocol": PROTOCOL,
        "ablations": ABLATIONS,
    },
    evidence_obligations=(
        METHOD_ID + ".phase-transcript",
        METHOD_ID + ".model-tool-receipts",
        METHOD_ID + ".metric-artifacts",
    ),
    metric_names=METRICS,
    artifact_kinds=(
        METHOD_ID + "_trajectory",
        METHOD_ID + "_experiment_manifest",
    ),
).compile()

__all__ = [
    "ABLATIONS",
    "BENCHMARK_IDS",
    "METHOD_ID",
    "METHOD_PROGRAM",
    "METRICS",
    "PAPER_URI",
    "PHASES",
    "PROTOCOL",
]
