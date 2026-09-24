from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="crossha_cvpr2026"
TITLE="Training One Model to Master Cross-Level Agentic Actions via Reinforcement Learning"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/He_Training_One_Model_to_Master_Cross-Level_Agentic_Actions_via_Reinforcement_CVPR_2026_paper.html"
BENCHMARK_IDS=("minecraft-openha",)
PROTOCOL=("perform cold-start supervised fine-tuning before multi-turn GRPO", "preserve the mixed heterogeneous action space rather than fixed single-space policies", "evaluate 800+ OpenHA tasks across Mine Blocks, Kill Entities and Craft Items", "report finished-task coverage and average success rate per category")
METRICS=("finished_tasks", "average_success_rate", "mine_success", "kill_success", "craft_success", "steps", "action_space_switch_count")
ABLATIONS=("without multi-turn GRPO", "grounding-only action space", "motion-only action space", "fixed action interface")
PHASES=(
    AgentPhaseSpec("observe", "crossha.policy", "Observe the Minecraft RGB stream, task instruction and recent trajectory context without privileged state."),
    AgentPhaseSpec("select_action_space", "crossha.policy", "Choose the most suitable action interface and granularity for the current step."),
    AgentPhaseSpec("instantiate_action", "crossha.policy", "Generate a motion-, grounding-, or text-level action under the selected interface."),
    AgentPhaseSpec("execute", "crossha.environment", "Execute the human-like mouse/keyboard interaction in Minecraft 1.16.5."),
    AgentPhaseSpec("score_rollout", "crossha.training", "Collect multi-turn task reward used by Group Relative Policy Optimization."),
    AgentPhaseSpec("policy_update", "crossha.training", "Update the unified policy with multi-turn GRPO while preserving heterogeneous action switching."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="crossha_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=200,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
