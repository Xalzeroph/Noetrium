from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactStoragePlacementVerifierPort,
    ArtifactStorageVerificationError,
    VerifiedArtifactStoragePlacement,
)


class FilesystemArtifactStoragePlacementVerifier(ArtifactStoragePlacementVerifierPort):
    """Verify immutable artifact bytes in the built-in filesystem storage provider."""

    provider_id = "artifact.filesystem"
    _BLOCK_SIZE = 1024 * 1024

    def verify(
        self,
        *,
        artifact_id: str,
        content_sha256: str,
        storage_provider_id: str,
        location: str,
    ) -> VerifiedArtifactStoragePlacement:
        if storage_provider_id != self.provider_id:
            raise ArtifactStorageVerificationError(
                "UNSUPPORTED_PROVIDER",
                f"filesystem verifier cannot verify provider {storage_provider_id!r}",
            )
        path = Path(location).expanduser()
        if not path.is_absolute():
            raise ArtifactStorageVerificationError(
                "NON_ABSOLUTE_LOCATION",
                f"filesystem artifact location must be absolute: {location!r}",
            )
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ArtifactStorageVerificationError(
                "PLACEMENT_NOT_FOUND",
                f"artifact storage placement does not exist: {path}",
            ) from exc
        if not resolved.is_file():
            raise ArtifactStorageVerificationError(
                "PLACEMENT_NOT_FILE",
                f"artifact storage placement is not a regular file: {resolved}",
            )

        digest = hashlib.sha256()
        size = 0
        try:
            with resolved.open("rb") as handle:
                for block in iter(lambda: handle.read(self._BLOCK_SIZE), b""):
                    digest.update(block)
                    size += len(block)
        except OSError as exc:
            raise ArtifactStorageVerificationError(
                "PLACEMENT_READ_FAILED",
                f"artifact storage placement cannot be read: {resolved}",
            ) from exc
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != content_sha256:
            raise ArtifactStorageVerificationError(
                "CONTENT_SHA256_MISMATCH",
                f"artifact storage content digest mismatch at {resolved}",
            )
        return VerifiedArtifactStoragePlacement(
            artifact_id=artifact_id,
            content_sha256=actual_sha256,
            storage_provider_id=self.provider_id,
            location=str(resolved),
            size_bytes=size,
        )


__all__ = ["FilesystemArtifactStoragePlacementVerifier"]
