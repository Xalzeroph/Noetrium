from __future__ import annotations

from dataclasses import dataclass


WEBVOYAGER_V1_COMMIT = "091544539eba485dbd74ef3742011ddeede37336"


@dataclass(frozen=True, slots=True)
class WebVoyagerFidelity:
    paper_uri: str = "https://arxiv.org/abs/2401.13919"
    source_repository: str = "https://github.com/MinorJerry/WebVoyager"
    audited_commit: str = WEBVOYAGER_V1_COMMIT
    source_artifact: str = "prompts.py"
    observation_mode: str = "labeled_screenshot_plus_text"
    text_only_alternative: str = "labeled_accessibility_tree"
    one_action_per_iteration: bool = True
    action_grammar: tuple[str, ...] = (
        "Click",
        "Type",
        "Scroll",
        "Wait",
        "GoBack",
        "Google",
        "ANSWER",
    )
    wait_seconds: int = 5
    type_action_auto_enter: bool = True
    answer_is_terminal: bool = True
    numerical_element_grounding: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("WebVoyager audited commit must be a git SHA")
        if self.observation_mode != "labeled_screenshot_plus_text":
            raise ValueError("WebVoyager visual observation semantics drifted")
        if self.text_only_alternative != "labeled_accessibility_tree":
            raise ValueError("WebVoyager text-only observation semantics drifted")
        if self.action_grammar != ("Click", "Type", "Scroll", "Wait", "GoBack", "Google", "ANSWER"):
            raise ValueError("WebVoyager action grammar drifted")
        if not all((self.one_action_per_iteration, self.type_action_auto_enter, self.answer_is_terminal, self.numerical_element_grounding)):
            raise ValueError("WebVoyager interaction semantics drifted")
        if self.wait_seconds != 5:
            raise ValueError("WebVoyager wait duration drifted")


WEBVOYAGER_FIDELITY = WebVoyagerFidelity()


__all__ = ["WEBVOYAGER_FIDELITY", "WEBVOYAGER_V1_COMMIT", "WebVoyagerFidelity"]
