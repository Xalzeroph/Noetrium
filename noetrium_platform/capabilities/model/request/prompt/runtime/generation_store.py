from __future__ import annotations

from pathlib import Path

from .blocks import PromptBlockPolicy
from .generation_codec import encode_generation, policy_digest
from .generation_contracts import PromptGenerationManifest
from .generation_reader import PromptGenerationReader
from .generation_staging import PromptGenerationStager
from .publication_common import PromptPublicationLease
from .runtime import ActivePromptBundle
from .schema import OutputSchemaRegistry
from .spec import PromptSpec


class PromptGenerationStore:
    """Thin façade over encoding, crash-resumable staging, and immutable reading."""

    def __init__(self, generations_root: Path, *, lock_path: Path) -> None:
        self.generations = generations_root
        self.lock_path = lock_path
        self.generations.mkdir(parents=True, exist_ok=True)
        self.reader = PromptGenerationReader(self.generations)
        self.stager = PromptGenerationStager(self.generations, self.reader)

    _policy_digest = staticmethod(policy_digest)

    def stage(
        self,
        generation_id: str,
        specs: tuple[PromptSpec, ...],
        policies: dict[str, PromptBlockPolicy],
        schemas: OutputSchemaRegistry,
    ) -> PromptGenerationManifest:
        encoded = encode_generation(generation_id, specs, policies, schemas)
        with PromptPublicationLease(self.lock_path):
            return self.stager.publish(encoded)

    def load(self, generation_id: str) -> tuple[PromptGenerationManifest, tuple[ActivePromptBundle, ...]]:
        return self.reader.load(generation_id)


__all__ = ["PromptGenerationManifest", "PromptGenerationStore"]
