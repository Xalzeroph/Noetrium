from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec

METHOD_ID="orbit_acl2026"
PAPER_URI="https://aclanthology.org/2026.acl-long.1822/"
BENCHMARK_IDS=("embodiedbench",)
PROTOCOL=("separate on-policy trajectory collection from offline reward computation", "evaluate in-domain and out-of-domain EmbodiedBench settings", "hold interaction budget fixed across RL baselines", "preserve visual observations and multi-step action semantics")
METRICS=("task_success", "in_domain_success", "out_of_domain_success", "reward", "interaction_cost", "training_cost")
ABLATIONS=("without offline reward", "off-policy-only training", "without reinforcement fine-tuning")
PHASES=(
    AgentPhaseSpec("collect_onpolicy", "orbit.policy", "Collect on-policy multi-step embodied planning trajectories."),
    AgentPhaseSpec("offline_reward", "orbit.reward", "Score collected trajectories with the paper's offline reward mechanism."),
    AgentPhaseSpec("reinforcement_update", "orbit.training", "Apply reinforcement fine-tuning using offline reward."),
    AgentPhaseSpec("evaluate_id", "orbit.evaluator", "Evaluate in-domain EB-ALFRED tasks."),
    AgentPhaseSpec("evaluate_ood", "orbit.evaluator", "Evaluate unseen EB-Habitat tasks."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,
    implementation_version="2026-paper-protocol",
    schema_version="orbit_acl2026.phase-workflow.v1",
    phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"ACL 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,
    artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
