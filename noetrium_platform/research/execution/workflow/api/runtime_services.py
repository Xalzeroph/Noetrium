from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import require_sha256
from .method_machine import MethodEvidencePort, MethodProgram, MethodRuntimeContext


@runtime_checkable
class MethodRuntimeBinderPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def bind(
        self,
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        *,
        state_root: str | Path | None = None,
        machine_id: str | None = None,
    ) -> MethodRuntimeContext: ...


@runtime_checkable
class MethodEvidenceFactoryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def create(self, root: str | Path) -> MethodEvidencePort: ...


def require_method_runtime_binder(value: object) -> MethodRuntimeBinderPort:
    if not isinstance(value, MethodRuntimeBinderPort):
        raise TypeError("method runtime binder must satisfy MethodRuntimeBinderPort")
    require_sha256(value.identity_digest, "method runtime binder identity_digest")
    return value


def require_method_evidence_factory(value: object) -> MethodEvidenceFactoryPort:
    if not isinstance(value, MethodEvidenceFactoryPort):
        raise TypeError("method evidence factory must satisfy MethodEvidenceFactoryPort")
    require_sha256(value.identity_digest, "method evidence factory identity_digest")
    return value


__all__ = [
    "MethodEvidenceFactoryPort",
    "MethodRuntimeBinderPort",
    "require_method_evidence_factory",
    "require_method_runtime_binder",
]
