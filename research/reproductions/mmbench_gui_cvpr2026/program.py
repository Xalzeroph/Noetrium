from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="mmbench_gui_cvpr2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html"
BENCHMARK_IDS=("mmbench-gui",)
PROTOCOL=("run all four hierarchy levels", "preserve six-platform evaluation across Windows/macOS/Linux/iOS/Android/Web", "report success and action redundancy jointly through EQA", "stratify complex and cross-application tasks")
METRICS=("content_understanding", "element_grounding", "task_success", "task_collaboration", "action_redundancy", "eqa")
ABLATIONS=("grounding-module analysis", "single-platform versus cross-platform", "quality-only versus EQA")
PHASES=(
    AgentPhaseSpec("content_understanding", "mmbench_gui.evaluator", "Evaluate GUI content understanding."),
    AgentPhaseSpec("element_grounding", "mmbench_gui.evaluator", "Evaluate visual element grounding."),
    AgentPhaseSpec("task_automation", "mmbench_gui.evaluator", "Evaluate end-to-end task automation."),
    AgentPhaseSpec("task_collaboration", "mmbench_gui.evaluator", "Evaluate cross-application task collaboration."),
    AgentPhaseSpec("eqa_score", "mmbench_gui.evaluator", "Compute Efficiency-Quality-Aware score from success and action redundancy."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="mmbench_gui_cvpr2026.phase-workflow.v1",phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"CVPR 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
