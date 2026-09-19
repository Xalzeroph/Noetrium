from __future__ import annotations

from dataclasses import dataclass


SELF_REFINE_PAPER_ERA_COMMIT = "a56d135a49cdc9183e7db2527458822753a1f2c0"


@dataclass(frozen=True, slots=True)
class SelfRefineFidelity:
    """Mechanism-level fidelity contract from the official Self-Refine release.

    Task-specific prompt text, datasets, stopping signals and attempt budgets are
    intentionally not elevated into Platform defaults. A matched benchmark lane
    must freeze those values from the selected upstream task implementation.
    """

    paper_uri: str = "https://arxiv.org/abs/2303.17651"
    source_repository: str = "https://github.com/madaan/self-refine"
    audited_commit: str = SELF_REFINE_PAPER_ERA_COMMIT
    mechanism: tuple[str, ...] = ("init", "feedback", "iterate")
    training_free: bool = True
    same_model_reused_across_roles: bool = True
    task_specific_attempt_budget: bool = True
    task_specific_stop_condition: bool = True
    commongen_max_attempts: int = 4
    commongen_temperature: float = 0.7
    commongen_max_output_tokens: int = 300
    commongen_init_prompt_blob: str = "2f12bb9ea789faae0c3ee4a925e78e1d9e22b336"
    commongen_feedback_prompt_blob: str = "73af28c9a8dd10739dca5493bee9823495b4407a"
    commongen_iterate_prompt_blob: str = "e221cc4a277e6569ac3a67cb1813fa8221fb8771"
    commongen_stop_condition: str = "concept_feedback_none_and_commonsense_feedback_none"

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40 or any(ch not in "0123456789abcdef" for ch in self.audited_commit):
            raise ValueError("Self-Refine audited commit must be a full git SHA")
        if self.mechanism != ("init", "feedback", "iterate"):
            raise ValueError("Self-Refine fidelity requires init -> feedback -> iterate")
        if not self.training_free:
            raise ValueError("Self-Refine baseline is training-free")
        if not self.same_model_reused_across_roles:
            raise ValueError("Self-Refine baseline reuses one model across method roles")
        if not self.task_specific_attempt_budget or not self.task_specific_stop_condition:
            raise ValueError("Self-Refine task-level stopping semantics must remain explicit")
        if self.commongen_max_attempts != 4:
            raise ValueError("Self-Refine CommonGen batch attempt budget drifted")
        if self.commongen_temperature != 0.7 or self.commongen_max_output_tokens != 300:
            raise ValueError("Self-Refine CommonGen decoding defaults drifted")
        if self.commongen_stop_condition != "concept_feedback_none_and_commonsense_feedback_none":
            raise ValueError("Self-Refine CommonGen stopping condition drifted")
        for blob in (
            self.commongen_init_prompt_blob,
            self.commongen_feedback_prompt_blob,
            self.commongen_iterate_prompt_blob,
        ):
            if len(blob) != 40 or any(ch not in "0123456789abcdef" for ch in blob):
                raise ValueError("Self-Refine CommonGen prompt artifact must be a git blob SHA")


SELF_REFINE_FIDELITY = SelfRefineFidelity()


__all__ = ["SELF_REFINE_FIDELITY", "SELF_REFINE_PAPER_ERA_COMMIT", "SelfRefineFidelity"]
