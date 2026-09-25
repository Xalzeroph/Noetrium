from __future__ import annotations

from .blocks import PromptBlockPolicy
from .generation_store import PromptGenerationManifest, PromptGenerationStore
from .promotion_store import PromptPromotionEvidence, PromptPromotionRecord, PromptPromotionStore
from .publication_common import PromptPublicationError
from .runtime import ActivePromptBundle
from .schema import OutputSchemaRegistry
from .spec import PromptSpec


class DurablePromptRegistry:
    """Prompt publication façade over separately composed generation/promotion authorities."""

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

    def publish(self, *args, **kwargs):
        raise PromptPublicationError(
            "direct publish is forbidden; use stage() then promote() with qualification evidence"
        )

    def promote(self, evidence: PromptPromotionEvidence) -> PromptPromotionRecord:
        return self.promotion_store.promote(evidence)

    def load_active(self) -> tuple[PromptGenerationManifest, tuple[ActivePromptBundle, ...]]:
        return self.promotion_store.load_active()
