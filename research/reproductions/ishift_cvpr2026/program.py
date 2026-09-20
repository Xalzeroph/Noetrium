from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="ishift_cvpr2026"
TITLE="iSHIFT: Lightweight Slow-Fast GUI Agent with Adaptive Perception"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Mehrotra_iSHIFT_Lightweight_Slow-Fast_GUI_Agent_with_Adaptive_Perception_CVPR_2026_paper.html"
BENCHMARK_IDS=("aitw", "androidcontrol", "gui-odyssey", "guiact")
PROTOCOL=("reproduce two-stage alignment then fine-tuning training pipeline", "preserve latent-thinking and perception-control special tokens", "evaluate AITW, GUI Odyssey, AndroidControl and GUIAct separately", "report task quality jointly with parameter/token efficiency")
METRICS=("aitw_action_matching", "gui_odyssey_success", "androidcontrol_low_success", "androidcontrol_high_success", "guiact_success", "reasoning_token_efficiency")
ABLATIONS=("without latent thinking tokens", "explicit chain-of-thought instead of latent thinking", "without visual perception module", "without cross-attention in VPM", "always-slow perception")
PHASES=(
    AgentPhaseSpec("latent_think", "ishift.reasoner", "Perform compact implicit deliberation with latent thinking tokens instead of explicit chain-of-thought."),
    AgentPhaseSpec("perception_route", "ishift.router", "Decide whether the current action needs fast global perception or slow fine-grained grounding."),
    AgentPhaseSpec("visual_focus", "ishift.vpm", "Activate the DINOv2-based Visual Perception Module for object-centered features when the slow path is selected."),
    AgentPhaseSpec("ground_action", "ishift.agent", "Ground the target element and produce the GUI action."),
    AgentPhaseSpec("observe_feedback", "ishift.agent", "Observe the resulting interface state and continue with adaptive reasoning depth."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="ishift_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=64,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
