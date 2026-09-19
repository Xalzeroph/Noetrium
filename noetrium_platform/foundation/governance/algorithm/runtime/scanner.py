from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import replace

from noetrium_platform.foundation.governance.algorithm.api import AlgorithmSnapshot, LanguageCoverage
from noetrium_platform.foundation.governance.algorithm.api.ports import FileAnalysisCachePort, LanguageAnalyzerPort, SourceInventoryPort


class AlgorithmScanner:
    def __init__(
        self,
        *,
        inventory: SourceInventoryPort,
        analyzers: tuple[LanguageAnalyzerPort, ...],
        cache: FileAnalysisCachePort | None = None,
        use_cache: bool = True,
        source_authority: str = "filesystem",
        source_revision: str | None = None,
        analyzer_implementation_digest: str = "",
    ) -> None:
        self._inventory = inventory
        self._analyzers = {analyzer.language: analyzer for analyzer in analyzers}
        self._cache = cache
        self._use_cache = use_cache
        self._source_authority = str(source_authority)
        self._source_revision = source_revision
        self._analyzer_implementation_digest = str(analyzer_implementation_digest)

    def scan(self) -> AlgorithmSnapshot:
        symbols = []
        file_counts: Counter = Counter()
        symbol_counts: Counter = Counter()
        error_counts: Counter = Counter()
        source_digest = hashlib.sha256()
        revisions = []
        for language, analyzer in sorted(self._analyzers.items(), key=lambda item: item[0].value):
            revisions.append(f"{language.value}:{analyzer.revision}")
        for document in self._inventory.documents():
            analyzer = self._analyzers.get(document.language)
            if analyzer is None:
                continue
            file_counts[document.language] += 1
            source_digest.update(document.relative_path.encode("utf-8"))
            source_digest.update(b"\0")
            source_digest.update(document.sha256.encode("ascii"))
            source_digest.update(b"\0")
            analysis = None
            cache_identity = analyzer.revision
            if self._analyzer_implementation_digest:
                cache_identity = f"{analyzer.revision}@{self._analyzer_implementation_digest}"
            if self._cache is not None and self._use_cache:
                analysis = self._cache.get(document.relative_path, document.sha256, cache_identity)
            if analysis is None:
                analysis = analyzer.analyze(document)
                if self._cache is not None:
                    cached = replace(analysis, analyzer_revision=cache_identity)
                    self._cache.put(cached)
            symbols.extend(analysis.symbols)
            symbol_counts[document.language] += len(analysis.symbols)
            error_counts[document.language] += analysis.parse_errors
        coverage = tuple(
            LanguageCoverage(language, file_counts[language], symbol_counts[language], error_counts[language])
            for language in sorted(file_counts, key=lambda item: item.value)
        )
        return AlgorithmSnapshot(
            schema_version="algorithm-snapshot.v3",
            analyzer_revision="|".join(revisions),
            source_digest=source_digest.hexdigest(),
            symbols=tuple(sorted(symbols, key=lambda row: row.symbol_id)),
            coverage=coverage,
            generated_unix_ns=time.time_ns(),
            source_authority=self._source_authority,
            source_revision=self._source_revision,
            analyzer_implementation_digest=self._analyzer_implementation_digest,
        )


__all__ = ["AlgorithmScanner"]
