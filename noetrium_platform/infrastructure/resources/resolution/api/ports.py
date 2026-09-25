from __future__ import annotations

from typing import Protocol

from .contracts import ResourceResolutionRequest, ResolvedResourceBinding


class ResourceResolutionPort(Protocol):
    """Resolve named resources without exposing provider implementation."""

    def resolve(self, request: ResourceResolutionRequest) -> ResolvedResourceBinding: ...


__all__ = ["ResourceResolutionPort"]
