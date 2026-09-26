from __future__ import annotations

from .fidelity import CER_FIDELITY

CER_PHASES = (
    {
        "phase_id": 'retrieve_experience',
        "role": 'cer.retrieve',
        "instruction": 'Retrieve contextualized successful and failed prior interaction experiences.',
    },
    {
        "phase_id": 'adapt_context',
        "role": 'cer.context',
        "instruction": 'Construct compact experience-conditioned context for the current task.',
    },
    {
        "phase_id": 'act',
        "role": 'cer.act',
        "instruction": 'Execute the next language-agent action under replay-conditioned context.',
    },
    {
        "phase_id": 'evaluate',
        "role": 'cer.evaluate',
        "instruction": 'Evaluate trajectory progress and task outcome.',
    },
    {
        "phase_id": 'store_experience',
        "role": 'cer.store',
        "instruction": 'Store the contextualized experience for future self-improvement.',
    },
)

METHOD_SPEC = {
    "method_id": 'contextual-experience-replay',
    "version": '2025-paper-protocol',
    "semantic_contract": 'contextual-experience-replay.phase-workflow.v1',
    "entrypoint": CER_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': CER_FIDELITY.paper_uri, 'venue': CER_FIDELITY.venue, 'year': CER_FIDELITY.year, 'benchmark_ids': CER_FIDELITY.benchmark_ids})
    method.policy(evidence=('contextual-experience-replay.phase-transcript', 'contextual-experience-replay.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('contextual-experience-replay_trajectory',))
    method.phases(CER_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'CER_PHASES']
