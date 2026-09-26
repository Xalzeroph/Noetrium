from __future__ import annotations

from .fidelity import VIDEOARM_FIDELITY

VIDEOARM_PHASES = (
    {
        "phase_id": 'observe',
        "role": 'videoarm.observe',
        "instruction": 'Observe coarse global video evidence and the current hierarchical memory.',
    },
    {
        "phase_id": 'think',
        "role": 'videoarm.think',
        "instruction": 'Reason about the question and decide which evidence operation should run next.',
    },
    {
        "phase_id": 'act',
        "role": 'videoarm.act',
        "instruction": 'Use the selected coarse-to-fine video or audio interpretation operation.',
    },
    {
        "phase_id": 'memorize',
        "role": 'videoarm.memorize',
        "instruction": 'Insert and compress newly acquired multimodal evidence into hierarchical memory.',
    },
    {
        "phase_id": 'answer',
        "role": 'videoarm.answer',
        "instruction": 'Integrate hierarchical evidence and produce the final answer.',
    },
)

METHOD_SPEC = {
    "method_id": 'videoarm',
    "version": '2026-paper-protocol',
    "semantic_contract": 'videoarm.phase-workflow.v1',
    "entrypoint": VIDEOARM_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': VIDEOARM_FIDELITY.paper_uri, 'venue': VIDEOARM_FIDELITY.venue, 'year': VIDEOARM_FIDELITY.year, 'benchmark_ids': VIDEOARM_FIDELITY.benchmark_ids})
    method.policy(evidence=('videoarm.phase-transcript', 'videoarm.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('videoarm_trajectory',))
    method.phases(VIDEOARM_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'VIDEOARM_PHASES']
