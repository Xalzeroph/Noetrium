from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture.document_integrity_invariants import (
    audit_document_integrity_invariants,
)


def test_platform_does_not_reencode_checksummed_document_failures_as_free_text() -> None:
    root = Path(__file__).resolve().parents[1]
    assert audit_document_integrity_invariants(root) == []
