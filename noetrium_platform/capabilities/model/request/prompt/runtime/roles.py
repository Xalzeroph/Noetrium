from __future__ import annotations

from .spec import PromptSpec
from .role_specs import diagnostic_prompt_spec, meta_prompt_spec, planner_prompt_spec, semantic_prompt_spec


def default_prompt_specs(model_family: str = "qwen3.6") -> tuple[PromptSpec, ...]:
    """Frozen role bundle assembled from independently versioned role specifications."""
    return (
        planner_prompt_spec(model_family),
        semantic_prompt_spec(model_family),
        meta_prompt_spec(model_family),
        diagnostic_prompt_spec(model_family),
    )
