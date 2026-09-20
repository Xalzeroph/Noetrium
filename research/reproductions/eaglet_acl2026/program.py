from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID="eaglet_acl2026"
PAPER_URI="https://aclanthology.org/2026.acl-long.597/"
BENCHMARK_IDS=("scienceworld", "alfworld", "webshop")
PROTOCOL=("reproduce teacher-plan synthesis and homologous consensus filtering", "perform SFT cold start before rule-based RL", "use executor capability gain rather than learned reward model", "report seen/unseen splits and training cost")
METRICS=("task_success", "seen_success", "unseen_success", "training_cost", "planner_tokens", "executor_capability_gain")
ABLATIONS=("without consensus filtering", "SFT-only", "without capability-gain reward", "implicit planning")
PHASES=(
    AgentPhaseSpec("plan_synthesis", "eaglet.teacher", "Synthesize candidate global plans with the teacher LLM."),
    AgentPhaseSpec("consensus_filter", "eaglet.filter", "Apply homologous consensus filtering to retain high-quality plans."),
    AgentPhaseSpec("cold_start_sft", "eaglet.training", "Fine-tune the planner on filtered plans for cold start."),
    AgentPhaseSpec("capability_gain_rl", "eaglet.training", "Optimize with executor capability-gain reward without a learned reward model."),
    AgentPhaseSpec("plan_execute", "eaglet.planner", "Generate a global plan and execute it with the downstream executor agent."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="eaglet_acl2026.phase-workflow.v1",
    phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"ACL 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,
    artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
