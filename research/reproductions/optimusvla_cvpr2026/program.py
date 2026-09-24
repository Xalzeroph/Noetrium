from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="optimusvla_cvpr2026"
TITLE="Global Prior Meets Local Consistency: Dual-Memory Augmented Vision-Language-Action Model for Efficient Robotic Manipulation"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Li_Global_Prior_Meets_Local_Consistency_Dual-Memory_Augmented_Vision-Language-Action_Model_for_CVPR_2026_paper.html"
BENCHMARK_IDS=("libero", "calvin", "robotwin2-hard")
PROTOCOL=("evaluate GPM and LCM jointly under the paper VLA backbone", "preserve adaptive NFE inference schedule", "report simulation and real-world suites separately", "measure success and inference speed under matched compute")
METRICS=("task_success", "libero_success", "calvin_gain", "robotwin_hard_success", "inference_speedup", "nfe_count")
ABLATIONS=("without global prior memory", "without local consistency memory", "without adaptive NFE", "Gaussian initialization instead of retrieved prior")
PHASES=(
    AgentPhaseSpec("encode", "optimusvla.backbone", "Encode task language and current observations into the VLA multimodal representation."),
    AgentPhaseSpec("retrieve_global_prior", "optimusvla.gpm", "Retrieve a task-level prior trajectory from Global Prior Memory."),
    AgentPhaseSpec("encode_local_consistency", "optimusvla.lcm", "Encode executed action history into Local Consistency Memory and infer task progress."),
    AgentPhaseSpec("generate_action_chunk", "optimusvla.flow", "Generate the next action chunk from prior-initialized flow with adaptive NFE scheduling."),
    AgentPhaseSpec("enforce_consistency", "optimusvla.lcm", "Apply local temporal-consistency constraints to the generated action chunk."),
    AgentPhaseSpec("execute_update", "optimusvla.policy", "Execute the action chunk and update local action-history memory."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="optimusvla_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=64,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
