from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Iterable

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmFinding,
    AlgorithmLanguage,
    AlgorithmMetrics,
    AlgorithmPriority,
    AlgorithmSnapshot,
    AlgorithmSymbol,
    FileAnalysis,
    LanguageCoverage,
    SourceDocument,
)
from noetrium_platform.foundation.governance.api import RepositorySourcePort
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes


_LANGUAGE_BY_SUFFIX = {
    ".py": AlgorithmLanguage.PYTHON,
    ".js": AlgorithmLanguage.JAVASCRIPT,
    ".mjs": AlgorithmLanguage.JAVASCRIPT,
    ".cjs": AlgorithmLanguage.JAVASCRIPT,
    ".sh": AlgorithmLanguage.SHELL,
    ".bash": AlgorithmLanguage.SHELL,
}
_ALGORITHM_EXCLUDED_PATH_PARTS = frozenset({".mypy_cache", ".ruff_cache"})


class RepositorySourceInventory:
    """Algorithm source adapter over the shared governance repository inventory."""

    def __init__(self, source_inventory: RepositorySourcePort) -> None:
        self._source_inventory = source_inventory

    def documents(self) -> Iterable[SourceDocument]:
        for source in self._source_inventory.documents(suffixes=_LANGUAGE_BY_SUFFIX):
            if any(part in _ALGORITHM_EXCLUDED_PATH_PARTS for part in PurePosixPath(source.relative_path).parts):
                continue
            yield SourceDocument(
                relative_path=source.relative_path,
                language=_LANGUAGE_BY_SUFFIX[source.suffix],
                sha256=source.sha256,
                text=source.text,
            )


def _finding_from_dict(data: dict) -> AlgorithmFinding:
    return AlgorithmFinding(AlgorithmPriority(data["priority"]), str(data["code"]), str(data["detail"]), int(data["score"]))


def _symbol_from_dict(data: dict) -> AlgorithmSymbol:
    metrics = AlgorithmMetrics(**data["metrics"])
    findings = tuple(_finding_from_dict(row) for row in data.get("findings", ()))
    return AlgorithmSymbol(
        symbol_id=str(data["symbol_id"]),
        relative_path=str(data["relative_path"]),
        language=AlgorithmLanguage(data["language"]),
        qualified_name=str(data["qualified_name"]),
        line_start=int(data["line_start"]),
        line_end=int(data["line_end"]),
        metrics=metrics,
        findings=findings,
    )


def _snapshot_from_dict(data: dict) -> AlgorithmSnapshot:
    schema = str(data["schema_version"])
    common_fields = {
        "schema_version", "analyzer_revision", "source_digest", "symbols", "coverage", "generated_unix_ns",
    }
    if schema == "algorithm-snapshot.v3":
        expected = common_fields | {"source_authority", "source_revision", "analyzer_implementation_digest"}
        if set(data) != expected:
            raise ValueError("algorithm-snapshot.v3 has unexpected fields")
        source_authority = str(data["source_authority"])
        source_revision = data["source_revision"]
        if source_revision is not None:
            source_revision = str(source_revision)
        implementation_digest = str(data["analyzer_implementation_digest"])
    elif schema == "algorithm-snapshot.v2":
        if set(data) != common_fields:
            raise ValueError("legacy algorithm-snapshot.v2 has unexpected fields")
        source_authority = "legacy"
        source_revision = None
        implementation_digest = ""
    else:
        raise ValueError(f"unsupported algorithm snapshot schema: {schema}")
    return AlgorithmSnapshot(
        schema_version=schema,
        analyzer_revision=str(data["analyzer_revision"]),
        source_digest=str(data["source_digest"]),
        symbols=tuple(_symbol_from_dict(row) for row in data["symbols"]),
        coverage=tuple(
            LanguageCoverage(
                language=AlgorithmLanguage(row["language"]),
                file_count=int(row["file_count"]),
                symbol_count=int(row["symbol_count"]),
                parse_errors=int(row["parse_errors"]),
            )
            for row in data["coverage"]
        ),
        generated_unix_ns=int(data["generated_unix_ns"]),
        source_authority=source_authority,
        source_revision=source_revision,
        analyzer_implementation_digest=implementation_digest,
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


class FilesystemFileAnalysisCache:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(relative_path: str, source_sha256: str, analyzer_revision: str) -> str:
        return hashlib.sha256(f"{relative_path}\0{source_sha256}\0{analyzer_revision}".encode("utf-8")).hexdigest()

    def get(self, relative_path: str, source_sha256: str, analyzer_revision: str) -> FileAnalysis | None:
        path = self._root / f"{self._key(relative_path, source_sha256, analyzer_revision)}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return FileAnalysis(
                relative_path=str(data["relative_path"]),
                language=AlgorithmLanguage(data["language"]),
                source_sha256=str(data["source_sha256"]),
                analyzer_revision=str(data["analyzer_revision"]),
                symbols=tuple(_symbol_from_dict(row) for row in data["symbols"]),
                parse_errors=int(data.get("parse_errors", 0)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, analysis: FileAnalysis) -> None:
        path = self._root / f"{self._key(analysis.relative_path, analysis.source_sha256, analysis.analyzer_revision)}.json"
        atomic_replace_bytes(path, _json_bytes(analysis))


class FilesystemAlgorithmSnapshotStore:
    def __init__(self, root: Path, *, baseline_path: Path | None = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._baseline = Path(baseline_path) if baseline_path is not None else self._root / "ALGORITHM_BASELINE.json"
        self._current = self._root / "ALGORITHM_CURRENT.json"
        self._history = self._root / "history"

    def _load(self, path: Path) -> AlgorithmSnapshot | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid algorithm snapshot: {path}") from exc
        return _snapshot_from_dict(data)

    def load_baseline(self) -> AlgorithmSnapshot | None:
        return self._load(self._baseline)

    def publish_baseline(self, snapshot: AlgorithmSnapshot) -> None:
        atomic_replace_bytes(self._baseline, _json_bytes(snapshot))

    def publish_current(self, snapshot: AlgorithmSnapshot) -> None:
        atomic_replace_bytes(self._current, _json_bytes(snapshot))

    def append_history(self, snapshot: AlgorithmSnapshot) -> None:
        self._history.mkdir(parents=True, exist_ok=True)
        existing = sorted(self._history.glob("*.json"))
        if existing:
            previous = self._load(existing[-1])
            if previous is not None and previous.source_digest == snapshot.source_digest and previous.analyzer_revision == snapshot.analyzer_revision:
                return
        name = f"{snapshot.generated_unix_ns}-{snapshot.source_digest[:12]}.json"
        atomic_replace_bytes(self._history / name, _json_bytes(snapshot))


__all__ = [
    "FilesystemAlgorithmSnapshotStore",
    "FilesystemFileAnalysisCache",
    "RepositorySourceInventory",
]
