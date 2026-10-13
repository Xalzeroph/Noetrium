from __future__ import annotations

from noetrium_platform.capabilities.model.request.prompt.api import (
    PromptSelectionIdentity,
    PromptSelectionPort,
)
from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRegistry


class RegistryPromptSelection(PromptSelectionPort):
    """Read-only adapter over the current Prompt Registry generation."""

    def __init__(self, registry: PromptRegistry) -> None:
        if not isinstance(registry, PromptRegistry):
            raise TypeError("prompt selection registry must be PromptRegistry")
        self._registry = registry

    def resolve_selection(self, prompt_id: str) -> PromptSelectionIdentity:
        resolution = self._registry.resolve(prompt_id)
        bundle = resolution.bundle
        if bundle.prompt_id != prompt_id:
            raise ValueError("prompt registry returned mismatched prompt identity")
        return PromptSelectionIdentity(
            generation_id=resolution.generation_id,
            prompt_id=bundle.prompt_id,
            prompt_digest=bundle.digest,
            role=bundle.role,
        )


__all__ = ["RegistryPromptSelection"]
