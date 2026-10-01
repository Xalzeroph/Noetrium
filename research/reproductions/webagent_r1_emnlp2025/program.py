from __future__ import annotations

from .fidelity import WEBAGENT_R1_FIDELITY

WEBAGENT_R1_PHASES = (
    {
        "phase_id": 'warmup',
        "role": 'webagent_r1.warmup',
        "instruction": "Initialize the web policy with behavior cloning or the paper's zero/CoT alternative.",
    },
    {
        "phase_id": 'rollout',
        "role": 'webagent_r1.rollout',
        "instruction": 'Collect multi-turn web-interaction trajectories.',
    },
    {
        "phase_id": 'reward',
        "role": 'webagent_r1.reward',
        "instruction": 'Score end-to-end task success for reinforcement learning.',
    },
    {
        "phase_id": 'update',
        "role": 'webagent_r1.update',
        "instruction": 'Update the web policy using multi-turn RL trajectories.',
    },
    {
        "phase_id": 'test_scale',
        "role": 'webagent_r1.test',
        "instruction": 'Run increased-interaction test-time scaling on WebArena-Lite tasks.',
    },
)

METHOD_SPEC = {
    "method_id": 'webagent-r1',
    "version": '2025-paper-protocol',
    "semantic_contract": 'webagent-r1.phase-workflow.v1',
    "entrypoint": WEBAGENT_R1_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': WEBAGENT_R1_FIDELITY.paper_uri, 'venue': WEBAGENT_R1_FIDELITY.venue, 'year': WEBAGENT_R1_FIDELITY.year, 'benchmark_ids': WEBAGENT_R1_FIDELITY.benchmark_ids})
    method.policy(evidence=('webagent-r1.phase-transcript', 'webagent-r1.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('webagent-r1_trajectory',))
    method.phases(WEBAGENT_R1_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'WEBAGENT_R1_PHASES']
