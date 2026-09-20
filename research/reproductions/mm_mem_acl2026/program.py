from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import (
    AgentPhaseSpec,
    build_agent_cycle_program,
    build_agent_phase_program,
)

METHOD_ID = "mm_mem_acl2026"
PAPER_URI = "https://aclanthology.org/2026.acl-long.533/"
BENCHMARK_IDS = ("video-mme", "hd-epic", "mlvu", "vstream-qa")
PROTOCOL = ("train SIB-GRPO decisions over ADD_NEW/MERGE/DISCARD", "preserve VQA correctness plus supervisor plus caption-length reward", "evaluate offline and streaming benchmarks separately", "report memory compression and latency with task quality")
METRICS = ("qa_accuracy", "streaming_score", "memory_tokens", "compression_ratio", "latency", "memory_action_distribution")
ABLATIONS = ("without SIB-GRPO", "without symbolic schema", "without entropy retrieval", "single-level memory")
PHASES = (
    AgentPhaseSpec("sensory_buffer", "mm_mem.encoder", "Encode incoming visual evidence into fine-grained sensory traces."),
    AgentPhaseSpec("episodic_stream", "mm_mem.memory", "Distill sensory traces into an episodic stream while preserving task-relevant evidence."),
    AgentPhaseSpec("symbolic_schema", "mm_mem.memory", "Compress episodic evidence into high-level symbolic gist schemas."),
    AgentPhaseSpec("sib_decision", "mm_mem.policy", "Choose ADD_NEW, MERGE, or DISCARD under the Semantic Information Bottleneck objective."),
    AgentPhaseSpec("topdown_retrieval", "mm_mem.retriever", "Retrieve memory top-down using entropy-driven adaptive selection."),
    AgentPhaseSpec("answer", "mm_mem.reasoner", "Answer the video query from retrieved multimodal memory."),
)

METHOD_PROGRAM = build_agent_phase_program(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="mm_mem_acl2026.phase-workflow.v1",
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
)

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
