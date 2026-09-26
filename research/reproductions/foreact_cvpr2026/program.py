from __future__ import annotations

METHOD_ID="foreact_cvpr2026"

TITLE="ForeAct: Steering Your VLA with Efficient Visual Foresight Planning"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_ForeAct_Steering_Your_VLA_with_Efficient_Visual_Foresight_Planning_CVPR_2026_paper.html"

BENCHMARK_IDS=("foreact-real11",)

PROTOCOL=("reproduce the 11-task real-world benchmark and atomic-action scoring", "evaluate pi_0 and stronger VLA backbones separately", "preserve the 640x480 foresight image-generation configuration", "measure visual foresight against text-only subtask guidance under matched VLA backbones")

METRICS=("task_success", "atomic_action_success", "foresight_latency", "subtask_success", "steps", "planning_gain")

ABLATIONS=("without visual foresight", "text-only subtask guidance", "without subtask VLM", "single-view foresight")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'foreact.planner',
        "instruction": 'Encode current multi-view robot observations and the high-level task instruction.',
    },
    {
        "phase_id": 'subtask_reason',
        "role": 'foreact.vlm',
        "instruction": 'Infer the next semantic subtask description.',
    },
    {
        "phase_id": 'imagine_future',
        "role": 'foreact.generator',
        "instruction": 'Generate the predicted future observation conditioned on current vision and the subtask.',
    },
    {
        "phase_id": 'augment_vla_input',
        "role": 'foreact.planner',
        "instruction": 'Attach imagined future observations to the VLA visual context without modifying VLA architecture.',
    },
    {
        "phase_id": 'act',
        "role": 'foreact.vla',
        "instruction": 'Produce and execute the next visuo-motor action chunk.',
    },
    {
        "phase_id": 'recede_or_continue',
        "role": 'foreact.planner',
        "instruction": 'Use the resulting observation to refresh foresight planning for the next step.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'foreact_cvpr2026.phase-workflow.v1',
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
