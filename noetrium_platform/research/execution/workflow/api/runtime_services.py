from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import require_sha256
from .method_machine import (
    MethodEvidencePort,
    NoetriumUnit,
    MethodRunResult,
    MethodRuntimeContext,
)





@runtime_checkable
class MethodEvidenceFactoryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def create(self, root: str | Path) -> MethodEvidencePort: ...




def require_method_evidence_factory(value: object) -> MethodEvidenceFactoryPort:
    if not isinstance(value, MethodEvidenceFactoryPort):
        raise TypeError("method evidence factory must satisfy MethodEvidenceFactoryPort")
    require_sha256(value.identity_digest, "method evidence factory identity_digest")
    return value


__all__ = [
    "MethodEvidenceFactoryPort",
    "require_method_evidence_factory",
]
