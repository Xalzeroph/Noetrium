from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .runtime_contracts import ActivePromptBundle, PromptResolution


@dataclass(frozen=True, slots=True)
class ActivePromptGeneration:
    generation_id: str
    bundles: tuple[ActivePromptBundle, ...]


class ActivePromptGenerationCell:
    """Single atomic authority for the in-memory active prompt generation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generation = ActivePromptGeneration("empty", ())
        self._index: dict[str, ActivePromptBundle] = {}

    def replace(self, generation_id: str, bundles: tuple[ActivePromptBundle, ...]) -> None:
        index = {bundle.prompt_id: bundle for bundle in bundles}
        if len(index) != len(bundles):
            raise ValueError("duplicate prompt id in active generation")
        snapshot = ActivePromptGeneration(generation_id, bundles)
        with self._lock:
            self._index = index
            self._generation = snapshot

    def resolve(self, prompt_id: str) -> PromptResolution:
        with self._lock:
            bundle = self._index[prompt_id]
            return PromptResolution(self._generation.generation_id, bundle)

    def get(self, prompt_id: str) -> ActivePromptBundle:
        return self.resolve(prompt_id).bundle

    @property
    def generation_id(self) -> str:
        with self._lock:
            return self._generation.generation_id

    def snapshot(self) -> ActivePromptGeneration:
        with self._lock:
            return self._generation
