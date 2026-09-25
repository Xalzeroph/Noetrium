from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="star_toggle_cvpr2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html"
BENCHMARK_IDS=("state-control-benchmark",)
PROTOCOL=("evaluate all four multimodal agents from the final paper", "separate already-correct-state cases from required-toggle cases", "run the three additional public agentic benchmarks", "evaluate the dynamic environment separately")
METRICS=("toggle_execution_accuracy", "task_success", "false_action_rate", "grounding_accuracy", "steps")
ABLATIONS=("without explicit current-state perception", "without desired-state inference", "always-act policy")
PHASES=(
    AgentPhaseSpec("see", "star.perception", "Perceive the current binary toggle state from the GUI."),
    AgentPhaseSpec("think_goal", "star.reasoner", "Infer the desired toggle state from the user instruction."),
    AgentPhaseSpec("compare", "star.reasoner", "Compare current and desired states and decide whether interaction is required."),
    AgentPhaseSpec("act_or_noop", "star.agent", "Execute the toggle action only when a state transition is required."),
    AgentPhaseSpec("verify", "star.perception", "Verify the post-action state and retain evidence."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="star_toggle_cvpr2026.phase-workflow.v1",phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"CVPR 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
