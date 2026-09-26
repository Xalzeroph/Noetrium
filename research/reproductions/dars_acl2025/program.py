from __future__ import annotations

from .fidelity import DARS_FIDELITY

DARS_PHASES = (
    {
        "phase_id": 'rollout',
        "role": 'dars.rollout',
        "instruction": 'Execute a coding-agent trajectory until success or a recoverable sub-optimal decision.',
    },
    {
        "phase_id": 'branch',
        "role": 'dars.branch',
        "instruction": 'Identify a prior decision point using execution history and feedback.',
    },
    {
        "phase_id": 'resample',
        "role": 'dars.resample',
        "instruction": 'Sample an alternative action conditioned on history and execution feedback.',
    },
    {
        "phase_id": 'replay',
        "role": 'dars.replay',
        "instruction": 'Traverse the alternative software-agent branch from the selected decision point.',
    },
    {
        "phase_id": 'select',
        "role": 'dars.select',
        "instruction": 'Aggregate branch outcomes and select the best repair trajectory.',
    },
)

METHOD_SPEC = {
    "method_id": 'dars',
    "version": '2025-paper-protocol',
    "semantic_contract": 'dars.phase-workflow.v1',
    "entrypoint": DARS_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': DARS_FIDELITY.paper_uri, 'venue': DARS_FIDELITY.venue, 'year': DARS_FIDELITY.year, 'benchmark_ids': DARS_FIDELITY.benchmark_ids})
    method.policy(evidence=('dars.phase-transcript', 'dars.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('dars_trajectory',))
    method.phases(DARS_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'DARS_PHASES']
