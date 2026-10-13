from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class PromptOutcomeLink:
    request_id: str
    prompt_digest: str
    task_id: str
    decision_cycle_id: str
    action_id: str | None
    verified_action_success: bool | None
    task_success: bool | None
    utility: float | None
    contract_repairs: int

    def __post_init__(self) -> None:
        if self.utility is not None and (
            isinstance(self.utility, bool)
            or not isinstance(self.utility, (int, float))
            or not math.isfinite(float(self.utility))
        ):
            raise ValueError("prompt outcome utility must be finite")
        if type(self.contract_repairs) is not int or self.contract_repairs < 0:
            raise ValueError("prompt outcome contract_repairs must be non-negative")


@dataclass(frozen=True, slots=True)
class PromptOutcomeSummary:
    prompt_digest: str
    observations: int
    verified_action_success_rate: float | None
    task_success_rate: float | None
    mean_utility: float | None
    effect_claim_authorized: bool = False

    def __post_init__(self) -> None:
        if type(self.observations) is not int or self.observations < 0:
            raise ValueError("prompt outcome observations must be non-negative")
        for field in ("verified_action_success_rate", "task_success_rate"):
            value = getattr(self, field)
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= value <= 1
            ):
                raise ValueError(f"prompt outcome {field} must be finite and within [0, 1]")
        if self.mean_utility is not None and (
            isinstance(self.mean_utility, bool)
            or not isinstance(self.mean_utility, (int, float))
            or not math.isfinite(float(self.mean_utility))
        ):
            raise ValueError("prompt outcome mean_utility must be finite")


def summarize_outcomes(prompt_digest: str, links: tuple[PromptOutcomeLink, ...]) -> PromptOutcomeSummary:
    rows=[x for x in links if x.prompt_digest==prompt_digest]
    action=[x.verified_action_success for x in rows if x.verified_action_success is not None]
    task=[x.task_success for x in rows if x.task_success is not None]
    util=[x.utility for x in rows if x.utility is not None]
    return PromptOutcomeSummary(prompt_digest,len(rows),sum(action)/len(action) if action else None,sum(task)/len(task) if task else None,sum(util)/len(util) if util else None,False)
