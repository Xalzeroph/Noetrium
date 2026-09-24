from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="dejavu_cvpr2026"
TITLE="Dejavu: Towards Experience Feedback Learning for Embodied Intelligence"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_Dejavu_Towards_Experience_Feedback_Learning_for_Embodied_Intelligence_CVPR_2026_paper.html"
BENCHMARK_IDS=("libero",)
PROTOCOL=("evaluate OpenVLA, UniVLA and GO-1 backbones separately", "preserve the four LIBERO suites and horizon H=320", "keep the VLA backbone frozen while adapting only EFN", "append successful rollouts to the experience bank without evaluation-time gradient updates")
METRICS=("task_success", "average_steps", "experience_bank_size", "retrieval_similarity", "residual_magnitude", "adaptation_gain")
ABLATIONS=("without similarity reward", "without instruction-aware retrieval", "without SAC", "retrieval-only", "residual-only")
PHASES=(
    AgentPhaseSpec("observe", "dejavu.efn", "Encode current visual-language state while keeping the base VLA frozen."),
    AgentPhaseSpec("retrieve_experience", "dejavu.memory", "Retrieve a contextually successful prior transition from the live experience bank."),
    AgentPhaseSpec("predict_residual", "dejavu.efn", "Predict a retrieval-conditioned residual correction to the frozen VLA action."),
    AgentPhaseSpec("execute", "dejavu.policy", "Execute the corrected action under the current rollout horizon."),
    AgentPhaseSpec("reward_update", "dejavu.training", "Train the residual controller with task return plus semantic-similarity shaping."),
    AgentPhaseSpec("bank_update", "dejavu.memory", "Append successful trajectories and prioritize shorter successful experiences."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="dejavu_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=320,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
