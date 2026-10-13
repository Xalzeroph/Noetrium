"""Frontier wave 14: ten peer-reviewed 2025 agent lineage reproductions.

The wave broadens Minecraft, embodied planning, multi-agent coordination,
multimodal memory, action deliberation, and domain-agent coverage.  Paper
reference results are provenance; measured Noetrium claims require execution
receipts from the bound benchmark environment.
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
            max_cycles=64,
            configuration={"paper_uri": self.paper_uri, "venue": self.venue, "benchmark_ids": self.benchmarks, "protocol": self.protocol, "baselines": self.baselines, "ablations": self.ablations},
            evidence_obligations=(self.method_id + ".phase-transcript", self.method_id + ".model-tool-receipts", self.method_id + ".metric-artifacts", self.method_id + ".result-table"),
            metric_names=self.metrics,
            artifact_kinds=(self.method_id + "_trajectory", self.method_id + "_experiment_manifest"),
        ).compile()

    def study(self):
        return PaperStudySpec(method_id=self.method_id, title=self.title, venue=self.venue, paper_uri=self.paper_uri, benchmark_ids=self.benchmarks, protocol=self.protocol, metrics=self.metrics, ablations=self.ablations)


def R(i, t, v, u, b, p, m, base, a, ph):
    return Reproduction(i, t, v, u, b, p, m, base, a, ph)


COMMON = (
    "freeze paper-faithful benchmark, model, environment, split, and seed identities",
    "run method and matched baselines under identical interaction and compute budgets",
    "persist episode-level Machine Journal receipts and aggregate metric artifacts",
    "keep paper-reported reference values separate from Noetrium-measured results",
)


REPRODUCTIONS = (
    R("causalmace_findings_emnlp2025", "CausalMACE: Causality Empowered Multi-Agents in Minecraft Cooperative Tasks", "Findings EMNLP 2025", "https://aclanthology.org/2025.findings-emnlp.777/", ("causalmace-minecraft-cooperative-tasks",), COMMON + ("reproduce cooperative Minecraft tasks with the paper task graph and causal dependency interventions",), ("task_success", "completion_steps", "cooperation_efficiency", "dependency_violations", "llm_calls"), ("single LLM agent", "multi-agent without causal intervention", "paper cooperative baselines"), ("no task graph", "no causal module", "no intervention", "single agent"), (("decompose", "causalmace.task_graph", "Construct the overarching task graph."), ("infer", "causalmace.causality", "Infer prerequisite and dependency relations."), ("intervene", "causalmace.intervention", "Apply rule-grounded causal intervention to resolve dependencies."), ("allocate", "causalmace.allocate", "Assign executable subtasks to collaborating agents."), ("execute", "causalmace.execute", "Execute assigned Minecraft skills and observe world effects."), ("update", "causalmace.update", "Update task and causal state until the cooperative goal terminates."))),
    R("sand_emnlp2025", "SAND: Boosting LLM Agents with Self-Taught Action Deliberation", "EMNLP 2025", "https://aclanthology.org/2025.emnlp-main.152/", ("sand-agent-action-suite",), COMMON + ("reproduce self-consistency candidate action sampling, execution-guided critique, and step-wise deliberation training/evaluation",), ("task_success", "action_accuracy", "trajectory_return", "interaction_steps", "token_cost"), ("ReAct-style SFT", "pairwise preference optimization", "base agent"), ("no candidate sampling", "no execution-guided critique", "no deliberation thoughts"), (("sample", "sand.sample", "Sample diverse candidate actions with self-consistency."), ("execute_candidates", "sand.execute", "Obtain environment-grounded feedback for candidate actions."), ("critique", "sand.critique", "Contrast candidates using execution-guided evidence."), ("deliberate", "sand.deliberate", "Synthesize step-wise action deliberation."), ("commit", "sand.commit", "Commit the selected action to the environment."), ("learn", "sand.learn", "Use self-taught deliberation trajectories for agent tuning."))),
    R("agentinit_findings_emnlp2025", "AgentInit: Initializing LLM-based Multi-Agent Systems via Diversity and Expertise Orchestration for Effective and Efficient Collaboration", "Findings EMNLP 2025", "https://aclanthology.org/2025.findings-emnlp.636/", ("agentinit-multi-agent-suite",), COMMON + ("reproduce reflective role generation, natural-language-to-format normalization, and Pareto-balanced team selection",), ("task_score", "token_consumption", "team_diversity", "task_relevance", "transfer_score"), ("pre-defined teams", "existing MAS initialization", "random role generation"), ("no reflection", "no format normalization", "diversity-only selection", "relevance-only selection"), (("generate", "agentinit.generate", "Generate candidate specialists through multi-round interaction."), ("reflect", "agentinit.reflect", "Refine candidate expertise and collaboration fit."), ("normalize", "agentinit.format", "Normalize generated agents into a consistent role schema."), ("score", "agentinit.score", "Measure team diversity and task relevance."), ("select", "agentinit.pareto", "Select a Pareto-balanced collaborating team."), ("collaborate", "agentinit.run", "Execute the downstream MAS with the selected initialization."))),
    R("swarmagentic_emnlp2025", "SwarmAgentic: Towards Fully Automated Agentic System Generation via Swarm Intelligence", "EMNLP 2025", "https://aclanthology.org/2025.emnlp-main.93/", ("swarmagentic-agent-generation-suite",), COMMON + ("reproduce population-based from-scratch agent generation and feedback-guided swarm optimization of functionality and collaboration",), ("task_score", "optimization_gain", "agent_generation_cost", "token_cost", "iterations_to_best"), ("manual agent design", "single-candidate optimization", "automated agent-generation baselines"), ("no population", "no feedback update", "fixed collaboration", "fixed agent functions"), (("initialize", "swarmagentic.population", "Generate a population of candidate agentic systems."), ("evaluate", "swarmagentic.evaluate", "Evaluate each candidate on the bound task suite."), ("feedback", "swarmagentic.feedback", "Convert task evidence into language feedback."), ("evolve", "swarmagentic.evolve", "Update functionality and collaboration using swarm-inspired exploration."), ("select", "swarmagentic.select", "Retain high-utility candidate systems."), ("repeat", "swarmagentic.repeat", "Iterate generation and optimization under the paper budget."))),
    R("bar_findings_acl2025", "BAR: A Backward Reasoning based Agent for Complex Minecraft Tasks", "Findings ACL 2025", "https://aclanthology.org/2025.findings-acl.318/", ("bar-complex-minecraft-tasks",), COMMON + ("reproduce goal-to-prerequisite backward reasoning followed by grounded forward Minecraft execution",), ("task_success", "subgoal_success", "planning_steps", "execution_steps", "llm_calls"), ("forward-planning Minecraft agent", "ReAct-style Minecraft agent", "paper Minecraft baselines"), ("no backward reasoning", "flat plan", "no replanning"), (("goal", "bar.goal", "Represent the terminal Minecraft goal and inventory constraints."), ("backchain", "bar.backward", "Recursively derive prerequisite subgoals and resources."), ("order", "bar.order", "Topologically order feasible prerequisite acquisition."), ("execute", "bar.execute", "Execute grounded Minecraft actions forward."), ("observe", "bar.observe", "Reconcile inventory and world state after execution."), ("replan", "bar.replan", "Backchain again when an expected prerequisite is unsatisfied."))),
    R("procworld_emnlp2025", "ProcWorld: Benchmarking Large Model Planning in Reachability-Constrained Environments", "EMNLP 2025", "https://aclanthology.org/2025.emnlp-main.635/", ("procworld",), COMMON + ("evaluate text and vision observation modes over the paper's 16 task types, 5,000 rooms, and reachability-constrained planning protocol",), ("task_success", "planning_accuracy", "reachability_validity", "localization_accuracy", "trajectory_length"), ("LLM planning baselines", "VLM planning baselines", "oracle-observation baseline"), ("text-only observation", "vision-only observation", "no active information gathering", "no state tracking"), (("observe", "procworld.observe", "Receive the configured partial text or visual observation."), ("localize", "procworld.localize", "Track latent spatial and dynamic state."), ("gather", "procworld.gather", "Actively gather information to disambiguate partial observations."), ("reason", "procworld.reachability", "Reject plans violating physical reachability constraints."), ("act", "procworld.act", "Issue the next text-grounded environment action."), ("score", "procworld.score", "Score success, validity, localization, and trajectory efficiency."))),
    R("demac_findings_emnlp2025", "DeMAC: Enhancing Multi-Agent Coordination with Dynamic DAG and Manager-Player Feedback", "Findings EMNLP 2025", "https://aclanthology.org/2025.findings-emnlp.757/", ("demac-overcooked",), COMMON + ("reproduce dynamic DAG strategic planning and manager-player dual feedback in changing Overcooked tasks",), ("task_reward", "completion_rate", "coordination_efficiency", "adaptation_score", "communication_cost"), ("traditional RL", "human-agent collaboration", "static multi-agent planner"), ("static DAG", "no manager feedback", "no player feedback", "no DAG"), (("plan", "demac.manager", "Create the current long-horizon manager strategy."), ("graph", "demac.dag", "Represent and dynamically update task dependencies as a DAG."), ("delegate", "demac.delegate", "Delegate executable nodes to player agents."), ("execute", "demac.players", "Execute coordinated environment actions."), ("feedback", "demac.dual_feedback", "Exchange manager-to-player and player-to-manager feedback."), ("adapt", "demac.adapt", "Revise the DAG and strategy after environment changes."))),
    R("docagent_emnlp2025", "DocAgent: An Agentic Framework for Multi-Modal Long-Context Document Understanding", "EMNLP 2025", "https://aclanthology.org/2025.emnlp-main.893/", ("docagent-long-document-suite",), COMMON + ("reproduce outline construction, interactive multimodal reading, reviewer cross-checking, and task-agnostic memory across both paper benchmarks",), ("answer_accuracy", "f1", "context_tokens", "retrieval_recall", "review_correction_rate"), ("long-context LLM", "RAG baseline", "single-agent document reader"), ("no outline", "no interactive reader", "no reviewer", "no memory bank"), (("outline", "docagent.outline", "Extract a structured tree outline from the document."), ("locate", "docagent.locate", "Identify sections relevant to the query."), ("read", "docagent.read", "Interactively retrieve textual and visual evidence."), ("answer", "docagent.answer", "Synthesize an evidence-grounded candidate answer."), ("review", "docagent.review", "Cross-check the answer against complementary sources."), ("remember", "docagent.memory", "Update the task-agnostic cross-task memory bank."))),
    R("quantagents_findings_emnlp2025", "QuantAgents: Towards Multi-agent Financial System via Simulated Trading", "Findings EMNLP 2025", "https://aclanthology.org/2025.findings-emnlp.945/", ("quantagents-three-year-market-simulation",), COMMON + ("reproduce the paper's three-year simulated-trading protocol with analyst, risk, news, and manager agents without using future information",), ("cumulative_return", "risk_adjusted_return", "max_drawdown", "prediction_accuracy", "turnover"), ("single financial agent", "post-reflection agent", "paper trading baselines"), ("no simulated-trading analyst", "no risk analyst", "no news analyst", "no predictive feedback"), (("simulate", "quantagents.simulation", "Generate simulated-trading analysis without future leakage."), ("risk", "quantagents.risk", "Assess portfolio and scenario risk."), ("news", "quantagents.news", "Analyze contemporaneous market news."), ("meet", "quantagents.meeting", "Exchange specialist evidence through the paper meeting protocol."), ("decide", "quantagents.manager", "Produce the manager trading decision."), ("feedback", "quantagents.feedback", "Score real-market performance and simulated prediction accuracy."))),
    R("ddo_emnlp2025", "DDO: Dual-Decision Optimization for LLM-Based Medical Consultation via Multi-Agent Collaboration", "EMNLP 2025", "https://aclanthology.org/2025.emnlp-main.1340/", ("ddo-medical-consultation-three-datasets",), COMMON + ("reproduce the three-dataset protocol while decoupling sequential symptom inquiry from disease diagnosis and optimizing their distinct objectives",), ("diagnosis_accuracy", "inquiry_efficiency", "symptom_recall", "consultation_turns", "combined_score"), ("single-agent consultation", "generation-based medical consultation", "paper LLM baselines"), ("shared objective", "no inquiry specialist", "no diagnosis specialist", "no multi-agent collaboration"), (("initialize", "ddo.case", "Initialize the patient evidence available at consultation start."), ("inquire", "ddo.inquiry", "Select the next symptom question as a sequential decision."), ("observe", "ddo.observe", "Update consultation evidence from the patient response."), ("diagnose", "ddo.diagnosis", "Classify disease hypotheses from accumulated evidence."), ("collaborate", "ddo.collaboration", "Exchange evidence between inquiry and diagnosis roles."), ("optimize", "ddo.objectives", "Apply the paper's distinct inquiry and diagnosis objectives."))),
)


def all_reproductions() -> tuple[Reproduction, ...]:
    return REPRODUCTIONS
