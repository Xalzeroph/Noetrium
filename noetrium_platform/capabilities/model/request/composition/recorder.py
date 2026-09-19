from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore

from ..runtime import (
    DirectoryModelRequestLedger,
    ReconstructableModelRequestRecorder,
)


def build_directory_model_request_recorder(root: Path) -> ReconstructableModelRequestRecorder:
    """Compose the durable request recorder behind the request-system API."""

    return ReconstructableModelRequestRecorder(
        DirectoryArtifactBlobStore(root / "blobs"),
        DirectoryModelRequestLedger(root / "requests"),
    )


__all__ = ["build_directory_model_request_recorder"]
