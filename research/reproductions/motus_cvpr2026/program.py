from __future__ import annotations

METHOD_ID="motus_cvpr2026"

TITLE="Motus: A Unified Latent Action World Model"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Bi_Motus_A_Unified_Latent_Action_World_Model_CVPR_2026_paper.html"

BENCHMARK_IDS=("robotwin2", "motus-realworld")

PROTOCOL=("reproduce the three-phase training pipeline and six-layer data pyramid", "preserve shared optical-flow latent action construction across heterogeneous data", "evaluate RoboTwin 2.0 multi-task simulation separately from real-world robot evaluation", "report unified-mode performance rather than training isolated task-specific models")

METRICS=("robotwin_success", "realworld_success", "world_model_quality", "action_accuracy", "video_prediction_quality", "mode_switch_count")

ABLATIONS=("without latent action pretraining", "without understanding expert", "without video-generation expert", "without unified scheduler", "isolated VLA-only mode")

PHASES = (
    {
        "phase_id": 'encode_multimodal',
        "role": 'motus.understanding',
        "instruction": 'Encode image/video/language context through the understanding expert.',
    },
    {
        "phase_id": 'infer_latent_action',
        "role": 'motus.latent_action',
        "instruction": 'Derive optical-flow-based latent delta actions shared across heterogeneous data.',
    },
    {
        "phase_id": 'select_mode',
        "role": 'motus.scheduler',
        "instruction": 'Select world-model, VLA, inverse-dynamics, video-generation, or video-action joint-prediction mode.',
    },
    {
        "phase_id": 'joint_expert_forward',
        "role": 'motus.mot',
        "instruction": 'Route through the Mixture-of-Transformers understanding, action and video-generation experts.',
    },
    {
        "phase_id": 'diffusion_schedule',
        "role": 'motus.unidiffuser',
        "instruction": 'Apply the UniDiffuser-style scheduler for the selected generation/prediction mode.',
    },
    {
        "phase_id": 'act_or_predict',
        "role": 'motus.agent',
        "instruction": 'Emit action, future video, inverse action, or joint video-action prediction and preserve the corresponding artifact.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'motus_cvpr2026.phase-workflow.v1',
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
