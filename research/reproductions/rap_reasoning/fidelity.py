from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane
from .source import SOURCE_OFFICIAL_RAP_REPO



@dataclass(frozen=True, slots=True)
class RAPFidelity:
    """Paper-era RAP semantics plus the released Blocksworld experiment cut."""

    paper_uri: str = "https://arxiv.org/abs/2305.14992"
    source: MethodSourceLane = SOURCE_OFFICIAL_RAP_REPO
    mcts_source_artifact: str = "rap/mcts.py"
    blocksworld_source_artifact: str = "rap/blocksworld_mcts.py"
    runner_source_artifact: str = "run_blocksworld.py"
    same_llm_reasoner_and_world_model: bool = True
    action_prior_name: str = "r0"
    world_state_reward_name: str = "r1"
    nonnegative_reward_combination: str = "r0**alpha * r1**(1-alpha)"
    negative_reward_combination: str = "min(r0, r1)"
    blocksworld_success_reward: float = 100.0
    blocksworld_partial_reward_offset: float = 0.5
    mcts_prior: bool = True
    mcts_reward_aggregation: str = "mean"
    mcts_child_aggregation: str = "max"
    seed: int = 0
    temperature: float = 0.6
    rollouts: int = 10
    max_depth: int = 4
    n_sample_confidence: int = 10
    alpha: float = 0.5
    r1_default: float = 0.5
    exploration_weight: float = 1.0
    discount: float = 1.0

    def __post_init__(self) -> None:
        if not self.same_llm_reasoner_and_world_model:
            raise ValueError("RAP requires the LM to serve reasoning-agent and world-model roles")
        if (self.action_prior_name, self.world_state_reward_name) != ("r0", "r1"):
            raise ValueError("RAP reward component identities drifted")
        if self.nonnegative_reward_combination != "r0**alpha * r1**(1-alpha)":
            raise ValueError("RAP nonnegative reward aggregation drifted")
        if self.negative_reward_combination != "min(r0, r1)":
            raise ValueError("RAP negative reward aggregation drifted")
        if (self.blocksworld_success_reward, self.blocksworld_partial_reward_offset) != (100.0, 0.5):
            raise ValueError("RAP Blocksworld state-reward semantics drifted")
        if (self.mcts_prior, self.mcts_reward_aggregation, self.mcts_child_aggregation) != (True, "mean", "max"):
            raise ValueError("RAP Blocksworld MCTS configuration drifted")
        if (
            self.seed,
            self.temperature,
            self.rollouts,
            self.max_depth,
            self.n_sample_confidence,
            self.alpha,
            self.r1_default,
            self.exploration_weight,
            self.discount,
        ) != (0, 0.6, 10, 4, 10, 0.5, 0.5, 1.0, 1.0):
            raise ValueError("RAP released Blocksworld experiment configuration drifted")


RAP_FIDELITY = RAPFidelity()


__all__ = ["RAP_FIDELITY", "RAPFidelity"]
