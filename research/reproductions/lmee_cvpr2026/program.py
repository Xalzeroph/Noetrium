from __future__ import annotations

METHOD_ID="lmee_cvpr2026"

TITLE="Explore with Long-term Memory: A Benchmark and Multimodal LLM-based Reinforcement Learning Framework for Embodied Exploration"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Explore_with_Long-term_Memory_A_Benchmark_and_Multimodal_LLM-based_Reinforcement_CVPR_2026_paper.html"

BENCHMARK_IDS=("lmee-bench",)

PROTOCOL=("reproduce LMEE-Bench multi-goal navigation and memory-based QA", "freeze HM3D-Sem train/val environment identity", "reproduce the released MemoryExplorer reinforcement-learning setup", "evaluate exploration process and final-task outcomes separately")

METRICS=("navigation_success", "memory_qa_accuracy", "exploration_efficiency", "memory_retrieval_quality", "steps", "context_tokens")

ABLATIONS=("without long-term memory", "without memory retrieval", "without reinforcement learning", "short-context memory only")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'lmee.agent',
        "instruction": 'Observe the embodied scene and current long-term episodic memory.',
    },
    {
        "phase_id": 'memory_retrieve',
        "role": 'lmee.memory',
        "instruction": 'Retrieve task-relevant historical visual episodes and memory-based evidence.',
    },
    {
        "phase_id": 'explore_plan',
        "role": 'lmee.agent',
        "instruction": 'Plan exploration toward current navigation and memory-QA objectives.',
    },
    {
        "phase_id": 'act',
        "role": 'lmee.agent',
        "instruction": 'Execute the selected embodied exploration action.',
    },
    {
        "phase_id": 'memory_update',
        "role": 'lmee.memory',
        "instruction": 'Append and consolidate new visual experience into long-term episodic memory.',
    },
    {
        "phase_id": 'answer_or_continue',
        "role": 'lmee.agent',
        "instruction": 'Answer memory-based questions when sufficient evidence exists or continue exploration.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'lmee_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=128)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
