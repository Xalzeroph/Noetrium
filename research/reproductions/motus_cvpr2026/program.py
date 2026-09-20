from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_cycle_program
METHOD_ID="motus_cvpr2026"
TITLE="Motus: A Unified Latent Action World Model"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Bi_Motus_A_Unified_Latent_Action_World_Model_CVPR_2026_paper.html"
BENCHMARK_IDS=("robotwin2", "motus-realworld")
PROTOCOL=("reproduce the three-phase training pipeline and six-layer data pyramid", "preserve shared optical-flow latent action construction across heterogeneous data", "evaluate RoboTwin 2.0 multi-task simulation separately from real-world robot evaluation", "report unified-mode performance rather than training isolated task-specific models")
METRICS=("robotwin_success", "realworld_success", "world_model_quality", "action_accuracy", "video_prediction_quality", "mode_switch_count")
ABLATIONS=("without latent action pretraining", "without understanding expert", "without video-generation expert", "without unified scheduler", "isolated VLA-only mode")
PHASES=(
    AgentPhaseSpec("encode_multimodal", "motus.understanding", "Encode image/video/language context through the understanding expert."),
    AgentPhaseSpec("infer_latent_action", "motus.latent_action", "Derive optical-flow-based latent delta actions shared across heterogeneous data."),
    AgentPhaseSpec("select_mode", "motus.scheduler", "Select world-model, VLA, inverse-dynamics, video-generation, or video-action joint-prediction mode."),
    AgentPhaseSpec("joint_expert_forward", "motus.mot", "Route through the Mixture-of-Transformers understanding, action and video-generation experts."),
    AgentPhaseSpec("diffusion_schedule", "motus.unidiffuser", "Apply the UniDiffuser-style scheduler for the selected generation/prediction mode."),
    AgentPhaseSpec("act_or_predict", "motus.agent", "Emit action, future video, inverse action, or joint video-action prediction and preserve the corresponding artifact."),
)
METHOD_PROGRAM=build_agent_cycle_program(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="motus_cvpr2026.phase-workflow.v1",phases=PHASES,max_cycles=64,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
)
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
