from __future__ import annotations

from dataclasses import dataclass

from .semantics import normalize_model_action


@dataclass(frozen=True, slots=True)
class ReactTrajectoryStep:
    action: str
    observation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", normalize_model_action(self.action))
        if not isinstance(self.observation, str):
            raise TypeError("ReAct trajectory observation must be text")


@dataclass(frozen=True, slots=True)
class ReactAlfworldTranscript:
    """Method-owned transcript semantics, independent of OS persistence."""

    initial_observation: str
    steps: tuple[ReactTrajectoryStep, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.initial_observation, str):
            raise TypeError("ReAct initial observation must be text")
        if not isinstance(self.steps, tuple) or any(
            not isinstance(step, ReactTrajectoryStep) for step in self.steps
        ):
            raise TypeError("ReAct transcript steps must be ReactTrajectoryStep values")

    def render(self, base_prompt: str) -> str:
        if not isinstance(base_prompt, str) or not base_prompt:
            raise ValueError("ReAct base prompt is required")
        prompt = f"{base_prompt}{self.initial_observation}\n>"
        for step in self.steps:
            prompt += f" {step.action}\n{step.observation}\n>"
        return prompt


def render_react_alfworld_transcript(
    *,
    base_prompt: str,
    initial_observation: str,
    exchanges: tuple[tuple[str, str], ...] = (),
) -> str:
    steps = tuple(ReactTrajectoryStep(action, observation) for action, observation in exchanges)
    return ReactAlfworldTranscript(initial_observation, steps).render(base_prompt)


__all__ = [
    "ReactAlfworldTranscript",
    "ReactTrajectoryStep",
    "render_react_alfworld_transcript",
]
