from __future__ import annotations

from .fidelity import ADAPTAGENT_FIDELITY

ADAPTAGENT_PHASES = (
    {
        "phase_id": 'select_demo',
        "role": 'adaptagent.select',
        "instruction": 'Select up to two demonstrations relevant to the unseen website or domain.',
    },
    {
        "phase_id": 'encode_demo',
        "role": 'adaptagent.encode',
        "instruction": 'Encode multimodal screenshots and action demonstrations.',
    },
    {
        "phase_id": 'adapt',
        "role": 'adaptagent.adapt',
        "instruction": "Adapt the web agent in context or through the paper's meta-adaptation route.",
    },
    {
        "phase_id": 'plan',
        "role": 'adaptagent.plan',
        "instruction": 'Plan the next website interaction from adapted context.',
    },
    {
        "phase_id": 'act',
        "role": 'adaptagent.act',
        "instruction": 'Execute and observe the target website action.',
    },
)

METHOD_SPEC = {
    "method_id": 'adaptagent',
    "version": '2025-paper-protocol',
    "semantic_contract": 'adaptagent.phase-workflow.v1',
    "entrypoint": ADAPTAGENT_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': ADAPTAGENT_FIDELITY.paper_uri, 'venue': ADAPTAGENT_FIDELITY.venue, 'year': ADAPTAGENT_FIDELITY.year, 'benchmark_ids': ADAPTAGENT_FIDELITY.benchmark_ids})
    method.policy(evidence=('adaptagent.phase-transcript', 'adaptagent.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('adaptagent_trajectory',))
    method.phases(ADAPTAGENT_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'ADAPTAGENT_PHASES']
