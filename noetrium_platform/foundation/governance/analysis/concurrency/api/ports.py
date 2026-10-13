from __future__ import annotations

from typing import Iterable, Protocol

from .contracts import (
    ConcurrencyBaseline,
    ConcurrencyDocument,
    ConcurrencyFileAnalysis,
    ConcurrencyLanguage,
    ConcurrencySnapshot,
)


class ConcurrencySourceInventoryPort(Protocol):
    def documents(self) -> Iterable[ConcurrencyDocument]: ...


class ConcurrencyLanguageAnalyzerPort(Protocol):
    @property
    def language(self) -> ConcurrencyLanguage: ...
    @property
    def revision(self) -> str: ...
    def analyze(self, document: ConcurrencyDocument) -> ConcurrencyFileAnalysis: ...


class ConcurrencySnapshotStorePort(Protocol):
    def publish_current(self, snapshot: ConcurrencySnapshot) -> None: ...
    def append_history(self, snapshot: ConcurrencySnapshot) -> None: ...
    def load_baseline(self) -> ConcurrencyBaseline | None: ...
    def publish_baseline(self, baseline: ConcurrencyBaseline) -> None: ...
