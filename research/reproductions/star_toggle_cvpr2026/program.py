from __future__ import annotations

METHOD_ID="star_toggle_cvpr2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html"

BENCHMARK_IDS=("state-control-benchmark",)

PROTOCOL=("evaluate all four multimodal agents from the final paper", "separate already-correct-state cases from required-toggle cases", "run the three additional public agentic benchmarks", "evaluate the dynamic environment separately")

METRICS=("toggle_execution_accuracy", "task_success", "false_action_rate", "grounding_accuracy", "steps")

ABLATIONS=("without explicit current-state perception", "without desired-state inference", "always-act policy")

PHASES = (
    {
        "phase_id": 'see',
        "role": 'star.perception',
        "instruction": 'Perceive the current binary toggle state from the GUI.',
    },
    {
        "phase_id": 'think_goal',
        "role": 'star.reasoner',
        "instruction": 'Infer the desired toggle state from the user instruction.',
    },
    {
        "phase_id": 'compare',
        "role": 'star.reasoner',
        "instruction": 'Compare current and desired states and decide whether interaction is required.',
    },
    {
        "phase_id": 'act_or_noop',
        "role": 'star.agent',
        "instruction": 'Execute the toggle action only when a state transition is required.',
    },
    {
        "phase_id": 'verify',
        "role": 'star.perception',
        "instruction": 'Verify the post-action state and retain evidence.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'star_toggle_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'CVPR 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
