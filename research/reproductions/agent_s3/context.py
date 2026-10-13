from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class AgentS3GeneratorTurn:
    user_text: str
    assistant_text: str
    screenshot_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_text, str) or not isinstance(self.assistant_text, str):
            raise TypeError("Agent S3 generator turn text must be strings")
        if self.screenshot_ref is not None and (
            not isinstance(self.screenshot_ref, str) or not self.screenshot_ref.strip()
        ):
            raise ValueError("Agent S3 screenshot_ref must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class AgentS3ReflectionTurn:
    text: str
    screenshot_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("Agent S3 reflection turn text must be a string")
        if self.screenshot_ref is not None and (
            not isinstance(self.screenshot_ref, str) or not self.screenshot_ref.strip()
        ):
            raise ValueError("Agent S3 screenshot_ref must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class AgentS3ContextView:
    generator_turns: tuple[AgentS3GeneratorTurn, ...]
    reflection_turns: tuple[AgentS3ReflectionTurn, ...]


def _retain_latest_images(turns: tuple[AgentS3GeneratorTurn, ...], limit: int) -> tuple[AgentS3GeneratorTurn, ...]:
    remaining = limit
    rows: list[AgentS3GeneratorTurn] = []
    for turn in reversed(turns):
        if turn.screenshot_ref is None:
            rows.append(turn)
        elif remaining > 0:
            rows.append(turn)
            remaining -= 1
        else:
            rows.append(replace(turn, screenshot_ref=None))
    rows.reverse()
    return tuple(rows)


def _retain_latest_reflection_images(
    turns: tuple[AgentS3ReflectionTurn, ...],
    limit: int,
) -> tuple[AgentS3ReflectionTurn, ...]:
    remaining = limit
    rows: list[AgentS3ReflectionTurn] = []
    for turn in reversed(turns):
        if turn.screenshot_ref is None:
            rows.append(turn)
        elif remaining > 0:
            rows.append(turn)
            remaining -= 1
        else:
            rows.append(replace(turn, screenshot_ref=None))
    rows.reverse()
    return tuple(rows)


def project_agent_s3_context(
    *,
    generator_turns: tuple[AgentS3GeneratorTurn, ...],
    reflection_turns: tuple[AgentS3ReflectionTurn, ...],
    engine_type: str,
    max_trajectory_length: int = 8,
) -> AgentS3ContextView:
    """Reproduce Agent S3's model-view truncation without mutating host history.

    Anthropic/OpenAI/Gemini keep all text and only remove older images. Other
    engines drop oldest complete generator/reflection turns beyond the bound.
    """

    if not isinstance(generator_turns, tuple) or any(
        not isinstance(turn, AgentS3GeneratorTurn) for turn in generator_turns
    ):
        raise TypeError("Agent S3 generator_turns must be a typed tuple")
    if not isinstance(reflection_turns, tuple) or any(
        not isinstance(turn, AgentS3ReflectionTurn) for turn in reflection_turns
    ):
        raise TypeError("Agent S3 reflection_turns must be a typed tuple")
    if not isinstance(engine_type, str) or not engine_type.strip():
        raise ValueError("Agent S3 engine_type must be non-empty")
    if type(max_trajectory_length) is not int or max_trajectory_length <= 0:
        raise ValueError("Agent S3 max_trajectory_length must be positive")

    if engine_type in ("anthropic", "openai", "gemini"):
        return AgentS3ContextView(
            generator_turns=_retain_latest_images(generator_turns, max_trajectory_length),
            reflection_turns=_retain_latest_reflection_images(
                reflection_turns,
                max_trajectory_length,
            ),
        )

    return AgentS3ContextView(
        generator_turns=generator_turns[-max_trajectory_length:],
        reflection_turns=reflection_turns[-max_trajectory_length:],
    )


__all__ = [
    "AgentS3ContextView",
    "AgentS3GeneratorTurn",
    "AgentS3ReflectionTurn",
    "project_agent_s3_context",
]
