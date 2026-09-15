from __future__ import annotations

from dataclasses import dataclass


RAP_AUDITED_COMMIT = "774817c228b3d5ddfc18de2318f3476128ecf6eb"


@dataclass(frozen=True, slots=True)
class RAPFidelity:
    """Mechanism-level fidelity contract for paper-era RAP.

    LLaMA-1 deployment details remain matched-stack experiment configuration;
    the reproduction contract freezes the reasoning/planning semantics that
    distinguish RAP from generic tree search.
    """

    paper_uri: str = "https://arxiv.org/abs/2305.14992"
    source_repository: str = "https://github.com/Ber666/RAP"
    audited_commit: str = RAP_AUDITED_COMMIT
    mcts_source_artifact: str = "rap/mcts.py"
    blocksworld_source_artifact: str = "rap/blocksworld_mcts.py"
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

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("RAP audited commit must be a git SHA")
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


RAP_FIDELITY = RAPFidelity()


__all__ = ["RAP_AUDITED_COMMIT", "RAP_FIDELITY", "RAPFidelity"]
