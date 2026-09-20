"""Executable 2026 frontier reproduction wave.

This module is deliberately not a campaign-only paper list.  Each entry freezes
paper provenance, benchmark/environment bindings, experimental protocol,
baselines, measurements, reported claims, and compiles the paper-owned method
semantics into the canonical MethodProgram ABI.  Runtime truth, effects,
checkpoint/replay, evidence and metric artifacts remain platform-owned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.workflow.api.authoring import (
    AgentMethodSpec,
    AgentPhaseSpec,
)
from noetrium_platform.research.execution.workflow.api.method_machine import MethodProgram


@dataclass(frozen=True, slots=True)
class BenchmarkBinding:
    benchmark_id: str
    source_uri: str
    split_requirement: str
    environment_requirement: str

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark_id", self.benchmark_id),
            ("source_uri", self.source_uri),
            ("split_requirement", self.split_requirement),
            ("environment_requirement", self.environment_requirement),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"2026 reproduction benchmark {name} must be non-empty")


@dataclass(frozen=True, slots=True)
class Frontier2026Reproduction:
    method_id: str
    title: str
    venue: str
    paper_uri: str
    families: tuple[str, ...]
    phases: tuple[AgentPhaseSpec, ...]
    benchmarks: tuple[BenchmarkBinding, ...]
    protocol: tuple[str, ...]
    metrics: tuple[str, ...]
    baselines: tuple[str, ...]
    ablations: tuple[str, ...]
    reported_claims: tuple[str, ...]
    platform_host: tuple[str, ...]
    execution_blockers: tuple[str, ...]
    cyclic: bool = False
    max_cycles: int = 1
    reproduction_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("method_id", self.method_id),
            ("title", self.title),
            ("venue", self.venue),
            ("paper_uri", self.paper_uri),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"2026 reproduction {name} must be non-empty")
        for name in (
            "families",
            "phases",
            "benchmarks",
            "protocol",
            "metrics",
            "baselines",
            "ablations",
            "reported_claims",
            "platform_host",
            "execution_blockers",
        ):
            value = getattr(self, name)
            if type(value) is not tuple or not value:
                raise ValueError(f"{self.method_id} {name} must be a non-empty tuple")
        if self.cyclic and self.max_cycles < 1:
            raise ValueError(f"{self.method_id} max_cycles must be positive")
        object.__setattr__(
            self,
            "reproduction_digest",
            canonical_digest(
                {
                    "method_id": self.method_id,
                    "title": self.title,
                    "venue": self.venue,
                    "paper_uri": self.paper_uri,
                    "families": self.families,
                    "phases": tuple(
                        {
                            "phase_id": p.phase_id,
                            "agent_id": p.agent_id,
                            "instruction": p.instruction,
                            "max_visits": p.max_visits,
                        }
                        for p in self.phases
                    ),
                    "benchmarks": tuple(
                        {
                            "benchmark_id": b.benchmark_id,
                            "source_uri": b.source_uri,
                            "split_requirement": b.split_requirement,
                            "environment_requirement": b.environment_requirement,
                        }
                        for b in self.benchmarks
                    ),
                    "protocol": self.protocol,
                    "metrics": self.metrics,
                    "baselines": self.baselines,
                    "ablations": self.ablations,
                    "reported_claims": self.reported_claims,
                    "platform_host": self.platform_host,
                    "execution_blockers": self.execution_blockers,
                    "cyclic": self.cyclic,
                    "max_cycles": self.max_cycles,
                }
            ),
        )

    def compile_program(self) -> MethodProgram:
        configuration = {
            "paper": self.title,
            "venue": self.venue,
            "paper_uri": self.paper_uri,
            "families": self.families,
            "benchmark_ids": tuple(b.benchmark_id for b in self.benchmarks),
            "protocol": self.protocol,
            "ablations": self.ablations,
            "reproduction_digest": self.reproduction_digest,
            "paper_private_semantics": True,
        }
        return AgentMethodSpec(
            method_id=self.method_id,
            implementation_version="paper-semantic-v1",
            schema_version="noetrium.frontier-2026-reproduction.v1",
            phases=self.phases,
            max_cycles=self.max_cycles if self.cyclic else None,
            configuration=configuration,
            metric_names=self.metrics,
            artifact_kinds=(
                "benchmark_manifest",
                "method_trace",
                "metric_bundle",
                "machine_journal_receipts",
                "evidence_bundle",
            ),
        ).compile()


def _b(
    benchmark_id: str,
    source_uri: str,
    split_requirement: str,
    environment_requirement: str,
) -> BenchmarkBinding:
    return BenchmarkBinding(
        benchmark_id=benchmark_id,
        source_uri=source_uri,
        split_requirement=split_requirement,
        environment_requirement=environment_requirement,
    )


REPRODUCTIONS = (
    Frontier2026Reproduction(
        method_id="agemem_acl2026",
        title="Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.981/",
        families=("memory", "long-horizon", "reinforcement-learning", "tool-use"),
        phases=(
            AgentPhaseSpec("observe", "agemem.policy", "Observe task state and current short-term/long-term memory."),
            AgentPhaseSpec("memory_action", "agemem.policy", "Choose a tool-like memory action: store, retrieve, update, summarize, discard, or no-op."),
            AgentPhaseSpec("apply_memory", "agemem.memory", "Apply the chosen memory action without changing platform memory authority."),
            AgentPhaseSpec("reason_act", "agemem.policy", "Reason with the resulting memory view and emit the next environment action."),
            AgentPhaseSpec("learn_signal", "agemem.training", "Record step-wise outcome/process signal used by the paper's progressive RL policy."),
        ),
        benchmarks=(
            _b("alfworld", "https://github.com/alfworld/alfworld", "paper ACL-2026 evaluation cut", "paper-compatible ALFWorld runtime"),
            _b("scienceworld", "https://github.com/allenai/ScienceWorld", "paper ACL-2026 evaluation cut", "paper-compatible ScienceWorld runtime"),
            _b("agentboard-pddl", "https://github.com/hkust-nlp/AgentBoard", "paper PDDL evaluation cut", "AgentBoard PDDL runtime"),
            _b("babyai", "https://github.com/mila-iqia/babyai", "paper ACL-2026 evaluation cut", "BabyAI environment"),
            _b("hotpotqa", "https://hotpotqa.github.io/", "paper agentic-search cut", "retrieval/search environment frozen to paper"),
        ),
        protocol=(
            "evaluate Qwen2.5-7B-Instruct and Qwen3-4B-Instruct paper settings separately",
            "reproduce the three-stage progressive reinforcement-learning schedule",
            "reproduce step-wise GRPO memory-action optimization",
            "preserve identical benchmark access across memory baselines",
            "report per-benchmark and macro-average performance plus context/token efficiency",
        ),
        metrics=("task_success", "average_score", "memory_quality", "context_tokens", "memory_action_count"),
        baselines=("No-Memory", "LangMem", "A-Mem", "Mem0", "Mem0g", "AgeMem-noRL"),
        ablations=("no reinforcement learning", "no long-term memory", "no short-term memory", "restricted memory action set"),
        reported_claims=(
            "Qwen2.5-7B AgeMem reports 41.07/35.55/17.31/61.42/54.44 on ALFWorld/SciWorld/PDDL/BabyAI/HotpotQA, average 41.96.",
            "Qwen3-4B AgeMem reports 48.97/59.48/35.07/72.56/55.49, average 54.31.",
        ),
        platform_host=("MethodProgram", "MemoryMachine", "CapabilityMachine", "ExperimentMachine", "MachineJournal"),
        execution_blockers=("freeze released training code/checkpoint and exact benchmark revisions", "real model/environment execution still required"),
        cyclic=True,
        max_cycles=128,
    ),
    Frontier2026Reproduction(
        method_id="mm_mem_acl2026",
        title="From Verbatim to Gist: Distilling Pyramidal Multimodal Memory via Semantic Information Bottleneck for Long-Horizon Video Agents",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.533/",
        families=("multimodal-memory", "video-agent", "long-horizon", "reinforcement-learning"),
        phases=(
            AgentPhaseSpec("sensory_buffer", "mm_mem.encoder", "Encode incoming visual evidence into fine-grained sensory traces."),
            AgentPhaseSpec("episodic_stream", "mm_mem.memory", "Distill sensory traces into an episodic stream while preserving task-relevant details."),
            AgentPhaseSpec("symbolic_schema", "mm_mem.memory", "Compress episodic evidence into high-level symbolic gist schemas."),
            AgentPhaseSpec("sib_decision", "mm_mem.policy", "Choose ADD_NEW, MERGE, or DISCARD under the Semantic Information Bottleneck objective."),
            AgentPhaseSpec("topdown_retrieval", "mm_mem.retriever", "Retrieve memory top-down using entropy-driven selection."),
            AgentPhaseSpec("answer", "mm_mem.reasoner", "Answer the current video query from retrieved multimodal memory."),
        ),
        benchmarks=(
            _b("video-mme", "https://video-mme.github.io/", "official paper evaluation split", "offline long-video QA"),
            _b("hd-epic", "https://github.com/hgaurav2k/HD-EPIC", "paper evaluation split", "egocentric long-video QA"),
            _b("mlvu", "https://github.com/JUNJIE99/MLVU", "development/evaluation cut used by released code", "long-video understanding"),
            _b("vstream-qa", "https://github.com/EliSpectre/MM-Mem", "released VStream-QA protocol", "streaming video QA"),
        ),
        protocol=(
            "train SIB-GRPO memory decisions with the released ADD_NEW/MERGE/DISCARD action space",
            "preserve composite reward: VQA correctness, supervisor signal, and caption-length penalty",
            "evaluate offline and streaming benchmarks separately",
            "report memory compression/latency alongside task quality",
        ),
        metrics=("qa_accuracy", "streaming_score", "memory_tokens", "compression_ratio", "latency", "memory_action_distribution"),
        baselines=("dense visual memory", "text-centric caption memory", "released MM-Mem baseline scripts"),
        ablations=("without SIB-GRPO", "without symbolic schema", "without entropy retrieval", "single-level memory"),
        reported_claims=("ACL final paper reports state-of-the-art results across four offline/streaming long-video benchmarks.",),
        platform_host=("MethodProgram", "MemoryMachine", "PerceptionMachine", "ModelInvocationMachine", "MachineJournal"),
        execution_blockers=("freeze MM-Mem checkpoint/configuration and four benchmark media cuts", "GPU video-model execution required"),
        cyclic=False,
    ),
    Frontier2026Reproduction(
        method_id="mem_gallery_acl2026",
        title="Mem-Gallery: Benchmarking Multimodal Long-Term Conversational Memory for MLLM Agents",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.1892/",
        families=("multimodal-memory", "benchmark", "conversation", "long-term-memory"),
        phases=(
            AgentPhaseSpec("session_ingest", "mem_gallery.evaluator", "Feed the frozen multimodal multi-session conversation history."),
            AgentPhaseSpec("memory_extract_adapt", "mem_gallery.evaluator", "Evaluate memory extraction and test-time adaptation."),
            AgentPhaseSpec("memory_reason", "mem_gallery.evaluator", "Evaluate reasoning over cross-session multimodal memories."),
            AgentPhaseSpec("knowledge_manage", "mem_gallery.evaluator", "Evaluate memory knowledge organization and evolution."),
            AgentPhaseSpec("score", "mem_gallery.evaluator", "Aggregate capability and efficiency measurements."),
        ),
        benchmarks=(
            _b("mem-gallery", "https://github.com/YuanchenBei/Mem-Gallery", "ACL-2026 released dataset split", "multimodal multi-session conversation replay"),
        ),
        protocol=(
            "reproduce all three functional evaluation dimensions",
            "benchmark the twelve memory systems from the final paper under matched context budgets",
            "retain image/text dependencies across sessions",
            "report capability and efficiency separately",
        ),
        metrics=("memory_extraction", "test_time_adaptation", "memory_reasoning", "knowledge_management", "token_efficiency", "latency"),
        baselines=("twelve memory systems evaluated in ACL final paper",),
        ablations=("text-only history", "no explicit multimodal retention", "no memory organization"),
        reported_claims=("Final paper benchmarks twelve memory systems and identifies multimodal retention, reasoning, knowledge-management, and efficiency bottlenecks.",),
        platform_host=("BenchmarkMachine", "MemoryMachine", "PerceptionMachine", "EvaluationMachine", "EvidenceBundle"),
        execution_blockers=("freeze released Mem-Gallery dataset/scoring revision and all baseline model revisions", "multimodal inference required"),
    ),
    Frontier2026Reproduction(
        method_id="os_symphony_acl2026",
        title="OS-Symphony: A Holistic Framework for Robust and Generalist Computer-Using Agents",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.1021/",
        families=("gui-agent", "multimodal-memory", "tool-agent", "long-horizon"),
        phases=(
            AgentPhaseSpec("orchestrate", "os_symphony.orchestrator", "Route the task between reflection-memory and versatile tool agents."),
            AgentPhaseSpec("retrieve_milestones", "os_symphony.memory", "Retrieve milestone-driven long-term trajectory memory."),
            AgentPhaseSpec("search_tutorial", "os_symphony.searcher", "Use the SeeAct multimodal browser searcher to synthesize a visually aligned tutorial when needed."),
            AgentPhaseSpec("execute", "os_symphony.tool_agent", "Execute the next computer action using current tutorial and memory context."),
            AgentPhaseSpec("reflect", "os_symphony.memory", "Curate/prune visual history and write trajectory-level corrective memory."),
        ),
        benchmarks=(
            _b("osworld-verified", "https://github.com/xlang-ai/OSWorld", "paper verified online cut", "Ubuntu desktop VM"),
            _b("windowsagentarena", "https://github.com/microsoft/WindowsAgentArena", "paper online cut", "Windows VM"),
            _b("macosarena", "https://github.com/OS-Copilot/OS-Symphony", "paper online cut", "macOS environment"),
        ),
        protocol=(
            "match 50-step and 100-step budgets where reported",
            "evaluate proprietary and open VLM backbones separately",
            "preserve browser-sandbox tutorial search and visual-context pruning",
            "record trajectory-level corrections in long-term memory",
        ),
        metrics=("task_success_rate", "steps", "tutorial_search_count", "memory_corrections", "model_calls", "token_cost"),
        baselines=("backbone computer-use agent without OS-Symphony", "paper online CUA baselines"),
        ablations=("without reflection-memory agent", "without multimodal searcher", "without visual-history pruning"),
        reported_claims=("ACL final paper reports 65.84% on OSWorld and state-of-the-art performance on three online OS benchmarks.",),
        platform_host=("MethodProgram", "MemoryMachine", "CapabilityMachine", "EnvironmentMachine", "MachineJournal"),
        execution_blockers=("freeze OS images, online benchmark revisions, browser sandbox, prompts and model snapshots", "OS VM execution required"),
        cyclic=True,
        max_cycles=100,
    ),
    Frontier2026Reproduction(
        method_id="implement_acl2026",
        title="Model-Based Imaginative Planning for Embodied Agents",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.827/",
        families=("embodied", "world-model", "planning", "test-time-scaling"),
        phases=(
            AgentPhaseSpec("perceive_symbolic", "implement.world_model", "Convert raw visual observation into object-centric symbolic state."),
            AgentPhaseSpec("propose_actions", "implement.llm", "Propose candidate actions from the current symbolic state and goal."),
            AgentPhaseSpec("imagine_futures", "implement.world_model", "Predict Monte Carlo future states for candidate actions using temperature sampling."),
            AgentPhaseSpec("rank_refine", "implement.llm", "Rank imagined trajectories and refine the decision."),
            AgentPhaseSpec("execute", "implement.agent", "Execute the selected action in the embodied environment."),
            AgentPhaseSpec("meta_icl_update", "implement.world_model", "Condition the world model on new interaction history for unseen-environment adaptation."),
        ),
        benchmarks=(
            _b("alfworld", "https://github.com/alfworld/alfworld", "ACL-2026 paper split", "visual/embodied ALFWorld configuration used by paper"),
        ),
        protocol=(
            "keep the LLM frozen during imaginative planning",
            "reproduce Monte Carlo state prediction by temperature sampling",
            "reproduce Meta In-Context Learning world-model adaptation",
            "compare finetuning and strong test-time-scaling baselines under matched budgets",
        ),
        metrics=("task_success", "planning_accuracy", "world_model_prediction", "imagined_rollouts", "steps", "model_calls"),
        baselines=("finetuning-based embodied agents", "test-time scaling baselines", "LLM executor without world-model imagination"),
        ablations=("without world model", "single deterministic future", "without Meta-ICL", "without online policy refinement"),
        reported_claims=("ACL final paper reports consistent advantages on ALFWorld over finetuning and strong test-time-scaling approaches.",),
        platform_host=("MethodProgram", "EnvironmentMachine", "PerceptionMachine", "ModelInvocationMachine", "MachineJournal"),
        execution_blockers=("freeze world-model checkpoint and exact ALFWorld visual configuration", "GPU/environment execution required"),
        cyclic=True,
        max_cycles=64,
    ),
    Frontier2026Reproduction(
        method_id="orbit_acl2026",
        title="On-policy Reinforcement Fine-tuning with Offline reward for Multi-step Embodied Planning",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.1822/",
        families=("embodied", "planning", "reinforcement-learning", "multimodal"),
        phases=(
            AgentPhaseSpec("collect_onpolicy", "orbit.policy", "Collect on-policy multi-step embodied planning trajectories."),
            AgentPhaseSpec("offline_reward", "orbit.reward", "Score collected trajectories with the paper's offline reward mechanism."),
            AgentPhaseSpec("reinforcement_update", "orbit.training", "Apply reinforcement fine-tuning using offline reward."),
            AgentPhaseSpec("evaluate_id", "orbit.evaluator", "Evaluate in-domain EmbodiedBench tasks."),
            AgentPhaseSpec("evaluate_ood", "orbit.evaluator", "Evaluate out-of-domain EmbodiedBench tasks."),
        ),
        benchmarks=(
            _b("embodiedbench", "https://github.com/EmbodiedBench/EmbodiedBench", "paper in-domain and out-of-domain cuts", "four interactive EmbodiedBench environments"),
        ),
        protocol=(
            "reproduce on-policy collection and offline reward computation as distinct phases",
            "evaluate both in-domain and out-of-domain settings",
            "hold environment interaction budget fixed across RL baselines",
            "preserve visual observations and multi-step action semantics",
        ),
        metrics=("task_success", "in_domain_success", "out_of_domain_success", "reward", "interaction_cost", "training_cost"),
        baselines=("base VLM planner", "online RL/RFT baselines", "supervised/frozen planner controls"),
        ablations=("without offline reward", "off-policy-only training", "without reinforcement fine-tuning"),
        reported_claims=("ACL final paper evaluates ORBIT on EmbodiedBench in both in-domain and out-of-domain scenarios.",),
        platform_host=("ResearchProgram", "EnvironmentMachine", "PerceptionMachine", "OptimizationMachine", "EvaluationMachine"),
        execution_blockers=("freeze ORBIT checkpoint/training config and EmbodiedBench revision", "GPU training and interactive environment execution required"),
    ),
    Frontier2026Reproduction(
        method_id="eaglet_acl2026",
        title="A Goal Without a Plan Is Just a Wish: Efficient and Effective Global Planner Training for Long-Horizon Agent Tasks",
        venue="ACL 2026",
        paper_uri="https://aclanthology.org/2026.acl-long.597/",
        families=("planning", "long-horizon", "reinforcement-learning", "agent-training"),
        phases=(
            AgentPhaseSpec("plan_synthesis", "eaglet.teacher", "Synthesize candidate global plans from an advanced teacher LLM."),
            AgentPhaseSpec("consensus_filter", "eaglet.filter", "Apply homologous consensus filtering to retain high-quality plans."),
            AgentPhaseSpec("cold_start_sft", "eaglet.training", "Fine-tune the plug-and-play planner on filtered plans."),
            AgentPhaseSpec("capability_gain_rl", "eaglet.training", "Optimize the planner with rule-based executor capability gain reward."),
            AgentPhaseSpec("plan_execute", "eaglet.planner", "Generate a global plan and execute it with the frozen/base executor agent."),
        ),
        benchmarks=(
            _b("scienceworld", "https://github.com/allenai/ScienceWorld", "seen and unseen paper splits", "ScienceWorld runtime"),
            _b("alfworld", "https://github.com/alfworld/alfworld", "seen and unseen paper splits", "ALFWorld runtime"),
            _b("webshop", "https://github.com/princeton-nlp/WebShop", "paper seen evaluation split", "WebShop environment"),
        ),
        protocol=(
            "reproduce teacher-plan synthesis and homologous consensus filtering",
            "reproduce SFT cold start before rule-based RL",
            "use executor capability gain rather than a learned reward model",
            "report seen/unseen splits separately and matched training cost",
        ),
        metrics=("task_success", "seen_success", "unseen_success", "training_cost", "planner_tokens", "executor_capability_gain"),
        baselines=("executor without planner", "SFT-only planner", "RL-based planner baselines", "MPO", "KnowAgent"),
        ablations=("without consensus filtering", "SFT-only", "without capability-gain reward", "implicit planning"),
        reported_claims=("ACL final paper reports new SOTA across three long-horizon tasks and approximately 8x lower training cost than RL-based baselines.",),
        platform_host=("ResearchProgram", "MethodProgram", "OptimizationMachine", "EnvironmentMachine", "EvaluationMachine"),
        execution_blockers=("freeze released planner training data/configuration, model revisions and benchmark cuts", "planner training/model execution required"),
    ),
    Frontier2026Reproduction(
        method_id="refact_cvpr2026",
        title="ReFAct: Empowering Multimodal Web Agents with Visual and Context Focusing",
        venue="CVPR 2026",
        paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html",
        families=("multimodal-web-agent", "active-perception", "memory", "context-management"),
        phases=(
            AgentPhaseSpec("reason", "refact.reasoner", "Reason over the current multimodal web-search state."),
            AgentPhaseSpec("ground_focus", "refact.grounding", "Actively ground and crop/filter visual information relevant to the current reasoning step."),
            AgentPhaseSpec("defocus_refocus", "refact.memory", "Use external-memory Defocus/Refocus operations to control retained context density."),
            AgentPhaseSpec("act", "refact.agent", "Execute the next web-search/navigation action."),
            AgentPhaseSpec("observe", "refact.agent", "Observe new multimodal evidence and update context."),
        ),
        benchmarks=(
            _b("groundedvqa", "https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html", "CVPR-2026 released benchmark", "multimodal web-search environment"),
        ),
        protocol=(
            "reproduce GroundedVQA flexible-complexity evaluation",
            "preserve active Grounding-tool calls and external memory operations",
            "compare on the additional public agentic benchmarks from the final paper",
            "measure quality against context density and visual-noise complexity",
        ),
        metrics=("answer_accuracy", "task_success", "grounding_accuracy", "context_tokens", "visual_focus_operations", "latency"),
        baselines=("base multimodal web-search agent", "paper web-agent baselines"),
        ablations=("without Grounding tool", "without Defocus/Refocus memory", "without active focusing"),
        reported_claims=("CVPR final paper reports consistent gains on GroundedVQA and additional widely-used agentic benchmarks.",),
        platform_host=("MethodProgram", "PerceptionMachine", "MemoryMachine", "CapabilityMachine", "EnvironmentMachine"),
        execution_blockers=("freeze GroundedVQA release, web state, model/prompts and grounding implementation", "multimodal web execution required"),
        cyclic=True,
        max_cycles=32,
    ),
    Frontier2026Reproduction(
        method_id="ego2web_cvpr2026",
        title="Ego2Web: A Web Agent Benchmark Grounded in Egocentric Videos",
        venue="CVPR 2026",
        paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html",
        families=("benchmark", "egocentric-video", "web-agent", "multimodal"),
        phases=(
            AgentPhaseSpec("video_understand", "ego2web.agent", "Extract task-relevant evidence from first-person video."),
            AgentPhaseSpec("goal_ground", "ego2web.agent", "Ground the online task in the observed physical-world evidence."),
            AgentPhaseSpec("web_plan", "ego2web.agent", "Plan the required online workflow."),
            AgentPhaseSpec("web_execute", "ego2web.agent", "Execute web actions under the frozen benchmark environment."),
            AgentPhaseSpec("judge", "ego2web.judge", "Score completion with Ego2WebJudge and retain judge evidence."),
        ),
        benchmarks=(
            _b("ego2web", "https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html", "CVPR-2026 final video-task pairs", "egocentric-video plus web execution"),
        ),
        protocol=(
            "preserve human-verified video-task pairs and task categories",
            "evaluate video understanding, web planning and interaction jointly",
            "run task-design ablations from the final paper",
            "validate automatic judge agreement against human labels",
        ),
        metrics=("task_success", "video_understanding", "web_execution_success", "judge_human_agreement", "steps", "latency"),
        baselines=("SoTA web agents evaluated in final paper", "video-ablated controls", "existing automatic web-agent judges"),
        ablations=("without video evidence", "weakened video understanding", "judge alternatives"),
        reported_claims=("Ego2WebJudge reports approximately 84% agreement with human judgment; evaluated SoTA agents retain substantial headroom.",),
        platform_host=("BenchmarkMachine", "PerceptionMachine", "EnvironmentMachine", "EvaluationMachine", "EvidenceBundle"),
        execution_blockers=("freeze released videos/tasks, website state and judge model/configuration", "web and video execution required"),
    ),
    Frontier2026Reproduction(
        method_id="mmbench_gui_cvpr2026",
        title="MMBench-GUI: A Unified Hierarchical Evaluation Framework for Multi-Platform GUI Agents",
        venue="CVPR 2026",
        paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html",
        families=("benchmark", "gui-agent", "multiplatform", "evaluation"),
        phases=(
            AgentPhaseSpec("content_understanding", "mmbench_gui.evaluator", "Evaluate GUI content understanding."),
            AgentPhaseSpec("element_grounding", "mmbench_gui.evaluator", "Evaluate visual element grounding."),
            AgentPhaseSpec("task_automation", "mmbench_gui.evaluator", "Evaluate end-to-end task automation."),
            AgentPhaseSpec("task_collaboration", "mmbench_gui.evaluator", "Evaluate cross-application/task collaboration."),
            AgentPhaseSpec("eqa_score", "mmbench_gui.evaluator", "Compute Efficiency-Quality-Aware score using success and action redundancy."),
        ),
        benchmarks=(
            _b("mmbench-gui", "https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html", "CVPR-2026 final hierarchy", "Windows/macOS/Linux/iOS/Android/Web environments"),
        ),
        protocol=(
            "run all four hierarchy levels",
            "preserve six-platform evaluation",
            "report success and action redundancy jointly through EQA",
            "stratify complex and cross-application tasks",
        ),
        metrics=("content_understanding", "element_grounding", "task_success", "task_collaboration", "action_redundancy", "eqa"),
        baselines=("GUI agents evaluated in final CVPR paper",),
        ablations=("grounding-module analysis", "single-platform vs cross-platform", "quality-only vs EQA"),
        reported_claims=("CVPR final paper finds visual grounding critical and substantial action inefficiency across existing GUI agents.",),
        platform_host=("BenchmarkMachine", "EnvironmentMachine", "PerceptionMachine", "EvaluationMachine", "MachineJournal"),
        execution_blockers=("freeze benchmark release and six platform images/states", "multi-platform GUI execution required"),
    ),
    Frontier2026Reproduction(
        method_id="echotrail_gui_cvprf2026",
        title="EchoTrail-GUI: Building Actionable Memory for GUI Agents via Critic-Guided Self-Exploration",
        venue="CVPR 2026 Findings",
        paper_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html",
        families=("gui-agent", "memory", "self-exploration", "multimodal"),
        phases=(
            AgentPhaseSpec("explore", "echotrail.explorer", "Autonomously explore GUI tasks and collect candidate successful trajectories."),
            AgentPhaseSpec("critic_validate", "echotrail.critic", "Validate explored trajectories using the reward/critic model."),
            AgentPhaseSpec("store_memory", "echotrail.memory", "Store validated task trajectories as actionable memories."),
            AgentPhaseSpec("retrieve_memory", "echotrail.memory", "Retrieve relevant prior trajectories for a new GUI task."),
            AgentPhaseSpec("guided_inference", "echotrail.agent", "Inject retrieved trajectories as in-context guidance and execute the task."),
        ),
        benchmarks=(
            _b("androidworld", "https://github.com/google-research/android_world", "paper CVPRF-2026 split", "Android emulator"),
            _b("androidlab", "https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html", "paper CVPRF-2026 split", "AndroidLab environment"),
        ),
        protocol=(
            "construct the memory database only from autonomously explored critic-validated successes",
            "freeze retrieval policy and injection format",
            "compare before/after memory injection on AndroidWorld and AndroidLab",
            "report operational efficiency as well as task success",
        ),
        metrics=("task_success_rate", "steps", "trajectory_acceptance", "memory_retrieval_hit", "token_cost"),
        baselines=("same GUI agent without memory", "paper GUI-agent baselines"),
        ablations=("without critic validation", "without memory retrieval", "random trajectory injection"),
        reported_claims=("CVPR Findings paper reports significant success-rate and efficiency improvements on AndroidWorld and AndroidLab.",),
        platform_host=("MethodProgram", "MemoryMachine", "EnvironmentMachine", "EvaluationMachine", "MachineJournal"),
        execution_blockers=("freeze released exploration trajectories/reward model and Android benchmark revisions", "Android runtime/model execution required"),
    ),
    Frontier2026Reproduction(
        method_id="star_toggle_cvpr2026",
        title="See, Think, Act: Teaching Multimodal Agents to Effectively Interact with GUI by Identifying Toggles",
        venue="CVPR 2026",
        paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html",
        families=("gui-agent", "state-reasoning", "multimodal", "grounding"),
        phases=(
            AgentPhaseSpec("see", "star.perception", "Perceive the current binary toggle state from the GUI."),
            AgentPhaseSpec("think_goal", "star.reasoner", "Infer the desired toggle state from the user instruction."),
            AgentPhaseSpec("compare", "star.reasoner", "Compare current and desired states and decide whether interaction is required."),
            AgentPhaseSpec("act_or_noop", "star.agent", "Execute the toggle interaction only when state transition is required."),
            AgentPhaseSpec("verify", "star.perception", "Verify post-action state and preserve evidence."),
        ),
        benchmarks=(
            _b("state-control-benchmark", "https://github.com/ZrW00/StaR", "CVPR-2026 released binary-toggle benchmark", "GUI image/dynamic interaction environment"),
        ),
        protocol=(
            "evaluate all four multimodal agents from the final paper",
            "separate already-correct-state cases from required-toggle cases",
            "run the three additional public agentic benchmarks",
            "evaluate the dynamic environment separately",
        ),
        metrics=("toggle_execution_accuracy", "task_success", "false_action_rate", "grounding_accuracy", "steps"),
        baselines=("same four multimodal agents without StaR", "paper GUI-agent baselines"),
        ablations=("without explicit current-state perception", "without desired-state inference", "always-act policy"),
        reported_claims=("CVPR final paper reports over 30% improvement in toggle instruction execution accuracy across four multimodal agents.",),
        platform_host=("MethodProgram", "PerceptionMachine", "EnvironmentMachine", "EvaluationMachine", "MachineJournal"),
        execution_blockers=("freeze released State Control Benchmark and agent/model revisions", "dynamic GUI execution required"),
        cyclic=False,
    ),
)


REPRODUCTION_BY_ID = {row.method_id: row for row in REPRODUCTIONS}
if len(REPRODUCTION_BY_ID) != len(REPRODUCTIONS):
    raise RuntimeError("2026 frontier reproduction method ids must be unique")

PROGRAM_BY_ID = {row.method_id: row.compile_program() for row in REPRODUCTIONS}


def by_id(method_id: str) -> Frontier2026Reproduction:
    try:
        return REPRODUCTION_BY_ID[method_id]
    except KeyError as exc:
        raise KeyError(f"unknown 2026 frontier reproduction: {method_id}") from exc


__all__ = [
    "BenchmarkBinding",
    "Frontier2026Reproduction",
    "PROGRAM_BY_ID",
    "REPRODUCTIONS",
    "REPRODUCTION_BY_ID",
    "by_id",
]
