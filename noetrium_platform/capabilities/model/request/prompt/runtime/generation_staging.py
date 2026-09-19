from __future__ import annotations

from pathlib import Path

from .atomic_publication import publish_atomic_directory, write_atomic_file
from .generation_codec import EncodedGeneration, decode_generation
from .generation_contracts import PromptGenerationManifest
from .generation_reader import PromptGenerationReader, validate_generation_id
from .publication_common import PromptPublicationError


class PromptGenerationStager:
    """Crash-resumable immutable generation staging/publication authority."""

    def __init__(self, generations: Path, reader: PromptGenerationReader) -> None:
        self.generations = generations
        self.reader = reader

    @staticmethod
    def _manifest(encoded: EncodedGeneration) -> PromptGenerationManifest:
        return PromptGenerationManifest(
            encoded.generation_id,
            encoded.bundle_digests,
            encoded.policy_digests,
            encoded.schema_digests,
            encoded.payload_sha256,
        )

    @staticmethod
    def _validate_encoded_file(path: Path, encoded: EncodedGeneration) -> None:
        if not path.is_file() or path.is_symlink():
            raise PromptPublicationError("staged prompt generation missing or unsafe")
        digest, _, _ = decode_generation(path.read_text(encoding="utf-8"), encoded.generation_id)
        if digest != encoded.payload_sha256:
            raise PromptPublicationError("staged prompt generation differs from retry payload")

    def publish(self, encoded: EncodedGeneration) -> PromptGenerationManifest:
        gid = validate_generation_id(encoded.generation_id)
        target = self.generations / gid
        tmp = self.generations / (gid + ".tmp")

        # A caller may crash after successful atomic rename but before receiving
        # the result. Exact retry is idempotent only if the immutable payload matches.
        if target.exists():
            manifest, _ = self.reader.load(gid)
            if manifest.payload_sha256 != encoded.payload_sha256:
                raise PromptPublicationError(f"generation already exists with different payload: {gid}")
            return manifest

        # A power cut may leave a complete fsynced staging directory. Never delete
        # it blindly: verify exact identity and finish the same atomic publication.
        if tmp.exists():
            self._validate_encoded_file(tmp / "generation.json", encoded)
            publish_atomic_directory(tmp, target, self.generations)
            return self._manifest(encoded)

        tmp.mkdir()
        write_atomic_file(tmp / "generation.json", encoded.envelope_bytes)
        publish_atomic_directory(tmp, target, self.generations)
        return self._manifest(encoded)
