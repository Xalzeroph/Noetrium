from __future__ import annotations

from collections import Counter
import hashlib
import time

from noetrium_platform.foundation.governance.concurrency.api import ConcurrencyCoverage, ConcurrencySnapshot
from noetrium_platform.foundation.governance.concurrency.api.ports import ConcurrencyLanguageAnalyzerPort, ConcurrencySourceInventoryPort


class ConcurrencyScanner:
    def __init__(
        self,
        inventory: ConcurrencySourceInventoryPort,
        analyzers: tuple[ConcurrencyLanguageAnalyzerPort, ...],
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

    def scan(self) -> ConcurrencySnapshot:
        hotspots=[]; files=Counter(); counts=Counter(); errors=Counter(); digest=hashlib.sha256(); revisions=[]
        for lang, analyzer in sorted(self._analyzers.items(), key=lambda item:item[0].value):
            revisions.append(f"{lang.value}:{analyzer.revision}")
        for doc in self._inventory.documents():
            analyzer=self._analyzers.get(doc.language)
            if analyzer is None: continue
            files[doc.language]+=1
            digest.update(doc.relative_path.encode()); digest.update(b"\0"); digest.update(doc.sha256.encode()); digest.update(b"\0")
            result=analyzer.analyze(doc)
            hotspots.extend(result.hotspots); counts[doc.language]+=len(result.hotspots); errors[doc.language]+=result.parse_errors
        coverage=tuple(ConcurrencyCoverage(lang,files[lang],counts[lang],errors[lang]) for lang in sorted(files,key=lambda x:x.value))
        return ConcurrencySnapshot(
            "concurrency-snapshot.v2", "|".join(revisions), digest.hexdigest(),
            tuple(sorted(hotspots,key=lambda x:x.hotspot_id)), coverage, time.time_ns(),
            source_authority=self._source_authority,
            source_revision=self._source_revision,
            analyzer_implementation_digest=self._analyzer_implementation_digest,
        )
