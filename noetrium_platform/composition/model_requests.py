from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.capabilities.model.request.runtime import (
    SQLiteModelRequestLedger,
    ReconstructableModelRequestRecorder,
)


def build_model_request_recorder(root: Path) -> ReconstructableModelRequestRecorder:
    """Default durable model-request backend wiring.

    Composition owns storage layout. Prompt/model-request contracts know nothing
    about directories, file formats, or the concrete persistence backend.
    """
    root = Path(root)
    return ReconstructableModelRequestRecorder(
        DirectoryArtifactBlobStore(root / "content"),
        SQLiteModelRequestLedger(root / "requests.sqlite3"),
    )


__all__ = ["build_model_request_recorder"]
