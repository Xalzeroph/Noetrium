from __future__ import annotations

from .memory import ReflexionTaskState


def should_reflect(before: ReflexionTaskState, after: ReflexionTaskState) -> bool:
    """Return the original method's post-trial reflection eligibility."""

    if before.task_id != after.task_id:
        raise ValueError("Reflexion state transition changed task identity")
    return (
        before.active
        and after.active
        and after.completed_trials == before.completed_trials + 1
        and not after.solved
    )


from .fidelity import REFLEXION_ALFWORLD_FIDELITY


class ReflexionSemanticsError(ValueError):
    """The downstream reproduction no longer matches the Reflexion protocol."""


def accept_action_candidate(text: str) -> str | None:
    """Mirror the original minimum-length candidate admission without hiding drift."""

    if not isinstance(text, str):
        raise TypeError("Reflexion action candidate must be text")
    normalized = text.strip()
    if len(normalized) < REFLEXION_ALFWORLD_FIDELITY.action_minimum_characters:
        return None
    if "\n" in normalized or "\r" in normalized:
        raise ReflexionSemanticsError("Reflexion action candidate must contain exactly one line")
    return normalized


def render_task_prompt(base_prompt: str, initial_observation: str, state: ReflexionTaskState) -> str:
    if not isinstance(base_prompt, str) or not base_prompt:
        raise ValueError("Reflexion base prompt is required")
    if not isinstance(initial_observation, str):
        raise TypeError("Reflexion initial observation must be text")
    text = base_prompt
    visible = state.visible_reflections
    if visible:
        text += "\n\nYour memory for the task below:"
        for index, reflection in enumerate(visible):
            text += f"\nTrial {index}:\n{reflection}"
    return text + f"\nHere is the task:\n{initial_observation}"


def extract_failed_scenario(trial_log: str) -> str:
    if not isinstance(trial_log, str):
        raise TypeError("Reflexion trial log must be text")
    marker = "Here is the task:"
    if marker not in trial_log:
        raise ReflexionSemanticsError("Reflexion failed trial is missing task marker")
    scenario = trial_log.rsplit(marker, 1)[-1].strip()
    if not scenario:
        raise ReflexionSemanticsError("Reflexion failed trial scenario is empty")
    return scenario


def render_reflection_prompt(
    *,
    failed_trial_log: str,
    state: ReflexionTaskState,
    few_shot_examples: str,
) -> str:
    """Build the method-owned verbal reinforcement request.

    Noetrium owns model invocation and request recording. This function owns
    only the scientific prompt semantics that turn a failed trajectory into a
    concise corrective plan for the next trial.
    """

    if not state.should_reflect:
        raise ReflexionSemanticsError("Reflexion reflection is invalid for solved/skipped task")
    if not isinstance(few_shot_examples, str) or not few_shot_examples.strip():
        raise ValueError("Reflexion reflection examples are required")
    scenario = extract_failed_scenario(failed_trial_log)
    prompt = (
        "Review the failed task trajectory below and produce a concise corrective plan. "
        "Focus on the strategy error and environment-specific actions; do not summarize the world. "
        "Return the new plan after 'Plan'.\n\n"
        f"Examples:\n{few_shot_examples.strip()}\n\n{scenario}"
    )
    if state.visible_reflections:
        prompt += "\n\nPlans from past attempts:"
        for index, reflection in enumerate(state.visible_reflections):
            prompt += f"\nTrial #{index}: {reflection}"
    return prompt + "\n\nNew plan:"

__all__ = [
    "ReflexionSemanticsError",
    "accept_action_candidate",
    "extract_failed_scenario",
    "render_reflection_prompt",
    "render_task_prompt",
    "should_reflect",
]