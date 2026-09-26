from __future__ import annotations

from .fidelity import R2D2_FIDELITY

R2D2_PHASES = (
    {
        "phase_id": 'remember',
        "role": 'r2d2.remember',
        "instruction": 'Store interaction history in the replay buffer.',
    },
    {
        "phase_id": 'replay',
        "role": 'r2d2.replay',
        "instruction": 'Replay memory to reconstruct a navigational map of visited web states.',
    },
    {
        "phase_id": 'decide',
        "role": 'r2d2.decide',
        "instruction": 'Choose the next action from the reconstructed map and task objective.',
    },
    {
        "phase_id": 'act',
        "role": 'r2d2.act',
        "instruction": 'Execute the action and record the transition.',
    },
    {
        "phase_id": 'reflect',
        "role": 'r2d2.reflect',
        "instruction": 'Analyze navigational mistakes and refine subsequent strategy.',
    },
)

METHOD_SPEC = {
    "method_id": 'r2d2',
    "version": '2025-paper-protocol',
    "semantic_contract": 'r2d2.phase-workflow.v1',
    "entrypoint": R2D2_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': R2D2_FIDELITY.paper_uri, 'venue': R2D2_FIDELITY.venue, 'year': R2D2_FIDELITY.year, 'benchmark_ids': R2D2_FIDELITY.benchmark_ids})
    method.policy(evidence=('r2d2.phase-transcript', 'r2d2.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('r2d2_trajectory',))
    method.phases(R2D2_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'R2D2_PHASES']
