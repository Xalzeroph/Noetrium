from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import (
    ResearchDimensionKind,
    ResearchResultKind,
    ResearchResultPage,
    ResearchResultQuery,
    ResearchSourceSnapshot,
)


@runtime_checkable
class ResearchResultSourcePort(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def supported_kinds(self) -> frozenset[ResearchResultKind]: ...

    @property
    def supported_dimensions(self) -> frozenset[ResearchDimensionKind]: ...

    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot: ...


@runtime_checkable
class ResearchResultQueryPort(Protocol):
    def query(self, query: ResearchResultQuery = ResearchResultQuery()) -> ResearchResultPage: ...


__all__ = ["ResearchResultQueryPort", "ResearchResultSourcePort"]
