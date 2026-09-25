from __future__ import annotations

from typing import Protocol

from .contracts import CaptureManifest, CaptureSyncReceipt


class ProcessByteCapturePort(Protocol):
    """Backend-neutral byte capture surface used by crash evidence acquisition."""

    def sync(self) -> CaptureSyncReceipt: ...

    def seal(self) -> CaptureManifest: ...

    def tail(self, length: int | None = None) -> bytes: ...

    def manifest_reference(self) -> str: ...


__all__ = ["ProcessByteCapturePort"]
