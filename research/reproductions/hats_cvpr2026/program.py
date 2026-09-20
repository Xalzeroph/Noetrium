from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="hats_cvpr2026"
TITLE="HATS: Hardness-Aware Trajectory Synthesis for GUI Agents"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Shao_HATS_Hardness-Aware_Trajectory_Synthesis_for_GUI_Agents_CVPR_2026_paper.html"
BENCHMARK_IDS=("androidworld", "webarena")
PROTOCOL=("reproduce hardness-driven MCTS rather than uniform random exploration", "replay every synthesized instruction before corpus admission", "preserve action-level reconstruction recall threshold R>=0.7", "feed misalignment signals back into future exploration hardness")
METRICS=("task_success", "trajectory_alignment_recall", "accepted_trajectory_count", "semantic_ambiguous_coverage", "androidworld_score", "webarena_score")
ABLATIONS=("uniform exploration", "without alignment-guided refinement", "without hardness feedback", "one-shot instruction synthesis")
PHASES=(
    AgentPhaseSpec("estimate_hardness", "hats.explorer", "Estimate semantic ambiguity and under-representation of candidate GUI actions."),
    AgentPhaseSpec("hd_mcts_select", "hats.explorer", "Select and expand GUI states with hardness-driven UCB Monte Carlo Tree Search."),
    AgentPhaseSpec("synthesize_instruction", "hats.refiner", "Generate an instruction from the explored action trajectory."),
    AgentPhaseSpec("replay_instruction", "hats.refiner", "Replay the synthesized instruction in the environment to reconstruct the trajectory."),
    AgentPhaseSpec("measure_alignment", "hats.refiner", "Measure action-level reconstruction recall between instruction replay and source trajectory."),
    AgentPhaseSpec("refine_or_accept", "hats.refiner", "Inject missing contextual cues until alignment reaches the paper threshold, then admit the trajectory."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="hats_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=32,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
