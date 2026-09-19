from __future__ import annotations

from dataclasses import dataclass


WEBVOYAGER_V1_COMMIT = "091544539eba485dbd74ef3742011ddeede37336"


@dataclass(frozen=True, slots=True)
class WebVoyagerFidelity:
    paper_uri: str = "https://aclanthology.org/2024.acl-long.371/"
    source_repository: str = "https://github.com/MinorJerry/WebVoyager"
    audited_commit: str = WEBVOYAGER_V1_COMMIT
    source_artifacts: tuple[str, ...] = (
        "run.py",
        "run.sh",
        "prompts.py",
        "utils.py",
        "data/WebVoyager_data.jsonl",
    )
    benchmark_task_count: int = 643
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
    max_iterations: int = 15
    max_attached_images: int = 3
    model_temperature: float = 1.0
    model_seed: int = 42
    max_output_tokens: int = 1000
    strict_thought_action_format: bool = True
    wait_seconds: int = 5
    type_action_auto_enter: bool = True
    answer_is_terminal: bool = True
    numerical_element_grounding: bool = True
    live_web_environment: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("WebVoyager audited commit must be a git SHA")
        if self.source_artifacts != (
            "run.py",
            "run.sh",
            "prompts.py",
            "utils.py",
            "data/WebVoyager_data.jsonl",
        ):
            raise ValueError("WebVoyager source artifact cut drifted")
        if self.benchmark_task_count != 643:
            raise ValueError("WebVoyager official task count drifted")
        if self.observation_mode != "labeled_screenshot_plus_text":
            raise ValueError("WebVoyager visual observation semantics drifted")
        if self.text_only_alternative != "labeled_accessibility_tree":
            raise ValueError("WebVoyager text-only observation semantics drifted")
        if self.action_grammar != (
            "Click",
            "Type",
            "Scroll",
            "Wait",
            "GoBack",
            "Google",
            "ANSWER",
        ):
            raise ValueError("WebVoyager action grammar drifted")
        if (
            self.max_iterations,
            self.max_attached_images,
            self.model_temperature,
            self.model_seed,
            self.max_output_tokens,
        ) != (15, 3, 1.0, 42, 1000):
            raise ValueError("WebVoyager released run protocol drifted")
        if not all(
            (
                self.one_action_per_iteration,
                self.strict_thought_action_format,
                self.type_action_auto_enter,
                self.answer_is_terminal,
                self.numerical_element_grounding,
                self.live_web_environment,
            )
        ):
            raise ValueError("WebVoyager interaction semantics drifted")
        if self.wait_seconds != 5:
            raise ValueError("WebVoyager wait duration drifted")


WEBVOYAGER_FIDELITY = WebVoyagerFidelity()


__all__ = [
    "WEBVOYAGER_FIDELITY",
    "WEBVOYAGER_V1_COMMIT",
    "WebVoyagerFidelity",
]
