from __future__ import annotations

from .fidelity import EMBODIED_VIDEOAGENT_FIDELITY

EMBODIED_VIDEOAGENT_PHASES = (
    {
        "phase_id": 'ingest',
        "role": 'embodied_videoagent.ingest',
        "instruction": 'Fuse egocentric RGB observations with embodied depth and pose sensing.',
    },
    {
        "phase_id": 'associate',
        "role": 'embodied_videoagent.associate',
        "instruction": 'Associate observations with persistent object identities in 3D.',
    },
    {
        "phase_id": 'update',
        "role": 'embodied_videoagent.update',
        "instruction": 'Use VLM reasoning to update object state when activities alter the scene.',
    },
    {
        "phase_id": 'retrieve',
        "role": 'embodied_videoagent.retrieve',
        "instruction": 'Retrieve persistent scene memory for reasoning or planning.',
    },
    {
        "phase_id": 'respond',
        "role": 'embodied_videoagent.respond',
        "instruction": 'Generate the embodied answer, interaction or manipulation plan.',
    },
)

METHOD_SPEC = {
    "method_id": 'embodied-videoagent',
    "version": '2025-paper-protocol',
    "semantic_contract": 'embodied-videoagent.phase-workflow.v1',
    "entrypoint": EMBODIED_VIDEOAGENT_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': EMBODIED_VIDEOAGENT_FIDELITY.paper_uri, 'venue': EMBODIED_VIDEOAGENT_FIDELITY.venue, 'year': EMBODIED_VIDEOAGENT_FIDELITY.year, 'benchmark_ids': EMBODIED_VIDEOAGENT_FIDELITY.benchmark_ids})
    method.policy(evidence=('embodied-videoagent.phase-transcript', 'embodied-videoagent.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('embodied-videoagent_trajectory',))
    method.phases(EMBODIED_VIDEOAGENT_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'EMBODIED_VIDEOAGENT_PHASES']
