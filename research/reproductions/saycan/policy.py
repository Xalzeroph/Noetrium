from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SayCanSkillScore:
    skill: str
    llm_log_score: float
    affordance_score: float
    combined_score: float
    normalized_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.skill, str) or not self.skill.strip():
            raise ValueError("SayCan skill identity must be non-empty")
        for name in (
            "llm_log_score",
            "affordance_score",
            "combined_score",
            "normalized_score",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"SayCan {name} must be finite")
        if not 0.0 <= float(self.affordance_score) <= 1.0:
            raise ValueError("SayCan affordance_score must be in [0, 1]")
        if float(self.combined_score) < 0.0:
            raise ValueError("SayCan combined_score must be non-negative")
        if not 0.0 <= float(self.normalized_score) <= 1.0:
            raise ValueError("SayCan normalized_score must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SayCanSelection:
    selected_skill: str
    scores: tuple[SayCanSkillScore, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.selected_skill, str) or not self.selected_skill.strip():
            raise ValueError("SayCan selected_skill must be non-empty")
        if not self.scores:
            raise ValueError("SayCan selection requires scored skills")
        if self.selected_skill not in {row.skill for row in self.scores}:
            raise ValueError("SayCan selected_skill must belong to score table")


def select_saycan_skill(
    llm_log_scores: Mapping[str, float],
    affordance_scores: Mapping[str, float],
) -> SayCanSelection:
    """Compose language and affordance scores exactly at the method layer.

    Noetrium may provide model calls, capability descriptions and embodied skill
    execution, but this exp(language) * affordance policy remains SayCan semantics.
    """

    if not isinstance(llm_log_scores, Mapping) or not isinstance(affordance_scores, Mapping):
        raise TypeError("SayCan scores must be mappings")
    llm_keys = set(llm_log_scores)
    affordance_keys = set(affordance_scores)
    if not llm_keys or llm_keys != affordance_keys:
        raise ValueError("SayCan language and affordance scores must cover the same non-empty skill set")
    if any(not isinstance(skill, str) or not skill.strip() for skill in llm_keys):
        raise ValueError("SayCan skill identities must be non-empty strings")

    raw_rows: list[tuple[str, float, float, float]] = []
    for skill in sorted(llm_keys):
        language = llm_log_scores[skill]
        affordance = affordance_scores[skill]
        if not isinstance(language, (int, float)) or isinstance(language, bool) or not math.isfinite(float(language)):
            raise ValueError("SayCan LLM log-scores must be finite numbers")
        if not isinstance(affordance, (int, float)) or isinstance(affordance, bool) or not math.isfinite(float(affordance)):
            raise ValueError("SayCan affordance scores must be finite numbers")
        affordance_value = float(affordance)
        if not 0.0 <= affordance_value <= 1.0:
            raise ValueError("SayCan affordance scores must be in [0, 1]")
        combined = math.exp(float(language)) * affordance_value
        if not math.isfinite(combined):
            raise ValueError("SayCan combined score overflowed")
        raw_rows.append((skill, float(language), affordance_value, combined))

    total = sum(row[3] for row in raw_rows)
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("SayCan combined scores must contain positive mass")

    rows = tuple(
        SayCanSkillScore(
            skill=skill,
            llm_log_score=language,
            affordance_score=affordance,
            combined_score=combined,
            normalized_score=combined / total,
        )
        for skill, language, affordance, combined in raw_rows
    )
    selected = max(rows, key=lambda row: (row.normalized_score, row.skill))
    return SayCanSelection(selected.skill, rows)


__all__ = ["SayCanSelection", "SayCanSkillScore", "select_saycan_skill"]
