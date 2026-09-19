from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable

from noetrium_platform.foundation.governance.concurrency.api import (
    ConcurrencyBaseline, ConcurrencyDocument, ConcurrencyLanguage, ConcurrencySnapshot,
)
from noetrium_platform.foundation.governance.api import RepositorySourcePort
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

_LANG={'.py':ConcurrencyLanguage.PYTHON,'.js':ConcurrencyLanguage.JAVASCRIPT,'.mjs':ConcurrencyLanguage.JAVASCRIPT,'.cjs':ConcurrencyLanguage.JAVASCRIPT,'.sh':ConcurrencyLanguage.SHELL,'.bash':ConcurrencyLanguage.SHELL}


class RepositoryConcurrencySourceInventory:
    def __init__(self, source_inventory: RepositorySourcePort) -> None:
        self._source_inventory = source_inventory

    def documents(self) -> Iterable[ConcurrencyDocument]:
        for source in self._source_inventory.documents(suffixes=_LANG):
            yield ConcurrencyDocument(
                source.relative_path, _LANG[source.suffix], source.sha256, source.text
            )


class FilesystemConcurrencySnapshotStore:
    def __init__(self, state_root:Path, *, baseline_path:Path):
        self._root=Path(state_root); self._root.mkdir(parents=True,exist_ok=True); self._history=self._root/'history'; self._baseline=Path(baseline_path)
    @staticmethod
    def _bytes(value): return json.dumps(asdict(value),sort_keys=True,separators=(',',':')).encode()+b'\n'
    def publish_current(self,snapshot:ConcurrencySnapshot)->None: atomic_replace_bytes(self._root/'CONCURRENCY_CURRENT.json',self._bytes(snapshot))
    def append_history(self,snapshot:ConcurrencySnapshot)->None:
        self._history.mkdir(parents=True,exist_ok=True)
        latest=sorted(self._history.glob('*.json'))
        if latest:
            try:
                data=json.loads(latest[-1].read_text())
                if data.get('source_digest')==snapshot.source_digest and data.get('analyzer_revision')==snapshot.analyzer_revision:return
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass
        atomic_replace_bytes(self._history/f'{snapshot.generated_unix_ns}-{snapshot.source_digest[:12]}.json',self._bytes(snapshot))
    def load_baseline(self)->ConcurrencyBaseline|None:
        if not self._baseline.exists(): return None
        data=json.loads(self._baseline.read_text(encoding="utf-8"))
        schema=str(data.get('schema_version',''))
        if schema == "concurrency-baseline.v2":
            expected={
                "schema_version","source_authority","source_revision","source_digest",
                "analyzer_revision","analyzer_implementation_digest","observed_blocker_fingerprints","accepted_blocker_fingerprints",
            }
            if set(data) != expected:
                raise ValueError("concurrency baseline v2 has unexpected fields")
            revision=data["source_revision"]
            if revision is not None and not isinstance(revision,str):
                raise ValueError("concurrency baseline source_revision must be string or null")
            return ConcurrencyBaseline(
                schema_version=schema, source_authority=str(data["source_authority"]),
                source_revision=revision, source_digest=str(data["source_digest"]),
                analyzer_revision=str(data["analyzer_revision"]),
                analyzer_implementation_digest=str(data["analyzer_implementation_digest"]),
                observed_blocker_fingerprints=tuple(str(x) for x in data["observed_blocker_fingerprints"]),
                accepted_blocker_fingerprints=tuple(str(x) for x in data["accepted_blocker_fingerprints"]),
            )
        return ConcurrencyBaseline(
            schema_version=schema, source_authority="legacy", source_revision=None, source_digest="",
            analyzer_revision=str(data.get('analyzer_revision','')), analyzer_implementation_digest="",
            observed_blocker_fingerprints=(),
            accepted_blocker_fingerprints=tuple(str(x) for x in data.get('blocker_fingerprints',())),
        )
    def publish_baseline(self,baseline:ConcurrencyBaseline)->None:
        self._baseline.parent.mkdir(parents=True,exist_ok=True)
        atomic_replace_bytes(self._baseline,self._bytes(baseline))
