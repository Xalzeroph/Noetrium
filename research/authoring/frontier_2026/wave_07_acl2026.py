"""Executable ACL-2026 reproduction wave.

Paper-specific semantics live here; the platform only supplies AgentMethodSpec/AgentPhaseSpec.
Reported values are provenance references, never substituted for measured Noetrium results.
"""
from __future__ import annotations
from dataclasses import dataclass
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec

@dataclass(frozen=True)
class PaperReproduction:
    method_id: str
    title: str
    paper_uri: str
    benchmark_ids: tuple[str,...]
    protocol: tuple[str,...]
    metrics: tuple[str,...]
    baselines: tuple[str,...]
    ablations: tuple[str,...]
    phases: tuple[AgentPhaseSpec,...]
    reported_results: tuple[str,...]=()

    def compile(self):
        return AgentMethodSpec(
            method_id=self.method_id, implementation_version="ACL-2026-final-protocol",
            schema_version=f"{self.method_id}.phase-workflow.v1", phases=self.phases,
            configuration={"paper_uri":self.paper_uri,"venue":"ACL 2026","benchmark_ids":self.benchmark_ids,"protocol":self.protocol,"baselines":self.baselines,"ablations":self.ablations,"reported_results":self.reported_results},
            evidence_obligations=(f"{self.method_id}.phase-transcript",f"{self.method_id}.model-tool-receipts",f"{self.method_id}.metric-artifacts",f"{self.method_id}.result-table"),
            metric_names=self.metrics,
            artifact_kinds=(f"{self.method_id}_trajectory",f"{self.method_id}_experiment_manifest",f"{self.method_id}_result_table"),
        ).compile()

def P(name,*steps): return tuple(AgentPhaseSpec(f"phase_{i:02d}",f"{name}.{s}",s.replace('_',' ')) for i,s in enumerate(steps,1))

