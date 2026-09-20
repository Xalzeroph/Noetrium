"""Frontier wave 13: ten peer-reviewed 2025 agent lineage reproductions.

This wave emphasizes recent memory, embodied planning, multi-agent coordination,
self-improvement, tool reasoning, and generalist-agent training. Paper-private
semantics remain authoring data; measured claims require execution receipts.
"""
from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from research.authoring.frontier_2026.study import PaperStudySpec


@dataclass(frozen=True)
class Reproduction:
    method_id: str
    title: str
    venue: str
    paper_uri: str
    benchmarks: tuple[str, ...]
    protocol: tuple[str, ...]
    metrics: tuple[str, ...]
    baselines: tuple[str, ...]
    ablations: tuple[str, ...]
    phases: tuple[tuple[str, str, str], ...]

    def program(self):
        return AgentMethodSpec(
            method_id=self.method_id,
            implementation_version="paper-protocol",
            schema_version=self.method_id + ".phase-workflow.v1",
            phases=tuple(AgentPhaseSpec(*phase) for phase in self.phases),
            max_cycles=48,
            configuration={
                "paper_uri": self.paper_uri,
                "venue": self.venue,
                "benchmark_ids": self.benchmarks,
                "protocol": self.protocol,
                "baselines": self.baselines,
                "ablations": self.ablations,
            },
            evidence_obligations=(
                self.method_id + ".phase-transcript",
                self.method_id + ".model-tool-receipts",
                self.method_id + ".metric-artifacts",
                self.method_id + ".result-table",
            ),
            metric_names=self.metrics,
            artifact_kinds=(self.method_id + "_trajectory", self.method_id + "_experiment_manifest"),
        ).compile()

    def study(self):
        return PaperStudySpec(
            method_id=self.method_id,
            title=self.title,
            venue=self.venue,
            paper_uri=self.paper_uri,
            benchmark_ids=self.benchmarks,
            protocol=self.protocol,
            metrics=self.metrics,
            ablations=self.ablations,
        )


def R(i, t, v, u, b, p, m, base, a, ph):
    return Reproduction(i, t, v, u, b, p, m, base, a, ph)


COMMON = (
    "freeze paper-faithful benchmark/model/environment cuts and random seeds",
    "run the method and matched baselines under identical interaction and compute budgets",
    "persist episode-level Machine Journal receipts plus aggregate metric artifacts",
    "keep paper-reported reference values separate from Noetrium-measured results",
)


