from __future__ import annotations

from .checksummed_document import (
    ChecksummedDocumentError,
    ChecksummedDocumentFailureCode,
)


class DocumentIntegrityError(RuntimeError):
    """Stable domain wrapper for a checksummed-document integrity failure.

    Domain codecs should expose a domain-level exception without copying parser,
    payload, path, or lower-layer free text.  The machine-readable document code
    remains available for recovery/diagnostics and is also projected through the
    generic failure-correlation protocol.
    """

    def __init__(
        self,
        message: str,
        *,
        document_failure_code: ChecksummedDocumentFailureCode | None = None,
    ) -> None:
        self.document_failure_code = document_failure_code
        super().__init__(message)

    @classmethod
    def from_checksummed_document(
        cls,
        exc: ChecksummedDocumentError,
        *,
        message: str,
    ) -> "DocumentIntegrityError":
        return cls(message, document_failure_code=exc.code)

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        if self.document_failure_code is None:
            return ()
        return (f"document-integrity:{self.document_failure_code.value}",)


__all__ = ["DocumentIntegrityError"]
