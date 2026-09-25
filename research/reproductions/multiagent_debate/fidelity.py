from __future__ import annotations

from dataclasses import dataclass


MULTIAGENT_DEBATE_AUDITED_COMMIT = "9b32e0971105a3ada91706d130582bde9b9a855c"


@dataclass(frozen=True, slots=True)
class MultiAgentDebateFidelity:
    """GSM8K mechanism fidelity for the original multi-agent debate release."""

    paper_uri: str = "https://arxiv.org/abs/2305.14325"
    source_repository: str = "https://github.com/composable-models/llm_multiagent_debate"
    audited_commit: str = MULTIAGENT_DEBATE_AUDITED_COMMIT
    source_artifact: str = "gsm/gen_gsm.py"
    default_agent_count: int = 3
    default_round_count: int = 2
    independent_agent_contexts: bool = True
    first_round_independent: bool = True
    subsequent_round_uses_other_agents_previous_round: bool = True
    round_information_semantics: str = "synchronous_previous_round_snapshot"
    self_previous_response_remains_in_local_context: bool = True
    peer_responses_are_injected_as_user_information: bool = True
    final_answer_format: str = "boxed_single_number"
    model_at_audited_gsm_script: str = "gpt-3.5-turbo-0301"

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("multi-agent debate audited commit must be a git SHA")
        if (self.default_agent_count, self.default_round_count) != (3, 2):
            raise ValueError("audited GSM debate defaults drifted")
        if not all((
            self.independent_agent_contexts,
            self.first_round_independent,
            self.subsequent_round_uses_other_agents_previous_round,
            self.self_previous_response_remains_in_local_context,
            self.peer_responses_are_injected_as_user_information,
        )):
            raise ValueError("multi-agent debate exchange semantics drifted")
        if self.round_information_semantics != "synchronous_previous_round_snapshot":
            raise ValueError("multi-agent debate round snapshot semantics drifted")
        if self.final_answer_format != "boxed_single_number":
            raise ValueError("audited GSM answer format drifted")


MULTIAGENT_DEBATE_FIDELITY = MultiAgentDebateFidelity()


__all__ = [
    "MULTIAGENT_DEBATE_AUDITED_COMMIT",
    "MULTIAGENT_DEBATE_FIDELITY",
    "MultiAgentDebateFidelity",
]
