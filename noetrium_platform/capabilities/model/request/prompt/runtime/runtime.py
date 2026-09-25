from __future__ import annotations

from .prompt_bundle_compiler import PromptBundleCompiler
from .runtime_cell import ActivePromptGenerationCell
from .runtime_contracts import ActivePromptBundle, PromptResolution
from .spec import PromptSpec


class PromptRegistry:
    """Runtime façade with atomic generation+bundle resolution."""

    def __init__(self) -> None:
        self._compiler = PromptBundleCompiler()
        self._cell = ActivePromptGenerationCell()

    def publish(self, generation: str, specs: tuple[PromptSpec, ...]) -> None:
        bundles = self._compiler.compile(specs)
        self._cell.replace(generation, bundles)

    def resolve(self, prompt_id: str) -> PromptResolution:
        return self._cell.resolve(prompt_id)

    def get(self, prompt_id: str) -> ActivePromptBundle:
        return self._cell.get(prompt_id)

    @property
    def generation(self) -> str:
        return self._cell.generation_id


__all__ = ["ActivePromptBundle", "PromptResolution", "PromptRegistry"]
