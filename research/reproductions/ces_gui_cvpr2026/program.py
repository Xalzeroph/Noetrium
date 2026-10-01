from __future__ import annotations

METHOD_ID="ces_gui_cvpr2026"

TITLE="Training High-Level Schedulers with Execution-Feedback Reinforcement Learning for Long-Horizon GUI Automation"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Deng_Training_High-Level_Schedulers_with_Execution-Feedback_Reinforcement_Learning_for_Long-Horizon_GUI_CVPR_2026_paper.html"

BENCHMARK_IDS=("aitz", "amex", "gui-odyssey")

PROTOCOL=("warm-start Coordinator and State Tracker with SFT", "stage RL by training Coordinator first with frozen Executor, then train State Tracker with Coordinator and Executor frozen", "use execution feedback rather than imitation-only scores as the high-level reward signal", "evaluate AITZ, AMEX and GUI-Odyssey long-horizon tasks separately")

METRICS=("task_success", "type_accuracy", "grounding_rate", "state_loss_rate", "steps", "context_tokens")

ABLATIONS=("without Coordinator", "without State Tracker", "without execution-feedback RL", "single-agent unified policy")

PHASES = (
    {
        "phase_id": 'coordinate',
        "role": 'ces.coordinator',
        "instruction": 'Read the user goal, current screen and compressed task state; emit one atomic sub-instruction.',
    },
    {
        "phase_id": 'execute',
        "role": 'ces.executor',
        "instruction": 'Use the frozen low-level GUI executor to reason over the sub-instruction and emit the concrete GUI action.',
    },
    {
        "phase_id": 'observe_feedback',
        "role": 'ces.executor',
        "instruction": 'Capture execution outcome and environment feedback after the GUI action.',
    },
    {
        "phase_id": 'track_state',
        "role": 'ces.state_tracker',
        "instruction": 'Compress previous state and execution feedback into an updated progress summary.',
    },
    {
        "phase_id": 'replan',
        "role": 'ces.coordinator',
        "instruction": 'Use the new state summary to continue, revise, or terminate the high-level plan.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'ces_gui_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=128)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
