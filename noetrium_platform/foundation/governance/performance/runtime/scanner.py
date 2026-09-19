from __future__ import annotations

from collections import Counter
import hashlib
import time

from noetrium_platform.foundation.governance.performance.api import PerformanceCoverage, PerformanceSnapshot
from noetrium_platform.foundation.governance.performance.api.ports import PerformanceLanguageAnalyzerPort, PerformanceSourceInventoryPort


class PerformanceScanner:
    def __init__(
        self,
        inventory: PerformanceSourceInventoryPort,
        analyzers: tuple[PerformanceLanguageAnalyzerPort, ...],
        *,
        source_authority: str = "filesystem",
        source_revision: str | None = None,
        analyzer_implementation_digest: str = "",
    ) -> None:
        self._inventory = inventory
        self._analyzers = {a.language: a for a in analyzers}
        self._source_authority = source_authority
        self._source_revision = source_revision
        self._analyzer_implementation_digest = analyzer_implementation_digest

    def scan(self) -> PerformanceSnapshot:
        hotspots=[]; files=Counter(); counts=Counter(); errors=Counter(); digest=hashlib.sha256()
        revisions=[]
        for lang,a in sorted(self._analyzers.items(), key=lambda x:x[0].value): revisions.append(f"{lang.value}:{a.revision}")
        for doc in self._inventory.documents():
            analyzer=self._analyzers.get(doc.language)
            if analyzer is None: continue
            files[doc.language]+=1; digest.update(doc.relative_path.encode()); digest.update(b"\0"); digest.update(doc.sha256.encode()); digest.update(b"\0")
            result=analyzer.analyze(doc); hotspots.extend(result.hotspots); counts[doc.language]+=len(result.hotspots); errors[doc.language]+=result.parse_errors
        coverage=tuple(PerformanceCoverage(lang,files[lang],counts[lang],errors[lang]) for lang in sorted(files,key=lambda x:x.value))
        return PerformanceSnapshot(
            "performance-snapshot.v2","|".join(revisions),digest.hexdigest(),
            tuple(sorted(hotspots,key=lambda x:x.hotspot_id)),coverage,time.time_ns(),
            source_authority=self._source_authority,
            source_revision=self._source_revision,
            analyzer_implementation_digest=self._analyzer_implementation_digest,
        )
