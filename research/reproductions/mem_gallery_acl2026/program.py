from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID = "mem_gallery_acl2026"
PAPER_URI = "https://aclanthology.org/2026.acl-long.1892/"
BENCHMARK_IDS = ("mem-gallery",)
PROTOCOL = ("reproduce all three functional evaluation dimensions", "benchmark the twelve final-paper memory systems under matched context budgets", "retain image/text dependencies across sessions", "report capability and efficiency separately")
METRICS = ("memory_extraction", "test_time_adaptation", "memory_reasoning", "knowledge_management", "token_efficiency", "latency")
ABLATIONS = ("text-only history", "no explicit multimodal retention", "no memory organization")
PHASES = (
    AgentPhaseSpec("session_ingest", "mem_gallery.evaluator", "Replay the frozen multimodal multi-session conversation history."),
    AgentPhaseSpec("memory_extract_adapt", "mem_gallery.evaluator", "Evaluate memory extraction and test-time adaptation."),
    AgentPhaseSpec("memory_reason", "mem_gallery.evaluator", "Evaluate reasoning over cross-session multimodal memories."),
    AgentPhaseSpec("knowledge_manage", "mem_gallery.evaluator", "Evaluate organization and evolution of memory knowledge."),
    AgentPhaseSpec("score", "mem_gallery.evaluator", "Aggregate functional capability and efficiency measurements."),
)

METHOD_PROGRAM = AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="mem_gallery_acl2026.phase-workflow.v1",
    phases=PHASES,
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
