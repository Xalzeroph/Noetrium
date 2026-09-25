from __future__ import annotations

from noetrium.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID = "agemem_acl2026"
PAPER_URI = "https://aclanthology.org/2026.acl-long.981/"
BENCHMARK_IDS = ("alfworld", "scienceworld", "agentboard-pddl", "babyai", "hotpotqa")
PROTOCOL = ("evaluate Qwen2.5-7B-Instruct and Qwen3-4B-Instruct separately", "reproduce the three-stage progressive RL schedule", "reproduce step-wise GRPO memory-action optimization", "preserve identical benchmark access across memory baselines", "report per-benchmark and macro-average performance plus context efficiency")
METRICS = ("task_success", "average_score", "memory_quality", "context_tokens", "memory_action_count")
ABLATIONS = ("no reinforcement learning", "no long-term memory", "no short-term memory", "restricted memory action set")
PHASES = (
    AgentPhaseSpec("observe", "agemem.policy", "Observe task state plus current short-term and long-term memory."),
    AgentPhaseSpec("memory_action", "agemem.policy", "Choose store, retrieve, update, summarize, discard, or no-op as a memory tool action."),
    AgentPhaseSpec("apply_memory", "agemem.memory", "Apply the selected memory action while leaving memory authority to the platform."),
    AgentPhaseSpec("reason_act", "agemem.policy", "Reason over the resulting memory view and emit the next environment action."),
    AgentPhaseSpec("learn_signal", "agemem.training", "Record step-wise process/outcome signals required by progressive RL and step-wise GRPO."),
)

METHOD_PROGRAM = AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="agemem_acl2026.phase-workflow.v1",
    phases=PHASES,
    max_cycles=128,
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
