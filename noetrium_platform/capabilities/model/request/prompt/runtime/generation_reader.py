from __future__ import annotations

from pathlib import Path

from .generation_codec import decode_generation
from .generation_contracts import PromptGenerationManifest
from .publication_common import PromptPublicationError
from .runtime import ActivePromptBundle


def validate_generation_id(generation_id: str) -> str:
    if not generation_id or "/" in generation_id or "\\" in generation_id or generation_id in {".", ".."}:
        raise PromptPublicationError("invalid prompt generation id")
    return generation_id


class PromptGenerationReader:
    """Immutable generation read/verification authority."""

    def __init__(self, generations: Path) -> None:
        self.generations = generations

    def path(self, generation_id: str) -> Path:
        gid = validate_generation_id(generation_id)
        return self.generations / gid / "generation.json"

    def load(self, generation_id: str) -> tuple[PromptGenerationManifest, tuple[ActivePromptBundle, ...]]:
        gid = validate_generation_id(generation_id)
        path = self.path(gid)
        if not path.is_file() or path.is_symlink():
            raise PromptPublicationError("prompt generation missing or unsafe")
        digest, bundles, payload = decode_generation(path.read_text(encoding="utf-8"), gid)
        manifest = PromptGenerationManifest(
            gid,
            tuple(map(tuple, payload["bundle_digests"])),
            tuple(map(tuple, payload["policy_digests"])),
            tuple(map(tuple, payload["schema_digests"])),
            digest,
        )
        return manifest, bundles
