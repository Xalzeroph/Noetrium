from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from .atomic_publication import write_atomic_file
from .promotion_contracts import PromptPromotionRecord
from .publication_common import PromptPublicationError


class PromotionRecordStore:
    """Immutable durable authority for validated prompt promotion intents."""

    def __init__(self,root:Path)->None:
        self.root=root
        self.root.mkdir(parents=True,exist_ok=True)

    def path(self,generation_id:str)->Path:
        return self.root/(generation_id+".json")

    def exists(self,generation_id:str)->bool:
        return self.path(generation_id).exists()

    def write_new(self,record:PromptPromotionRecord)->None:
        path=self.path(record.generation_id)
        if path.exists():
            raise PromptPublicationError("generation was already promoted")
        raw=canonical_bytes(record, indent=2)
        write_atomic_file(path,raw)

    def load(self,generation_id:str)->PromptPromotionRecord:
        path=self.path(generation_id)
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            return PromptPromotionRecord(**data)
        except Exception as exc:
            raise PromptPublicationError(f"invalid promotion record: {path.name}") from exc
