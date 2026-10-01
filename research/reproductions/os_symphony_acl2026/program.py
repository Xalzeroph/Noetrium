from __future__ import annotations

METHOD_ID = "os_symphony_acl2026"

PAPER_URI = "https://aclanthology.org/2026.acl-long.1021/"

BENCHMARK_IDS = ("osworld-verified", "windowsagentarena", "macosarena")

PROTOCOL = ("match paper step budgets", "evaluate proprietary and open VLM backbones separately", "preserve browser-sandbox tutorial search and visual-context pruning", "record trajectory-level corrections in long-term memory")

METRICS = ("task_success_rate", "steps", "tutorial_search_count", "memory_corrections", "model_calls", "token_cost")

ABLATIONS = ("without reflection-memory agent", "without multimodal searcher", "without visual-history pruning")

PHASES = (
    {
        "phase_id": 'orchestrate',
        "role": 'os_symphony.orchestrator',
        "instruction": 'Route work between reflection-memory and versatile tool agents.',
    },
    {
        "phase_id": 'retrieve_milestones',
        "role": 'os_symphony.memory',
        "instruction": 'Retrieve milestone-driven long-term trajectory memory.',
    },
    {
        "phase_id": 'search_tutorial',
        "role": 'os_symphony.searcher',
        "instruction": 'Use a SeeAct multimodal browser searcher to synthesize a visually aligned tutorial when needed.',
    },
    {
        "phase_id": 'execute',
        "role": 'os_symphony.tool_agent',
        "instruction": 'Execute the next computer action using current tutorial and memory context.',
    },
    {
        "phase_id": 'reflect',
        "role": 'os_symphony.memory',
        "instruction": 'Curate/prune visual history and record trajectory-level corrective memory.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'os_symphony_acl2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'ACL 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=100)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
