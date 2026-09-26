from __future__ import annotations

from .fidelity import LVAGENT_FIDELITY

LVAGENT_PHASES = (
    {
        "phase_id": 'select_team',
        "role": 'lvagent.select',
        "instruction": 'Select a complementary MLLM agent team for the current long-video task.',
    },
    {
        "phase_id": 'perceive',
        "role": 'lvagent.perceive',
        "instruction": 'Retrieve critical temporal segments while controlling video-context cost.',
    },
    {
        "phase_id": 'discuss',
        "role": 'lvagent.discuss',
        "instruction": 'Have agents answer and exchange reasons for the current question.',
    },
    {
        "phase_id": 'reflect',
        "role": 'lvagent.reflect',
        "instruction": 'Evaluate per-agent behavior and update the collaboration configuration.',
    },
    {
        "phase_id": 'consensus',
        "role": 'lvagent.consensus',
        "instruction": 'Aggregate the final answer after multi-round collaboration.',
    },
)

METHOD_SPEC = {
    "method_id": 'lvagent',
    "version": '2025-paper-protocol',
    "semantic_contract": 'lvagent.phase-workflow.v1',
    "entrypoint": LVAGENT_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': LVAGENT_FIDELITY.paper_uri, 'venue': LVAGENT_FIDELITY.venue, 'year': LVAGENT_FIDELITY.year, 'benchmark_ids': LVAGENT_FIDELITY.benchmark_ids})
    method.policy(evidence=('lvagent.phase-transcript', 'lvagent.model-receipts'), metrics=('task_success', 'agent_phase_count'), artifacts=('lvagent_trajectory',))
    method.phases(LVAGENT_PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'LVAGENT_PHASES']
