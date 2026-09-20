from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_cycle_program, build_agent_phase_program
METHOD_ID="roboagent_cvpr2026"
TITLE="RoboAgent: Chaining Basic Capabilities for Embodied Task Planning"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Xu_RoboAgent_Chaining_Basic_Capabilities_for_Embodied_Task_Planning_CVPR_2026_paper.html"
BENCHMARK_IDS=("alfworld", "embodiedbench")
PROTOCOL=("reproduce behavior-cloning warm start from expert plans", "reproduce DAgger trajectory collection using the current model", "reproduce expert-policy-guided reinforcement learning", "evaluate ALFWorld visual/text settings and EB-ALFRED separately")
METRICS=("task_success", "seen_success", "unseen_success", "capability_calls", "steps", "planning_efficiency")
ABLATIONS=("without capability-private contexts", "without DAgger", "without reinforcement learning", "monolithic planner without scheduler")
PHASES=(
    AgentPhaseSpec("scheduler", "roboagent.scheduler", "Decompose the current embodied task and route the next query to a basic capability."),
    AgentPhaseSpec("capability_context", "roboagent.capability", "Load the selected capability's private context rather than a monolithic global history."),
    AgentPhaseSpec("capability_reason", "roboagent.capability", "Solve the routed vision-language subproblem with the shared VLM."),
    AgentPhaseSpec("environment_interact", "roboagent.executor", "Execute an atomic embodied action when the selected capability requires environment interaction."),
    AgentPhaseSpec("return_intermediate", "roboagent.scheduler", "Return the capability result to the scheduler and update the high-level plan."),
)
METHOD_PROGRAM=build_agent_cycle_program(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="roboagent_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=64,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
)
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
