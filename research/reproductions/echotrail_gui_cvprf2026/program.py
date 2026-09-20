from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_phase_program
METHOD_ID="echotrail_gui_cvprf2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html"
BENCHMARK_IDS=("androidworld", "androidlab")
PROTOCOL=("construct the memory database only from autonomous critic-validated successes", "freeze retrieval policy and memory injection format", "compare before and after memory injection on AndroidWorld and AndroidLab", "report operational efficiency together with task success")
METRICS=("task_success_rate", "steps", "trajectory_acceptance", "memory_retrieval_hit", "token_cost")
ABLATIONS=("without critic validation", "without memory retrieval", "random trajectory injection")
PHASES=(
    AgentPhaseSpec("explore", "echotrail.explorer", "Autonomously explore GUI tasks and collect candidate successful trajectories."),
    AgentPhaseSpec("critic_validate", "echotrail.critic", "Validate explored trajectories with the reward/critic model."),
    AgentPhaseSpec("store_memory", "echotrail.memory", "Store critic-validated successful trajectories as actionable memories."),
    AgentPhaseSpec("retrieve_memory", "echotrail.memory", "Retrieve relevant prior trajectories for a new GUI task."),
    AgentPhaseSpec("guided_inference", "echotrail.agent", "Inject retrieved trajectories as in-context guidance and execute the task."),
)
METHOD_PROGRAM=build_agent_phase_program(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="echotrail_gui_cvprf2026.phase-workflow.v1",phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"CVPR Findings 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
)
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
