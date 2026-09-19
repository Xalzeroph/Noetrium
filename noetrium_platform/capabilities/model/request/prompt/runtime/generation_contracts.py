from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptGenerationManifest:
    generation_id: str
    bundle_digests: tuple[tuple[str, str], ...]
    policy_digests: tuple[tuple[str, str], ...]
    schema_digests: tuple[tuple[str, str], ...]
    payload_sha256: str
