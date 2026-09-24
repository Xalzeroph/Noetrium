from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID="implement_acl2026"
PAPER_URI="https://aclanthology.org/2026.acl-long.827/"
BENCHMARK_IDS=("alfworld",)
PROTOCOL=("keep the policy LLM frozen during imaginative planning", "reproduce Monte Carlo future-state prediction by temperature sampling", "reproduce Meta In-Context Learning world-model adaptation", "report success over 1, 6, and 12 trials on held-out ALFWorld tasks")
METRICS=("task_success", "planning_accuracy", "world_model_prediction", "imagined_rollouts", "steps", "model_calls")
ABLATIONS=("without world model", "single deterministic future", "without Meta-ICL", "without online policy refinement")
PHASES=(
    AgentPhaseSpec("perceive_symbolic", "implement.world_model", "Convert raw visual observations into object-centric symbolic states."),
    AgentPhaseSpec("propose_actions", "implement.llm", "Propose candidate actions from current symbolic state and task goal."),
    AgentPhaseSpec("imagine_futures", "implement.world_model", "Predict Monte Carlo future states for candidate actions using temperature sampling."),
    AgentPhaseSpec("rank_refine", "implement.llm", "Rank imagined trajectories and refine the decision."),
    AgentPhaseSpec("execute", "implement.agent", "Execute the selected action in ALFWorld."),
    AgentPhaseSpec("meta_icl_update", "implement.world_model", "Condition the world model on new interaction history for unseen-environment adaptation."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="implement_acl2026.phase-workflow.v1",
    phases=PHASES,
    max_cycles=64,
    configuration={"paper_uri":PAPER_URI,"venue":"ACL 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,
    artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
