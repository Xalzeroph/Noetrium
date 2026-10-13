from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from urllib.parse import quote

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel import (
    ChecksummedDocumentError,
    decode_checksummed_document,
)
from noetrium_platform.infrastructure.resources.authority.api import (
    ResourceRealizationSpec,
)

from .contracts import (
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
)

WORKSPACE_METADATA_SCHEMA = "resource.workspace-allocation.v2"
WORKSPACE_METADATA_FIELDS = frozenset(
    {"workspace_id", "scope", "category", "owner", "note"}
)
WORKSPACE_PROVIDER_KIND = "workspace.directory"


def workspace_name(value: str, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"invalid workspace {label}")
    return value


def workspace_root_digest(root: Path) -> str:
    return canonical_digest(str(Path(root).absolute()))


def workspace_resource_key(
    root: Path,
    *,
    scope_kind: str,
    scope_id: str,
    category: str,
    workspace_id: str,
) -> str:
    values = tuple(
        quote(workspace_name(value, label), safe="")
        for value, label in (
            (scope_kind, "scope kind"),
            (scope_id, "scope id"),
            (category, "category"),
            (workspace_id, "workspace id"),
        )
    )
    return ":".join(("workspace", workspace_root_digest(root), *values))


def workspace_terminal_key(resource_key: str) -> str:
    if type(resource_key) is not str or not resource_key.startswith("workspace:"):
        raise ValueError("workspace terminal key requires workspace resource key")
    return "workspace-terminal:" + canonical_digest(resource_key)


def workspace_realization_spec(metadata_document: bytes) -> ResourceRealizationSpec:
    raw = bytes(metadata_document)
    try:
        decoded = decode_checksummed_document(
            raw,
            expected_schema=WORKSPACE_METADATA_SCHEMA,
        ).payload
    except (ChecksummedDocumentError, OSError) as exc:
        raise WorkspaceMetadataError(
            WorkspaceMetadataFailureCode.DOCUMENT_INTEGRITY
        ) from exc
    if set(decoded) != WORKSPACE_METADATA_FIELDS:
        raise RuntimeError("workspace metadata document payload shape drifted")
    return ResourceRealizationSpec(
        WORKSPACE_PROVIDER_KIND,
        {
            "metadata_document_b64": base64.b64encode(raw).decode("ascii"),
            "metadata_sha256": hashlib.sha256(raw).hexdigest(),
        },
    )


def workspace_metadata_document_from_spec(spec) -> bytes:
    try:
        raw = base64.b64decode(
            str(spec["metadata_document_b64"]).encode("ascii"),
            validate=True,
        )
        expected_sha = str(spec["metadata_sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("workspace realization spec is malformed") from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("workspace realization metadata digest drifted")
    # Validate the embedded document through the same canonical schema path.
    workspace_realization_spec(raw)
    return raw


__all__ = [
    "WORKSPACE_METADATA_FIELDS",
    "WORKSPACE_METADATA_SCHEMA",
    "WORKSPACE_PROVIDER_KIND",
    "workspace_metadata_document_from_spec",
    "workspace_name",
    "workspace_realization_spec",
    "workspace_resource_key",
    "workspace_root_digest",
    "workspace_terminal_key",
]
