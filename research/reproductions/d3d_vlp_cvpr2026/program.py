from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="d3d_vlp_cvpr2026"
TITLE="D3D-VLP: Dynamic 3D Vision-Language-Planning Model for Embodied Grounding and Navigation"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_D3D-VLP_Dynamic_3D_Vision-Language-Planning_Model_for_Embodied_Grounding_and_Navigation_CVPR_2026_paper.html"
BENCHMARK_IDS=("r2r-ce", "reverie-ce", "navrag-ce", "hm3d-ovon", "sg3d")
PROTOCOL=("preserve the unified 3D-CoT pipeline rather than separate independent modules", "reproduce SLFS masked autoregressive training from fragmented supervision", "evaluate all five navigation/grounding benchmark families", "retain dynamic replanning feedback when target or plan execution fails")
METRICS=("navigation_success", "spl", "grounding_accuracy", "task_success", "replan_count", "trajectory_length")
ABLATIONS=("without dynamic replanning", "without multi-level 3D memory", "without SLFS", "separate non-synergistic modules")
PHASES=(
    AgentPhaseSpec("update_3d_memory", "d3d_vlp.memory", "Update multi-level 3D memory with observations, trajectory history, grounded targets and prior plans."),
    AgentPhaseSpec("dynamic_3d_cot", "d3d_vlp.reasoner", "Generate a dynamic 3D chain-of-thought spanning planning, grounding, navigation and question answering."),
    AgentPhaseSpec("ground_target", "d3d_vlp.reasoner", "Ground the next target or detect that the current target is missing."),
    AgentPhaseSpec("plan_or_replan", "d3d_vlp.planner", "Generate or revise the plan using current 3D memory and grounding feedback."),
    AgentPhaseSpec("navigate", "d3d_vlp.navigator", "Execute navigation actions toward the grounded target."),
    AgentPhaseSpec("feedback", "d3d_vlp.reasoner", "Use blocked-plan or missing-target feedback to trigger another reasoning cycle."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="d3d_vlp_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=128,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