REPRODUCTIONS = (
    R(
        "hiagent_acl2025",
        "HiAgent: Hierarchical Working Memory Management for Solving Long-Horizon Agent Tasks with Large Language Model",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.1575/",
        ("hiagent-long-horizon-five-task-suite",),
        COMMON + ("evaluate hierarchical in-trial working-memory management across the paper's five long-horizon tasks",),
        ("task_success", "interaction_steps", "context_tokens", "subgoal_completion", "memory_compression_ratio"),
        ("full-history agent", "history-summary agent", "task-native baseline"),
        ("no subgoal chunking", "no proactive replacement", "retain full action-observation history"),
        (("plan", "hiagent.subgoal", "Form the current hierarchical subgoal."), ("act", "hiagent.act", "Choose an executable action from current working memory."), ("observe", "hiagent.observe", "Append environment feedback to the active chunk."), ("compress", "hiagent.compress", "Replace completed subgoal history with its summarized observation."), ("retain", "hiagent.retain", "Keep only action-observation evidence relevant to the active subgoal."), ("repeat", "hiagent.repeat", "Continue until task completion or the paper budget is exhausted.")),
    ),
    R(
        "citynavagent_acl2025",
        "CityNavAgent: Aerial Vision-and-Language Navigation with Hierarchical Semantic Planning and Global Memory",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.1511/",
        ("citynav-continuous-aerial-vln",),
        COMMON + ("evaluate aerial VLN in continuous urban environments with the paper's hierarchical semantic planning protocol",),
        ("success_rate", "spl", "navigation_error", "trajectory_length", "revisit_success"),
        ("direct LLM navigator", "flat semantic planner", "memory-free aerial VLN agent"),
        ("no hierarchical semantic planning", "no global topological memory", "single semantic level"),
        (("perceive", "citynav.observe", "Ground aerial visual observation and instruction."), ("decompose", "citynav.hspm", "Generate semantic subgoals at multiple abstraction levels."), ("localize", "citynav.localize", "Ground the active semantic target in continuous city space."), ("navigate", "citynav.navigate", "Execute continuous aerial navigation toward the active target."), ("remember", "citynav.memory", "Update the global topological trajectory graph."), ("reuse", "citynav.revisit", "Exploit global memory when navigating to previously visited targets.")),
    ),
    R(
        "agentgym_acl2025",
        "AgentGym: Evaluating and Training Large Language Model-based Agents across Diverse Environments",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.1355/",
        ("agentgym-14-environments-89-tasks",),
        COMMON + ("reproduce concurrent interaction across 14 environments and 89 tasks, then evaluate self-improvement/training transfer",),
        ("task_success", "environment_macro_average", "trajectory_quality", "interaction_turns", "generalization_success"),
        ("zero-shot base model", "commercial-agent reference", "single-environment trained agent"),
        ("no interactive exploration", "no trajectory training", "single-environment training"),
        (("bind", "agentgym.bind", "Bind one task to its real-time environment."), ("interact", "agentgym.interact", "Run multi-turn agent-environment interaction."), ("collect", "agentgym.collect", "Persist successful and failed trajectories."), ("learn", "agentgym.learn", "Improve the policy from collected interaction data."), ("transfer", "agentgym.transfer", "Evaluate the learned agent across heterogeneous environments."), ("aggregate", "agentgym.aggregate", "Compute task-, environment-, and suite-level results.")),
    ),
    R(
        "anymac_emnlp2025",
        "AnyMAC: Cascading Flexible Multi-Agent Collaboration via Next-Agent Prediction",
        "EMNLP 2025",
        "https://aclanthology.org/2025.emnlp-main.584/",
        ("anymac-collaborative-reasoning-suite",),
        COMMON + ("compare dynamic sequential collaboration against fixed and graph-based communication topologies",),
        ("final_accuracy", "collaboration_gain", "agent_calls", "context_tokens", "communication_efficiency"),
        ("single agent", "fixed multi-agent chain", "graph-topology multi-agent system"),
        ("fixed next-agent order", "no next-context selection", "full-history context"),
        (("initialize", "anymac.roles", "Instantiate candidate specialist roles."), ("select_agent", "anymac.next_agent", "Predict the most useful next agent for the current state."), ("select_context", "anymac.next_context", "Select relevant evidence from arbitrary prior collaboration steps."), ("reason", "anymac.reason", "Generate the selected agent's contribution."), ("cascade", "anymac.cascade", "Append the contribution and repeat dynamic routing."), ("finalize", "anymac.finalize", "Terminate collaboration and produce the final answer.")),
    ),
    R(
        "godel_agent_acl2025",
        "Godel Agent: A Self-Referential Agent Framework for Recursively Self-Improvement",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.1354/",
        ("godel-agent-multidomain-suite",),
        COMMON + ("start from the paper seed agent and reproduce iterative self-modification under high-level objective feedback",),
        ("task_success", "improvement_delta", "optimization_iterations", "token_cost", "cross_domain_generalization"),
        ("fixed handcrafted agent", "predefined meta-optimizer", "prompt-only self-reflection"),
        ("no self-code modification", "fixed optimization routine", "single improvement iteration"),
        (("evaluate", "godel.evaluate", "Evaluate the current agent implementation on the development objective."), ("diagnose", "godel.diagnose", "Inspect failures and current agent logic."), ("propose", "godel.propose", "Generate a self-modification without a predefined optimization operator."), ("apply", "godel.apply", "Construct the candidate agent implementation."), ("verify", "godel.verify", "Evaluate the candidate under the same objective and budget."), ("recurse", "godel.recurse", "Adopt beneficial modifications and continue recursive improvement.")),
    ),
    R(
        "agentic_reasoning_acl2025",
        "Agentic Reasoning: A Streamlined Framework for Enhancing LLM Reasoning with Agentic Tools",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.1383/",
        ("agentic-reasoning-deep-research-suite",),
        COMMON + ("reproduce coordinated web-search, code-execution and mind-map memory tool use on complex reasoning tasks",),
        ("answer_accuracy", "search_recall", "tool_calls", "evidence_coverage", "token_cost"),
        ("base reasoning model", "web-search-only agent", "unstructured-memory tool agent"),
        ("no mind-map memory", "no code agent", "no web-search agent"),
        (("parse", "agentic_reasoning.parse", "Decompose the research question into evidence needs."), ("search", "agentic_reasoning.search", "Run the optimized web-search agent."), ("compute", "agentic_reasoning.code", "Invoke code execution for computational subproblems."), ("organize", "agentic_reasoning.mindmap", "Store evidence and logical relations in structured memory."), ("reason", "agentic_reasoning.reason", "Integrate tool evidence through the evolving mind map."), ("answer", "agentic_reasoning.answer", "Produce a final evidence-grounded solution.")),
    ),
    R(
        "samule_emnlp2025",
        "SAMULE: Self-Learning Agents Enhanced by Multi-level Reflection",
        "EMNLP 2025",
        "https://aclanthology.org/2025.emnlp-main.839/",
        ("samule-self-learning-agent-suite",),
        COMMON + ("reproduce retrospective-model training from micro-, meso-, and macro-level reflection synthesis",),
        ("task_success", "reflection_gain", "error_recurrence", "cross_task_transfer", "sample_efficiency"),
        ("no-reflection agent", "single-trajectory reflection", "successful-trajectory self-learning"),
        ("no micro reflection", "no intra-task reflection", "no inter-task reflection"),
        (("attempt", "samule.attempt", "Run task attempts and retain both successes and failures."), ("micro", "samule.micro", "Synthesize single-trajectory error corrections."), ("meso", "samule.meso", "Induce error taxonomies across trials of the same task."), ("macro", "samule.macro", "Extract transferable lessons from same-typed errors across tasks."), ("train", "samule.train", "Train the retrospective language model on multi-level reflections."), ("reflect", "samule.infer", "Generate retrospective guidance during future agent inference.")),
    ),
    R(
        "agentrm_acl2025",
        "AgentRM: Enhancing Agent Generalization with Reward Modeling",
        "ACL 2025",
        "https://aclanthology.org/2025.acl-long.945/",
        ("agentrm-nine-task-four-category-suite",),
        COMMON + ("evaluate the 8B reward model on nine tasks/four categories and reproduce test-time Best-of-N plus beam-search guidance",),
        ("task_success", "heldout_gain", "reward_accuracy", "best_of_n_gain", "beam_search_gain"),
        ("non-finetuned 8B policy", "direct policy fine-tuning", "LLM-as-a-judge reward"),
        ("no reward model", "explicit versus implicit reward modeling", "no test-time search"),
        (("sample", "agentrm.sample", "Generate candidate agent actions or trajectories."), ("score", "agentrm.reward", "Score candidates with the learned generalizable reward model."), ("search", "agentrm.search", "Perform Best-of-N or reward-guided beam search."), ("select", "agentrm.select", "Select the highest-valued behavior."), ("execute", "agentrm.execute", "Execute selected behavior in the task environment."), ("evaluate", "agentrm.evaluate", "Measure held-in, unseen-task, and weak-to-strong generalization.")),
    ),
    R(
        "cfgm_emnlp2025",
        "Coarse-to-Fine Grounded Memory for LLM Agent Planning",
        "EMNLP 2025",
        "https://aclanthology.org/2025.emnlp-main.659/",
        ("cfgm-agent-planning-suite",),
        COMMON + ("reproduce coarse focus-point grounding, experience collection, hybrid-grained tip extraction and memory-guided planning",),
        ("task_success", "planning_steps", "memory_retrieval_precision", "generalization_success", "token_cost"),
        ("memory-free planner", "trajectory-memory planner", "single-granularity memory agent"),
        ("no coarse focus points", "no fine actionable tips", "single-granularity memory"),
        (("ground_coarse", "cfgm.focus", "Ground environmental knowledge into coarse focus points."), ("collect", "cfgm.collect", "Collect targeted experiences around grounded focus points."), ("ground_fine", "cfgm.tips", "Extract actionable hybrid-grained tips from experiences."), ("retrieve", "cfgm.retrieve", "Retrieve coarse and fine memory for the current planning state."), ("plan", "cfgm.plan", "Adapt retrieved knowledge into an executable plan."), ("act", "cfgm.act", "Execute the plan and record outcome evidence.")),
    ),
    R(
        "memoryos_emnlp2025",
        "Memory OS of AI Agent",
        "EMNLP 2025",
        "https://aclanthology.org/2025.emnlp-main.1318/",
        ("locomo",),
        COMMON + ("reproduce hierarchical memory integration and dynamic updating on LoCoMo using the paper evaluation protocol",),
        ("f1", "bleu1", "retrieval_recall", "memory_latency", "memory_size"),
        ("RAG memory", "flat long-term memory", "full-conversation context"),
        ("no hierarchy", "no dynamic update", "single memory tier"),
        (("ingest", "memoryos.ingest", "Encode new conversational experience."), ("route", "memoryos.route", "Route evidence into the appropriate hierarchical memory tier."), ("update", "memoryos.update", "Dynamically consolidate and update stored memory."), ("retrieve", "memoryos.retrieve", "Retrieve cross-tier evidence for the current query."), ("compose", "memoryos.compose", "Compose retrieved memory into coherent response context."), ("evaluate", "memoryos.evaluate", "Measure LoCoMo retention and response quality.")),
    ),
)

PROGRAMS = {reproduction.method_id: reproduction.program() for reproduction in REPRODUCTIONS}
STUDY_SPECS = {reproduction.method_id: reproduction.study() for reproduction in REPRODUCTIONS}

__all__ = ["REPRODUCTIONS", "PROGRAMS", "STUDY_SPECS"]
