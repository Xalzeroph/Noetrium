from __future__ import annotations

from typing import Iterable, Protocol

from .contracts import AlgorithmLanguage, AlgorithmSnapshot, FileAnalysis, SourceDocument


class SourceInventoryPort(Protocol):
    def documents(self) -> Iterable[SourceDocument]: ...


class LanguageAnalyzerPort(Protocol):
    @property
    def language(self) -> AlgorithmLanguage: ...
    @property
    def revision(self) -> str: ...
    def analyze(self, document: SourceDocument) -> FileAnalysis: ...


class FileAnalysisCachePort(Protocol):
    def get(self, relative_path: str, source_sha256: str, analyzer_revision: str) -> FileAnalysis | None: ...
    def put(self, analysis: FileAnalysis) -> None: ...


class AlgorithmSnapshotStorePort(Protocol):
    def load_baseline(self) -> AlgorithmSnapshot | None: ...
    def publish_baseline(self, snapshot: AlgorithmSnapshot) -> None: ...
    def publish_current(self, snapshot: AlgorithmSnapshot) -> None: ...
    def append_history(self, snapshot: AlgorithmSnapshot) -> None: ...


__all__ = [
    "AlgorithmSnapshotStorePort",
    "FileAnalysisCachePort",
    "LanguageAnalyzerPort",
    "SourceInventoryPort",
]
