from __future__ import annotations

METHOD_ID="dejavu_cvpr2026"

TITLE="Dejavu: Towards Experience Feedback Learning for Embodied Intelligence"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_Dejavu_Towards_Experience_Feedback_Learning_for_Embodied_Intelligence_CVPR_2026_paper.html"

BENCHMARK_IDS=("libero",)

PROTOCOL=("evaluate OpenVLA, UniVLA and GO-1 backbones separately", "preserve the four LIBERO suites and horizon H=320", "keep the VLA backbone frozen while adapting only EFN", "append successful rollouts to the experience bank without evaluation-time gradient updates")

METRICS=("task_success", "average_steps", "experience_bank_size", "retrieval_similarity", "residual_magnitude", "adaptation_gain")

ABLATIONS=("without similarity reward", "without instruction-aware retrieval", "without SAC", "retrieval-only", "residual-only")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'dejavu.efn',
        "instruction": 'Encode current visual-language state while keeping the base VLA frozen.',
    },
    {
        "phase_id": 'retrieve_experience',
        "role": 'dejavu.memory',
        "instruction": 'Retrieve a contextually successful prior transition from the live experience bank.',
    },
    {
        "phase_id": 'predict_residual',
        "role": 'dejavu.efn',
        "instruction": 'Predict a retrieval-conditioned residual correction to the frozen VLA action.',
    },
    {
        "phase_id": 'execute',
        "role": 'dejavu.policy',
        "instruction": 'Execute the corrected action under the current rollout horizon.',
    },
    {
        "phase_id": 'reward_update',
        "role": 'dejavu.training',
        "instruction": 'Train the residual controller with task return plus semantic-similarity shaping.',
    },
    {
        "phase_id": 'bank_update',
        "role": 'dejavu.memory',
        "instruction": 'Append successful trajectories and prioritize shorter successful experiences.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'dejavu_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=320)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
