from __future__ import annotations

METHOD_ID = "agemem_acl2026"

PAPER_URI = "https://aclanthology.org/2026.acl-long.981/"

BENCHMARK_IDS = ("alfworld", "scienceworld", "agentboard-pddl", "babyai", "hotpotqa")

PROTOCOL = ("evaluate Qwen2.5-7B-Instruct and Qwen3-4B-Instruct separately", "reproduce the three-stage progressive RL schedule", "reproduce step-wise GRPO memory-action optimization", "preserve identical benchmark access across memory baselines", "report per-benchmark and macro-average performance plus context efficiency")

METRICS = ("task_success", "average_score", "memory_quality", "context_tokens", "memory_action_count")

ABLATIONS = ("no reinforcement learning", "no long-term memory", "no short-term memory", "restricted memory action set")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'agemem.policy',
        "instruction": 'Observe task state plus current short-term and long-term memory.',
    },
    {
        "phase_id": 'memory_action',
        "role": 'agemem.policy',
        "instruction": 'Choose store, retrieve, update, summarize, discard, or no-op as a memory tool action.',
    },
    {
        "phase_id": 'apply_memory',
        "role": 'agemem.memory',
        "instruction": 'Apply the selected memory action while leaving memory authority to the platform.',
    },
    {
        "phase_id": 'reason_act',
        "role": 'agemem.policy',
        "instruction": 'Reason over the resulting memory view and emit the next environment action.',
    },
    {
        "phase_id": 'learn_signal',
        "role": 'agemem.training',
        "instruction": 'Record step-wise process/outcome signals required by progressive RL and step-wise GRPO.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'agemem_acl2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'ACL 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=128)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
