from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="foreact_cvpr2026"
TITLE="ForeAct: Steering Your VLA with Efficient Visual Foresight Planning"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_ForeAct_Steering_Your_VLA_with_Efficient_Visual_Foresight_Planning_CVPR_2026_paper.html"
BENCHMARK_IDS=("foreact-real11",)
PROTOCOL=("reproduce the 11-task real-world benchmark and atomic-action scoring", "evaluate pi_0 and stronger VLA backbones separately", "preserve the 640x480 foresight image-generation configuration", "measure visual foresight against text-only subtask guidance under matched VLA backbones")
METRICS=("task_success", "atomic_action_success", "foresight_latency", "subtask_success", "steps", "planning_gain")
ABLATIONS=("without visual foresight", "text-only subtask guidance", "without subtask VLM", "single-view foresight")
PHASES=(
    AgentPhaseSpec("observe", "foreact.planner", "Encode current multi-view robot observations and the high-level task instruction."),
    AgentPhaseSpec("subtask_reason", "foreact.vlm", "Infer the next semantic subtask description."),
    AgentPhaseSpec("imagine_future", "foreact.generator", "Generate the predicted future observation conditioned on current vision and the subtask."),
    AgentPhaseSpec("augment_vla_input", "foreact.planner", "Attach imagined future observations to the VLA visual context without modifying VLA architecture."),
    AgentPhaseSpec("act", "foreact.vla", "Produce and execute the next visuo-motor action chunk."),
    AgentPhaseSpec("recede_or_continue", "foreact.planner", "Use the resulting observation to refresh foresight planning for the next step."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="foreact_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=128,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
