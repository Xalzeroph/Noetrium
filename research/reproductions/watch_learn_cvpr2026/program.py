from __future__ import annotations

from .fidelity import WATCH_AND_LEARN_FIDELITY

WATCH_AND_LEARN_PHASES = (
    {
        "phase_id": 'retrieve_video',
        "role": 'watch_learn.retrieve',
        "instruction": 'Retrieve task-relevant online human computer-use videos.',
    },
    {
        "phase_id": 'inverse_dynamics',
        "role": 'watch_learn.inverse',
        "instruction": 'Infer executable user actions from consecutive screen states.',
    },
    {
        "phase_id": 'label_trajectory',
        "role": 'watch_learn.label',
        "instruction": 'Construct and filter task-aware executable UI trajectories.',
    },
    {
        "phase_id": 'condition_policy',
        "role": 'watch_learn.condition',
        "instruction": 'Inject retrieved trajectories as ICL exemplars or supervised training data.',
    },
    {
        "phase_id": 'execute',
        "role": 'watch_learn.execute',
        "instruction": 'Run the computer-use agent on the target task.',
    },
)

METHOD_SPEC = {
    "method_id": 'watch-and-learn',
    "version": '2026-paper-protocol',
    "semantic_contract": 'watch-and-learn.phase-workflow.v1',
    "entrypoint": WATCH_AND_LEARN_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': WATCH_AND_LEARN_FIDELITY.paper_uri, 'venue': WATCH_AND_LEARN_FIDELITY.venue, 'year': WATCH_AND_LEARN_FIDELITY.year, 'benchmark_ids': WATCH_AND_LEARN_FIDELITY.benchmark_ids})
    method.policy(evidence=('watch-and-learn.phase-transcript', 'watch-and-learn.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('watch-and-learn_trajectory',))
    method.phases(WATCH_AND_LEARN_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'WATCH_AND_LEARN_PHASES']
