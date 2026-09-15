from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelfRefineFidelity:
    """Mechanism-level fidelity contract from the official Self-Refine release.

    Task-specific prompt text, datasets, stopping signals and attempt budgets are
    intentionally not elevated into Platform defaults. A matched benchmark lane
    must freeze those values from the selected upstream task implementation.
    """

    paper_uri: str = "https://arxiv.org/abs/2303.17651"
    source_repository: str = "https://github.com/madaan/self-refine"
    mechanism: tuple[str, ...] = ("init", "feedback", "iterate")
    training_free: bool = True
    same_model_reused_across_roles: bool = True
    task_specific_attempt_budget: bool = True
    task_specific_stop_condition: bool = True

    def __post_init__(self) -> None:
        if self.mechanism != ("init", "feedback", "iterate"):
            raise ValueError("Self-Refine fidelity requires init -> feedback -> iterate")
        if not self.training_free:
            raise ValueError("Self-Refine baseline is training-free")
        if not self.same_model_reused_across_roles:
            raise ValueError("Self-Refine baseline reuses one model across method roles")
        if not self.task_specific_attempt_budget or not self.task_specific_stop_condition:
            raise ValueError("Self-Refine task-level stopping semantics must remain explicit")


SELF_REFINE_FIDELITY = SelfRefineFidelity()


__all__ = ["SELF_REFINE_FIDELITY", "SelfRefineFidelity"]
