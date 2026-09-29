from __future__ import annotations

from .blocks import PromptBlockPolicy
from .generation_store import PromptGenerationManifest, PromptGenerationStore
from .promotion_store import PromptPromotionEvidence, PromptPromotionRecord, PromptPromotionStore
from .publication_common import PromptPublicationError
from .runtime_contracts import ActivePromptBundle, PromptResolution
from .schema import OutputSchemaRegistry
from .spec import PromptSpec


class PromptRegistry:
    """Single durable prompt publication and resolution authority."""

    def __init__(
        self,
        generation_store: PromptGenerationStore,
        promotion_store: PromptPromotionStore,
    ) -> None:
        self.generation_store = generation_store
        self.promotion_store = promotion_store

    def stage(
        self,
        generation_id: str,
        specs: tuple[PromptSpec, ...],
        policies: dict[str, PromptBlockPolicy],
        schemas: OutputSchemaRegistry,
    ) -> PromptGenerationManifest:
        return self.generation_store.stage(generation_id, specs, policies, schemas)

    def promote(self, evidence: PromptPromotionEvidence) -> PromptPromotionRecord:
        return self.promotion_store.promote(evidence)

    def load_active(self) -> tuple[PromptGenerationManifest, tuple[ActivePromptBundle, ...]]:
        return self.promotion_store.load_active()

    def resolve(self, prompt_id: str) -> PromptResolution:
        manifest, bundles = self.load_active()
        for bundle in bundles:
            if bundle.prompt_id == prompt_id:
                return PromptResolution(manifest.generation_id, bundle)
        raise KeyError(prompt_id)

    def get(self, prompt_id: str) -> ActivePromptBundle:
        return self.resolve(prompt_id).bundle

    @property
    def generation(self) -> str:
        manifest, _bundles = self.load_active()
        return manifest.generation_id


__all__ = [
    "PromptRegistry",
    "PromptGenerationManifest",
    "PromptPromotionEvidence",
    "PromptPromotionRecord",
    "PromptPublicationError",
]
