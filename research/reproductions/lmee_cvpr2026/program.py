from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="lmee_cvpr2026"
TITLE="Explore with Long-term Memory: A Benchmark and Multimodal LLM-based Reinforcement Learning Framework for Embodied Exploration"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Explore_with_Long-term_Memory_A_Benchmark_and_Multimodal_LLM-based_Reinforcement_CVPR_2026_paper.html"
BENCHMARK_IDS=("lmee-bench",)
PROTOCOL=("reproduce LMEE-Bench multi-goal navigation and memory-based QA", "freeze HM3D-Sem train/val environment identity", "reproduce the released MemoryExplorer reinforcement-learning setup", "evaluate exploration process and final-task outcomes separately")
METRICS=("navigation_success", "memory_qa_accuracy", "exploration_efficiency", "memory_retrieval_quality", "steps", "context_tokens")
ABLATIONS=("without long-term memory", "without memory retrieval", "without reinforcement learning", "short-context memory only")
PHASES=(
    AgentPhaseSpec("observe", "lmee.agent", "Observe the embodied scene and current long-term episodic memory."),
    AgentPhaseSpec("memory_retrieve", "lmee.memory", "Retrieve task-relevant historical visual episodes and memory-based evidence."),
    AgentPhaseSpec("explore_plan", "lmee.agent", "Plan exploration toward current navigation and memory-QA objectives."),
    AgentPhaseSpec("act", "lmee.agent", "Execute the selected embodied exploration action."),
    AgentPhaseSpec("memory_update", "lmee.memory", "Append and consolidate new visual experience into long-term episodic memory."),
    AgentPhaseSpec("answer_or_continue", "lmee.agent", "Answer memory-based questions when sufficient evidence exists or continue exploration."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="lmee_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=128,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
