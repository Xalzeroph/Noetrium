from __future__ import annotations

from .fidelity import OPENWEBVOYAGER_FIDELITY

OPENWEBVOYAGER_PHASES = (
    {
        "phase_id": 'imitate',
        "role": 'openwebvoyager.imitate',
        "instruction": 'Warm-start a multimodal web policy from imitation trajectories.',
    },
    {
        "phase_id": 'explore',
        "role": 'openwebvoyager.explore',
        "instruction": 'Explore real websites and collect new task trajectories.',
    },
    {
        "phase_id": 'judge',
        "role": 'openwebvoyager.judge',
        "instruction": 'Score trajectories with an external general-purpose judge.',
    },
    {
        "phase_id": 'filter',
        "role": 'openwebvoyager.filter',
        "instruction": 'Retain successful trajectories as improved training evidence.',
    },
    {
        "phase_id": 'optimize',
        "role": 'openwebvoyager.optimize',
        "instruction": 'Update the policy and continue the exploration-feedback-optimization cycle.',
    },
)

METHOD_SPEC = {
    "method_id": 'openwebvoyager',
    "version": '2025-paper-protocol',
    "semantic_contract": 'openwebvoyager.phase-workflow.v1',
    "entrypoint": OPENWEBVOYAGER_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': OPENWEBVOYAGER_FIDELITY.paper_uri, 'venue': OPENWEBVOYAGER_FIDELITY.venue, 'year': OPENWEBVOYAGER_FIDELITY.year, 'benchmark_ids': OPENWEBVOYAGER_FIDELITY.benchmark_ids})
    method.policy(evidence=('openwebvoyager.phase-transcript', 'openwebvoyager.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('openwebvoyager_trajectory',))
    method.phases(OPENWEBVOYAGER_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'OPENWEBVOYAGER_PHASES']
