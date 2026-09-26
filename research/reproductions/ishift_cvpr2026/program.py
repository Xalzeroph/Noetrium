from __future__ import annotations

METHOD_ID="ishift_cvpr2026"

TITLE="iSHIFT: Lightweight Slow-Fast GUI Agent with Adaptive Perception"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Mehrotra_iSHIFT_Lightweight_Slow-Fast_GUI_Agent_with_Adaptive_Perception_CVPR_2026_paper.html"

BENCHMARK_IDS=("aitw", "androidcontrol", "gui-odyssey", "guiact")

PROTOCOL=("reproduce two-stage alignment then fine-tuning training pipeline", "preserve latent-thinking and perception-control special tokens", "evaluate AITW, GUI Odyssey, AndroidControl and GUIAct separately", "report task quality jointly with parameter/token efficiency")

METRICS=("aitw_action_matching", "gui_odyssey_success", "androidcontrol_low_success", "androidcontrol_high_success", "guiact_success", "reasoning_token_efficiency")

ABLATIONS=("without latent thinking tokens", "explicit chain-of-thought instead of latent thinking", "without visual perception module", "without cross-attention in VPM", "always-slow perception")

PHASES = (
    {
        "phase_id": 'latent_think',
        "role": 'ishift.reasoner',
        "instruction": 'Perform compact implicit deliberation with latent thinking tokens instead of explicit chain-of-thought.',
    },
    {
        "phase_id": 'perception_route',
        "role": 'ishift.router',
        "instruction": 'Decide whether the current action needs fast global perception or slow fine-grained grounding.',
    },
    {
        "phase_id": 'visual_focus',
        "role": 'ishift.vpm',
        "instruction": 'Activate the DINOv2-based Visual Perception Module for object-centered features when the slow path is selected.',
    },
    {
        "phase_id": 'ground_action',
        "role": 'ishift.agent',
        "instruction": 'Ground the target element and produce the GUI action.',
    },
    {
        "phase_id": 'observe_feedback',
        "role": 'ishift.agent',
        "instruction": 'Observe the resulting interface state and continue with adaptive reasoning depth.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'ishift_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=64)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
