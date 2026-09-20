from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="refact_cvpr2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html"
BENCHMARK_IDS=("groundedvqa",)
PROTOCOL=("reproduce GroundedVQA flexible-complexity evaluation", "preserve Grounding-tool calls and Defocus/Refocus memory operations", "compare on additional public agentic benchmarks from the final paper", "measure task quality against context density and visual-noise complexity")
METRICS=("answer_accuracy", "task_success", "grounding_accuracy", "context_tokens", "visual_focus_operations", "latency")
ABLATIONS=("without Grounding tool", "without Defocus/Refocus memory", "without active focusing")
PHASES=(
    AgentPhaseSpec("reason", "refact.reasoner", "Reason over the current multimodal web-search state."),
    AgentPhaseSpec("ground_focus", "refact.grounding", "Actively ground and filter visual information relevant to the current reasoning step."),
    AgentPhaseSpec("defocus_refocus", "refact.memory", "Use external-memory Defocus/Refocus operations to control retained context density."),
    AgentPhaseSpec("act", "refact.agent", "Execute the next web-search or navigation action."),
    AgentPhaseSpec("observe", "refact.agent", "Observe new multimodal evidence and update the working context."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="refact_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=32,
    configuration={"paper_uri":PAPER_URI,"venue":"CVPR 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
