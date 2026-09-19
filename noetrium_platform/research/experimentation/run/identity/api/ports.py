from __future__ import annotations

from typing import Protocol

from .contracts import RunIdentity


class RunIdentityProvider(Protocol):
    def allocate(self) -> RunIdentity: ...


__all__ = ["RunIdentityProvider"]
