from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="ui_agile_cvprf2026"
TITLE="UI-AGILE: Advancing GUI Agents with Effective Reinforcement Learning and Precise Inference-Time Grounding"
VENUE="CVPR Findings 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026F/html/Lian_UI-AGILE_Advancing_GUI_Agents_with_Effective_Reinforcement_Learning_and_Precise_CVPRF_2026_paper.html"
BENCHMARK_IDS=("screenspot-pro", "screenspot-v2", "androidcontrol")
PROTOCOL=("reproduce Simple Thinking, continuous grounding reward and crop-resampling during RFT", "evaluate decomposed grounding plus VLM selection separately from training gains", "report ScreenSpot-Pro, ScreenSpot-v2 and AndroidControl independently", "preserve matched image resolution and action-evaluation rules")
METRICS=("grounding_accuracy", "screenspot_pro_accuracy", "screenspot_v2_accuracy", "androidcontrol_low_success", "androidcontrol_high_success", "inference_latency")
ABLATIONS=("without Simple Thinking", "without crop-resampling", "without continuous grounding reward", "without decomposed grounding", "without VLM selection")
PHASES=(
    AgentPhaseSpec("simple_thinking", "ui_agile.policy", "Use concise task reasoning that balances planning depth with grounding latency."),
    AgentPhaseSpec("continuous_reward", "ui_agile.training", "Score grounding predictions with a continuous precision-sensitive reward."),
    AgentPhaseSpec("crop_resample", "ui_agile.training", "Resample difficult examples through crop-based visual refinement to reduce sparse rewards."),
    AgentPhaseSpec("decomposed_grounding", "ui_agile.grounder", "Decompose high-resolution screens into candidate regions for precise grounding."),
    AgentPhaseSpec("vlm_select", "ui_agile.selector", "Select the final candidate grounding with the VLM before emitting the GUI action."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="ui_agile_cvprf2026.phase-workflow.v1",phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
