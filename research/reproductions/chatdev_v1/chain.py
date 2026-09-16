from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


class ChatDevV1PhaseKind(StrEnum):
    SIMPLE = "SimplePhase"
    COMPOSED = "ComposedPhase"


@dataclass(frozen=True, slots=True)
class ChatDevV1SimplePhaseSpec:
    name: str
    assistant_role: str
    user_role: str
    max_turns: int
    reflect: bool = False

    def __post_init__(self) -> None:
        for field_name in ("name", "assistant_role", "user_role"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"ChatDev v1 {field_name} must be canonical non-empty text")
        if type(self.max_turns) is not int or not 1 <= self.max_turns <= 100:
            raise ValueError("ChatDev v1 simple phase max_turns must be in [1, 100]")
        if type(self.reflect) is not bool:
            raise TypeError("ChatDev v1 simple phase reflect must be bool")


@dataclass(frozen=True, slots=True)
class ChatDevV1ComposedPhaseSpec:
    name: str
    cycle_limit: int
    composition: tuple[ChatDevV1SimplePhaseSpec, ...]
    stop_condition: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or self.name != self.name.strip():
            raise ValueError("ChatDev v1 composed phase name must be canonical non-empty text")
        if type(self.cycle_limit) is not int or self.cycle_limit <= 0:
            raise ValueError("ChatDev v1 composed phase cycle_limit must be positive")
        if not isinstance(self.composition, tuple) or not self.composition or any(
            not isinstance(phase, ChatDevV1SimplePhaseSpec) for phase in self.composition
        ):
            raise TypeError("ChatDev v1 composed phase requires simple phase composition")
        if not isinstance(self.stop_condition, str) or not self.stop_condition.strip():
            raise ValueError("ChatDev v1 composed phase stop_condition is required")


CHATDEV_V1_SIMPLE_PHASES = {
    "DemandAnalysis": ChatDevV1SimplePhaseSpec(
        "DemandAnalysis", "Chief Product Officer", "Chief Executive Officer", 10, True
    ),
    "LanguageChoose": ChatDevV1SimplePhaseSpec(
        "LanguageChoose", "Chief Technology Officer", "Chief Executive Officer", 10, True
    ),
    "Coding": ChatDevV1SimplePhaseSpec(
        "Coding", "Programmer", "Chief Technology Officer", 1, False
    ),
    "CodeComplete": ChatDevV1SimplePhaseSpec(
        "CodeComplete", "Programmer", "Chief Technology Officer", 1, False
    ),
    "CodeReviewComment": ChatDevV1SimplePhaseSpec(
        "CodeReviewComment", "Code Reviewer", "Programmer", 1, False
    ),
    "CodeReviewModification": ChatDevV1SimplePhaseSpec(
        "CodeReviewModification", "Programmer", "Code Reviewer", 1, False
    ),
    "TestErrorSummary": ChatDevV1SimplePhaseSpec(
        "TestErrorSummary", "Programmer", "Software Test Engineer", 1, False
    ),
    "TestModification": ChatDevV1SimplePhaseSpec(
        "TestModification", "Programmer", "Software Test Engineer", 1, False
    ),
    "EnvironmentDoc": ChatDevV1SimplePhaseSpec(
        "EnvironmentDoc", "Programmer", "Chief Technology Officer", 1, True
    ),
    "Manual": ChatDevV1SimplePhaseSpec(
        "Manual", "Chief Product Officer", "Chief Executive Officer", 1, False
    ),
}

CHATDEV_V1_COMPOSED_PHASES = {
    "CodeCompleteAll": ChatDevV1ComposedPhaseSpec(
        "CodeCompleteAll",
        10,
        (CHATDEV_V1_SIMPLE_PHASES["CodeComplete"],),
        "unimplemented_file_is_empty",
    ),
    "CodeReview": ChatDevV1ComposedPhaseSpec(
        "CodeReview",
        3,
        (
            CHATDEV_V1_SIMPLE_PHASES["CodeReviewComment"],
            CHATDEV_V1_SIMPLE_PHASES["CodeReviewModification"],
        ),
        "modification_conclusion_contains_info_finished",
    ),
    "Test": ChatDevV1ComposedPhaseSpec(
        "Test",
        3,
        (
            CHATDEV_V1_SIMPLE_PHASES["TestErrorSummary"],
            CHATDEV_V1_SIMPLE_PHASES["TestModification"],
        ),
        "exist_bugs_flag_is_false",
    ),
}

CHATDEV_V1_TOP_LEVEL_CHAIN = (
    CHATDEV_V1_SIMPLE_PHASES["DemandAnalysis"],
    CHATDEV_V1_SIMPLE_PHASES["LanguageChoose"],
    CHATDEV_V1_SIMPLE_PHASES["Coding"],
    CHATDEV_V1_COMPOSED_PHASES["CodeCompleteAll"],
    CHATDEV_V1_COMPOSED_PHASES["CodeReview"],
    CHATDEV_V1_COMPOSED_PHASES["Test"],
    CHATDEV_V1_SIMPLE_PHASES["EnvironmentDoc"],
    CHATDEV_V1_SIMPLE_PHASES["Manual"],
)


@dataclass(frozen=True, slots=True)
class ChatDevV1PhaseReceipt:
    """Downstream phase result identity; platform journals remain the durable authority."""

    phase_name: str
    input_state_digest: str
    output_state_digest: str
    cycle_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.phase_name, str) or not self.phase_name.strip():
            raise ValueError("ChatDev v1 phase receipt name is required")
        require_sha256(self.input_state_digest, "ChatDev v1 input_state_digest")
        require_sha256(self.output_state_digest, "ChatDev v1 output_state_digest")
        if type(self.cycle_index) is not int or self.cycle_index < 0:
            raise ValueError("ChatDev v1 phase receipt cycle_index must be non-negative")

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = [
    "CHATDEV_V1_COMPOSED_PHASES",
    "CHATDEV_V1_SIMPLE_PHASES",
    "CHATDEV_V1_TOP_LEVEL_CHAIN",
    "ChatDevV1ComposedPhaseSpec",
    "ChatDevV1PhaseKind",
    "ChatDevV1PhaseReceipt",
    "ChatDevV1SimplePhaseSpec",
]
