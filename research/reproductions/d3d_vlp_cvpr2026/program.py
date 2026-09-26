from __future__ import annotations

METHOD_ID="d3d_vlp_cvpr2026"

TITLE="D3D-VLP: Dynamic 3D Vision-Language-Planning Model for Embodied Grounding and Navigation"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_D3D-VLP_Dynamic_3D_Vision-Language-Planning_Model_for_Embodied_Grounding_and_Navigation_CVPR_2026_paper.html"

BENCHMARK_IDS=("r2r-ce", "reverie-ce", "navrag-ce", "hm3d-ovon", "sg3d")

PROTOCOL=("preserve the unified 3D-CoT pipeline rather than separate independent modules", "reproduce SLFS masked autoregressive training from fragmented supervision", "evaluate all five navigation/grounding benchmark families", "retain dynamic replanning feedback when target or plan execution fails")

METRICS=("navigation_success", "spl", "grounding_accuracy", "task_success", "replan_count", "trajectory_length")

ABLATIONS=("without dynamic replanning", "without multi-level 3D memory", "without SLFS", "separate non-synergistic modules")

PHASES = (
    {
        "phase_id": 'update_3d_memory',
        "role": 'd3d_vlp.memory',
        "instruction": 'Update multi-level 3D memory with observations, trajectory history, grounded targets and prior plans.',
    },
    {
        "phase_id": 'dynamic_3d_cot',
        "role": 'd3d_vlp.reasoner',
        "instruction": 'Generate a dynamic 3D chain-of-thought spanning planning, grounding, navigation and question answering.',
    },
    {
        "phase_id": 'ground_target',
        "role": 'd3d_vlp.reasoner',
        "instruction": 'Ground the next target or detect that the current target is missing.',
    },
    {
        "phase_id": 'plan_or_replan',
        "role": 'd3d_vlp.planner',
        "instruction": 'Generate or revise the plan using current 3D memory and grounding feedback.',
    },
    {
        "phase_id": 'navigate',
        "role": 'd3d_vlp.navigator',
        "instruction": 'Execute navigation actions toward the grounded target.',
    },
    {
        "phase_id": 'feedback',
        "role": 'd3d_vlp.reasoner',
        "instruction": 'Use blocked-plan or missing-target feedback to trigger another reasoning cycle.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'd3d_vlp_cvpr2026.phase-workflow.v1',
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
