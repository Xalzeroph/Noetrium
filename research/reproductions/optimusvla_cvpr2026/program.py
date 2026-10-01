from __future__ import annotations

METHOD_ID="optimusvla_cvpr2026"

TITLE="Global Prior Meets Local Consistency: Dual-Memory Augmented Vision-Language-Action Model for Efficient Robotic Manipulation"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Li_Global_Prior_Meets_Local_Consistency_Dual-Memory_Augmented_Vision-Language-Action_Model_for_CVPR_2026_paper.html"

BENCHMARK_IDS=("libero", "calvin", "robotwin2-hard")

PROTOCOL=("evaluate GPM and LCM jointly under the paper VLA backbone", "preserve adaptive NFE inference schedule", "report simulation and real-world suites separately", "measure success and inference speed under matched compute")

METRICS=("task_success", "libero_success", "calvin_gain", "robotwin_hard_success", "inference_speedup", "nfe_count")

ABLATIONS=("without global prior memory", "without local consistency memory", "without adaptive NFE", "Gaussian initialization instead of retrieved prior")

PHASES = (
    {
        "phase_id": 'encode',
        "role": 'optimusvla.backbone',
        "instruction": 'Encode task language and current observations into the VLA multimodal representation.',
    },
    {
        "phase_id": 'retrieve_global_prior',
        "role": 'optimusvla.gpm',
        "instruction": 'Retrieve a task-level prior trajectory from Global Prior Memory.',
    },
    {
        "phase_id": 'encode_local_consistency',
        "role": 'optimusvla.lcm',
        "instruction": 'Encode executed action history into Local Consistency Memory and infer task progress.',
    },
    {
        "phase_id": 'generate_action_chunk',
        "role": 'optimusvla.flow',
        "instruction": 'Generate the next action chunk from prior-initialized flow with adaptive NFE scheduling.',
    },
    {
        "phase_id": 'enforce_consistency',
        "role": 'optimusvla.lcm',
        "instruction": 'Apply local temporal-consistency constraints to the generated action chunk.',
    },
    {
        "phase_id": 'execute_update',
        "role": 'optimusvla.policy',
        "instruction": 'Execute the action chunk and update local action-history memory.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'optimusvla_cvpr2026.phase-workflow.v1',
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
