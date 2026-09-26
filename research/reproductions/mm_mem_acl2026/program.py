from __future__ import annotations

METHOD_ID = "mm_mem_acl2026"

PAPER_URI = "https://aclanthology.org/2026.acl-long.533/"

BENCHMARK_IDS = ("video-mme", "hd-epic", "mlvu", "vstream-qa")

PROTOCOL = ("train SIB-GRPO decisions over ADD_NEW/MERGE/DISCARD", "preserve VQA correctness plus supervisor plus caption-length reward", "evaluate offline and streaming benchmarks separately", "report memory compression and latency with task quality")

METRICS = ("qa_accuracy", "streaming_score", "memory_tokens", "compression_ratio", "latency", "memory_action_distribution")

ABLATIONS = ("without SIB-GRPO", "without symbolic schema", "without entropy retrieval", "single-level memory")

PHASES = (
    {
        "phase_id": 'sensory_buffer',
        "role": 'mm_mem.encoder',
        "instruction": 'Encode incoming visual evidence into fine-grained sensory traces.',
    },
    {
        "phase_id": 'episodic_stream',
        "role": 'mm_mem.memory',
        "instruction": 'Distill sensory traces into an episodic stream while preserving task-relevant evidence.',
    },
    {
        "phase_id": 'symbolic_schema',
        "role": 'mm_mem.memory',
        "instruction": 'Compress episodic evidence into high-level symbolic gist schemas.',
    },
    {
        "phase_id": 'sib_decision',
        "role": 'mm_mem.policy',
        "instruction": 'Choose ADD_NEW, MERGE, or DISCARD under the Semantic Information Bottleneck objective.',
    },
    {
        "phase_id": 'topdown_retrieval',
        "role": 'mm_mem.retriever',
        "instruction": 'Retrieve memory top-down using entropy-driven adaptive selection.',
    },
    {
        "phase_id": 'answer',
        "role": 'mm_mem.reasoner',
        "instruction": 'Answer the video query from retrieved multimodal memory.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'mm_mem_acl2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'ACL 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
