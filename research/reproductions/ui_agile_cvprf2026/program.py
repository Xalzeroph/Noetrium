from __future__ import annotations

METHOD_ID="ui_agile_cvprf2026"

TITLE="UI-AGILE: Advancing GUI Agents with Effective Reinforcement Learning and Precise Inference-Time Grounding"

VENUE="CVPR Findings 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026F/html/Lian_UI-AGILE_Advancing_GUI_Agents_with_Effective_Reinforcement_Learning_and_Precise_CVPRF_2026_paper.html"

BENCHMARK_IDS=("screenspot-pro", "screenspot-v2", "androidcontrol")

PROTOCOL=("reproduce Simple Thinking, continuous grounding reward and crop-resampling during RFT", "evaluate decomposed grounding plus VLM selection separately from training gains", "report ScreenSpot-Pro, ScreenSpot-v2 and AndroidControl independently", "preserve matched image resolution and action-evaluation rules")

METRICS=("grounding_accuracy", "screenspot_pro_accuracy", "screenspot_v2_accuracy", "androidcontrol_low_success", "androidcontrol_high_success", "inference_latency")

ABLATIONS=("without Simple Thinking", "without crop-resampling", "without continuous grounding reward", "without decomposed grounding", "without VLM selection")

PHASES = (
    {
        "phase_id": 'simple_thinking',
        "role": 'ui_agile.policy',
        "instruction": 'Use concise task reasoning that balances planning depth with grounding latency.',
    },
    {
        "phase_id": 'continuous_reward',
        "role": 'ui_agile.training',
        "instruction": 'Score grounding predictions with a continuous precision-sensitive reward.',
    },
    {
        "phase_id": 'crop_resample',
        "role": 'ui_agile.training',
        "instruction": 'Resample difficult examples through crop-based visual refinement to reduce sparse rewards.',
    },
    {
        "phase_id": 'decomposed_grounding',
        "role": 'ui_agile.grounder',
        "instruction": 'Decompose high-resolution screens into candidate regions for precise grounding.',
    },
    {
        "phase_id": 'vlm_select',
        "role": 'ui_agile.selector',
        "instruction": 'Select the final candidate grounding with the VLM before emitting the GUI action.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'ui_agile_cvprf2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