REPRODUCTIONS=(
PaperReproduction("compass_acl2026","COMPASS: Enhancing Agent Long-Horizon Reasoning with Evolving Context","https://aclanthology.org/2026.acl-long.152/",("gaia","browsecomp","humanitys_last_exam"),("run Main Agent with tools under fixed budget","Meta-Thinker monitors progress and intervenes strategically","Context Manager emits stage-specific concise progress briefs","compare base, scaling and post-trained context-manager settings"),("accuracy","success_rate","token_cost","tool_calls","latency"),("single-agent CoT","multi-agent baseline","full-history context"),("without Meta-Thinker","without Context Manager","without test-time scaling"),P("compass","organize_context","execute_main_agent","monitor_progress","strategic_intervention","refresh_brief","finalize"),("up to 20% relative accuracy improvement reported",)),
PaperReproduction("octotools_acl2026","OctoTools: A Multi-Agent Framework with Extensible Tools for Complex Reasoning","https://aclanthology.org/2026.acl-long.1/",("mathvista","mmlu_pro","medqa","gaia_text"),("materialize standardized tool cards","planner produces high-level and low-level plans","executor selects and invokes tools","evaluate all 16 paper tasks with matched backbone"),("accuracy","task_success","tool_calls","token_cost","planning_steps"),("GPT-4o direct","tool-augmented baselines","specialized agents"),("without tool cards","without high-level planning","without executor feedback"),P("octotools","load_tool_cards","high_level_plan","low_level_plan","execute_tool","observe_result","replan","answer"),("9.3% average accuracy gain over GPT-4o reported",)),
PaperReproduction("bmam_acl2026","BMAM: Brain-inspired Multi-Agent Memory Framework","https://aclanthology.org/2026.findings-acl.1973/",("locomo",),("preserve episodic timelines","maintain semantic, salience and control-oriented memory subsystems","fuse complementary retrieval signals","execute six-phase memory lifecycle before answering"),("accuracy","retrieval_recall","temporal_accuracy","token_cost","memory_size"),("full context","RAG memory","memory-augmented baselines"),("without episodic timeline","without salience memory","single-store memory"),P("bmam","encode_episode","update_semantic","score_salience","control_memory","fused_retrieval","answer","consolidate"),("78.45% LoCoMo accuracy reported",)),
PaperReproduction("clag_acl2026","CLAG: Adaptive Memory Organization via Agent-Driven Clustering for Small Language Model Agents","https://aclanthology.org/2026.findings-acl.824/",("qa_multi_dataset",),("route every new memory to a semantic cluster","evolve knowledge only inside selected cluster","retrieve from a small relevant cluster set","repeat across three SLM backbones"),("answer_accuracy","robustness","retrieval_precision","retrieval_candidates","token_cost"),("global memory pool","retrieval memory baselines","no-memory SLM"),("without clustering","global evolution","retrieve all clusters"),P("clag","route_memory","cluster_insert","cluster_evolve","route_query","cluster_retrieve","answer")),
PaperReproduction("dcm_agent_acl2026","Dual-Cluster Memory Agent: Resolving Multi-Paradigm Ambiguity in Optimization Problem Solving","https://aclanthology.org/2026.acl-long.266/",("optimization_seven_benchmarks",),("cluster historical solutions by modeling and coding paradigms","distill Approach Checklist and Pitfall memory","navigate solution path with retrieved structured knowledge","detect errors and switch reasoning paths"),("objective_quality","solve_rate","error_rate","path_switches","token_cost"),("base LLM","flat memory","single-cluster memory"),("without modeling cluster","without coding cluster","without path switching"),P("dcm","cluster_history","distill_guidance","retrieve_guidance","generate_solution","detect_error","switch_path","verify"),("11%-21% average improvement reported",)),
PaperReproduction("branch_browse_acl2026","Branch-and-Browse: Efficient and Controllable Web Exploration with Tree-Structured Reasoning and Action Memory","https://aclanthology.org/2026.acl-long.838/",("web_exploration",),("decompose goal into explicit subtask tree","branch and backtrack at fine granularity","replay web state while background reasoning proceeds","share page-action memory within and across sessions"),("task_success","answer_accuracy","web_actions","backtracks","token_cost","wall_time"),("linear web agent","coarse tree search","memory-free web agent"),("without action memory","without state replay","linearized exploration"),P("branch_browse","decompose","select_branch","restore_state","browse","write_action_memory","evaluate_branch","backtrack_or_finish")),
PaperReproduction("webclipper_acl2026","WebClipper: Efficient Evolution of Web Agents with Graph-based Trajectory Pruning","https://aclanthology.org/2026.acl-long.988/",("deep_research_web",),("record web search as a state graph","mine a minimum-necessary DAG preserving successful evidence","prune cycles and unproductive branches","train/evaluate agents on pruned trajectories against unpruned controls"),("task_success","trajectory_length","tool_calls","token_cost","evidence_recall"),("unpruned trajectories","heuristic truncation","base web agent"),("without graph mining","without cycle removal","random pruning"),P("webclipper","collect_trajectory","build_state_graph","identify_evidence","mine_minimum_dag","prune","replay","evaluate")),
PaperReproduction("agentask_acl2026","AgentAsk: Multi-Agent Systems Need to Ask","https://aclanthology.org/2026.acl-long.1294/",("multiagent_reasoning",),("classify edge handoff failures into four paper error types","estimate whether clarification is required at each critical handoff","issue minimal clarification","continue collaboration and measure both quality and efficiency"),("accuracy","task_success","clarifications","token_cost","handoff_error_rate"),("single agent","vanilla MAS","CoT MAS"),("without clarification","clarify every edge","without error typing"),P("agentask","produce_message","classify_handoff","decide_clarification","ask","repair_message","continue_task","evaluate")),
PaperReproduction("eti_acl2026","Explicit Trait Inference for Multi-Agent Coordination","https://aclanthology.org/2026.acl-long.77/",("economic_games","multiagentbench"),("infer partner warmth and competence from interaction history","persist explicit partner trait profile","condition coordination decision on profile","evaluate controlled games and MultiAgentBench against CoT"),("payoff","payoff_loss","task_success","coordination_score","token_cost"),("CoT baseline","profile-free MAS","single-agent baseline"),("without warmth","without competence","randomized trait profile"),P("eti","observe_partner","infer_warmth","infer_competence","update_profile","coordinate","observe_outcome","revise_profile"),("45%-77% payoff-loss reduction in games reported","3%-29% MultiAgentBench improvement reported")),
PaperReproduction("extagents_acl2026","Scaling External Knowledge Input Beyond Context Windows of LLMs via Multi-Agent Collaboration","https://aclanthology.org/2026.acl-long.468/",("infinitybench_plus","long_survey_generation"),("partition external knowledge across parallel agents","process shards without extending individual context windows","coordinate evidence exchange and aggregation","scale input beyond context length while holding knowledge amount comparisons explicit"),("accuracy","evidence_recall","scaling_efficiency","token_cost","wall_time"),("single long-context agent","context compression","existing multi-agent orchestration"),("single worker","without cross-agent coordination","within-window-only input"),P("extagents","partition_knowledge","parallel_read","extract_evidence","coordinate","merge_evidence","reason","answer")),
)
PROGRAMS={r.method_id:r.compile() for r in REPRODUCTIONS}
__all__=["PaperReproduction","REPRODUCTIONS","PROGRAMS"]
