from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_SENTIENT_OSS_SURROGATE

AGENT_Q_PAPER_URI = "https://arxiv.org/abs/2408.07199"
@dataclass(frozen=True, slots=True)
class AgentQSurrogateFidelity:
    """Mechanism-conformance contract for the non-author-official Agent-Q implementation."""

    source: MethodSourceLane = SOURCE_SENTIENT_OSS_SURROGATE
    official_source_resolved: bool = False
    relation_to_paper: str = "independent_oss_surrogate_not_author_official"
    core_mcts_iterations_default: int = 10
    core_mcts_depth_default: int = 5
    core_mcts_exploration_default: float = 1.0
    core_mcts_simulation_default: str = "random"
    core_mcts_output_default: str = "max_reward"
    browser_invocation_iterations: int = 10
    browser_invocation_depth: int = 6
    browser_invocation_exploration: float = 1.0
    browser_invocation_simulation: str = "max"
    browser_invocation_output: str = "max_reward"
    terminal_reward: float = 1.0
    nonterminal_reward: float = -0.01
    terminal_judge_model: str = "gpt-4o-2024-08-06"
    iteration_environment_policy: str = "navigate_browser_to_homepage_before_each_mcts_iteration"
    dpo_pair_policy: str = "winning_path_action_preferred_over_each_sibling_action"
    dpo_state_dom_character_limit: int = 1000

    def __post_init__(self) -> None:
        if self.source.kind is not MethodSourceLaneKind.SURROGATE:
            raise ValueError("Agent Q discovered executable source must remain a surrogate lane")
        if self.official_source_resolved:
            raise ValueError("Agent Q author-official source remains unresolved")
        if self.relation_to_paper != "independent_oss_surrogate_not_author_official":
            raise ValueError("Agent Q surrogate relation must remain explicit")
        if (
            self.core_mcts_iterations_default,
            self.core_mcts_depth_default,
            self.core_mcts_exploration_default,
            self.core_mcts_simulation_default,
            self.core_mcts_output_default,
        ) != (10, 5, 1.0, "random", "max_reward"):
            raise ValueError("Agent Q generic MCTS defaults drifted")
        if (
            self.browser_invocation_iterations,
            self.browser_invocation_depth,
            self.browser_invocation_exploration,
            self.browser_invocation_simulation,
            self.browser_invocation_output,
        ) != (10, 6, 1.0, "max", "max_reward"):
            raise ValueError("Agent Q released browser-MCTS invocation drifted")
        if (self.terminal_reward, self.nonterminal_reward) != (1.0, -0.01):
            raise ValueError("Agent Q surrogate reward semantics drifted")
        if self.dpo_state_dom_character_limit != 1000:
            raise ValueError("Agent Q surrogate DPO state truncation drifted")

AGENT_Q_SURROGATE_FIDELITY = AgentQSurrogateFidelity()

__all__ = [
    "AGENT_Q_PAPER_URI",
    "AgentQSurrogateFidelity",
]
