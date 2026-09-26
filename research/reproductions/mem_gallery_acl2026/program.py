from __future__ import annotations

METHOD_ID = "mem_gallery_acl2026"

PAPER_URI = "https://aclanthology.org/2026.acl-long.1892/"

BENCHMARK_IDS = ("mem-gallery",)

PROTOCOL = ("reproduce all three functional evaluation dimensions", "benchmark the twelve final-paper memory systems under matched context budgets", "retain image/text dependencies across sessions", "report capability and efficiency separately")

METRICS = ("memory_extraction", "test_time_adaptation", "memory_reasoning", "knowledge_management", "token_efficiency", "latency")

ABLATIONS = ("text-only history", "no explicit multimodal retention", "no memory organization")

PHASES = (
    {
        "phase_id": 'session_ingest',
        "role": 'mem_gallery.evaluator',
        "instruction": 'Replay the frozen multimodal multi-session conversation history.',
    },
    {
        "phase_id": 'memory_extract_adapt',
        "role": 'mem_gallery.evaluator',
        "instruction": 'Evaluate memory extraction and test-time adaptation.',
    },
    {
        "phase_id": 'memory_reason',
        "role": 'mem_gallery.evaluator',
        "instruction": 'Evaluate reasoning over cross-session multimodal memories.',
    },
    {
        "phase_id": 'knowledge_manage',
        "role": 'mem_gallery.evaluator',
        "instruction": 'Evaluate organization and evolution of memory knowledge.',
    },
    {
        "phase_id": 'score',
        "role": 'mem_gallery.evaluator',
        "instruction": 'Aggregate functional capability and efficiency measurements.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'mem_gallery_acl2026.phase-workflow.v1',
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
