"""Artifact content composition entrypoints."""

from .acquisition import ArtifactAcquisitionAssembly, compose_artifact_acquisition
from .identity import compose_artifact_content_identity_resolver
from .storage import (
    ArtifactStorageBindingAssembly,
    compose_filesystem_artifact_storage_bindings,
)

__all__ = [
    "ArtifactAcquisitionAssembly",
    "ArtifactStorageBindingAssembly",
    "compose_artifact_acquisition",
    "compose_artifact_content_identity_resolver",
    "compose_filesystem_artifact_storage_bindings",
]
