from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.serving.api import (
    QualifiedModelClosurePublication,
    QualifiedModelClosurePublicationReceipt,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers.qualified_closure_publication import (
    publish_qualified_model_deployment_closure as _publish_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)


def publish_qualified_model_deployment_closure(
    path: str | Path,
    publication: QualifiedModelClosurePublication,
    *,
    replace_malformed_existing: bool = False,
) -> QualifiedModelClosurePublicationReceipt:
    """Publish one qualified deployment closure through the platform durable authorities."""

    return _publish_qualified_model_deployment_closure(
        path,
        publication,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        replace_malformed_existing=replace_malformed_existing,
    )


__all__ = ["publish_qualified_model_deployment_closure"]
