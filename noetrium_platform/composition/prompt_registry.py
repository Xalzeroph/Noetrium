from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.request.prompt.runtime.active_pointer import ActivePromptPointer
from noetrium_platform.capabilities.model.request.prompt.runtime.generation_store import PromptGenerationStore
from noetrium_platform.capabilities.model.request.prompt.runtime.promotion_record_store import PromotionRecordStore
from noetrium_platform.capabilities.model.request.prompt.runtime.promotion_store import PromptPromotionStore
from noetrium_platform.capabilities.model.request.prompt.runtime.publication import PromptRegistry


def build_prompt_registry(
    *,
    generations_root: Path,
    promotion_records_root: Path,
    active_pointer_path: Path,
    publication_lock_path: Path,
) -> PromptRegistry:
    generations = PromptGenerationStore(generations_root, lock_path=publication_lock_path)
    promotion = PromptPromotionStore(
        generation_store=generations,
        records=PromotionRecordStore(promotion_records_root),
        pointer=ActivePromptPointer(active_pointer_path),
        lock_path=publication_lock_path,
    )
    return PromptRegistry(generations, promotion)


__all__ = ["build_prompt_registry"]
