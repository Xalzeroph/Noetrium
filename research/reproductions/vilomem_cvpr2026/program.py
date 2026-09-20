from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentPhaseSpec, build_agent_cycle_program
METHOD_ID="vilomem_cvpr2026"
TITLE="ViLoMem: Agentic Learner with Grow-and-Refine Multimodal Semantic Memory"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Bo_ViLoMem_Agentic_Learner_with_Grow-and-Refine_Multimodal_Semantic_Memory_CVPR_2026_paper.html"
BENCHMARK_IDS=("mmmu", "mathvista", "mathvision", "hallusionbench", "mmstar", "realworldqa")
PROTOCOL=("evaluate the six final-paper multimodal reasoning benchmarks under matched backbone/model settings", "separate logical-memory and visual-memory generation/retrieval paths", "preserve grow-versus-refine merge semantics and verifier filtering", "run cross-benchmark memory generalization and cross-model memory transfer separately")
METRICS=("pass_at_1", "logic_error_repeat_rate", "visual_error_repeat_rate", "memory_schema_count", "retrieval_hit_rate", "memory_tokens")
ABLATIONS=("without visual memory", "without logical memory", "without distraction-hallucination separation", "without grow-and-refine merging", "cross-benchmark memory only")
PHASES=(
    AgentPhaseSpec("solve", "vilomem.solver", "Solve the multimodal query using retrieved logical and visual semantic memories."),
    AgentPhaseSpec("verify", "vilomem.verifier", "Verify the prediction and identify whether the attempt should contribute new memory."),
    AgentPhaseSpec("attribute_logic_error", "vilomem.logic_memory", "Attribute reasoning failures into structured logical error and strategy schemas."),
    AgentPhaseSpec("attribute_visual_error", "vilomem.visual_memory", "Analyze attention/perception failures and isolate visual distraction or hallucination patterns."),
    AgentPhaseSpec("grow_or_refine", "vilomem.memory", "Merge with a similar memory schema or create a new schema while preserving stable reusable knowledge."),
    AgentPhaseSpec("dual_retrieve", "vilomem.retriever", "Retrieve logical memories by problem/text similarity and visual memories by image embedding plus query filtering."),
)
METHOD_PROGRAM=build_agent_cycle_program(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="vilomem_cvpr2026.phase-workflow.v1",phases=PHASES,max_cycles=8,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
)
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
