from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable
from noetrium_platform.foundation.governance.performance.api import PerformanceBaseline, PerformanceDocument, PerformanceLanguage, PerformanceSnapshot
from noetrium_platform.foundation.governance.api import RepositorySourcePort
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

_LANG={'.py':PerformanceLanguage.PYTHON,'.js':PerformanceLanguage.JAVASCRIPT,'.mjs':PerformanceLanguage.JAVASCRIPT,'.cjs':PerformanceLanguage.JAVASCRIPT,'.sh':PerformanceLanguage.SHELL,'.bash':PerformanceLanguage.SHELL}
class RepositoryPerformanceSourceInventory:
    def __init__(self, source_inventory: RepositorySourcePort) -> None:
        self._source_inventory = source_inventory

    def documents(self) -> Iterable[PerformanceDocument]:
        for source in self._source_inventory.documents(suffixes=_LANG):
            yield PerformanceDocument(
                source.relative_path, _LANG[source.suffix], source.sha256, source.text
            )


class FilesystemPerformanceSnapshotStore:
    def __init__(self, root: Path, *, baseline_path: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._history = self._root / "history"
        self._baseline = Path(baseline_path)

    @staticmethod
    def _bytes(value: object) -> bytes:
        return json.dumps(asdict(value), sort_keys=True, separators=(",", ":")).encode() + b"\n"

    def publish_current(self, snapshot: PerformanceSnapshot) -> None:
        atomic_replace_bytes(self._root / "PERFORMANCE_CURRENT.json", self._bytes(snapshot))

    def append_history(self, snapshot: PerformanceSnapshot) -> None:
        self._history.mkdir(parents=True, exist_ok=True)
        current = sorted(self._history.glob("*.json"))
        if current:
            try:
                data = json.loads(current[-1].read_text())
                if data.get("source_digest") == snapshot.source_digest and data.get("analyzer_revision") == snapshot.analyzer_revision:
                    return
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass
        atomic_replace_bytes(
            self._history / f"{snapshot.generated_unix_ns}-{snapshot.source_digest[:12]}.json",
            self._bytes(snapshot),
        )

    def load_baseline(self) -> PerformanceBaseline | None:
        if not self._baseline.exists():
            return None
        data = json.loads(self._baseline.read_text(encoding="utf-8"))
        schema = str(data.get("schema_version", ""))
        if schema == "performance-baseline.v2":
            expected = {
                "schema_version", "source_authority", "source_revision", "source_digest",
                "analyzer_revision", "analyzer_implementation_digest", "observed_blocker_fingerprints", "accepted_blocker_fingerprints",
            }
            if set(data) != expected:
                raise ValueError("performance baseline v2 has unexpected fields")
            revision = data["source_revision"]
            if revision is not None and not isinstance(revision, str):
                raise ValueError("performance baseline source_revision must be string or null")
            return PerformanceBaseline(
                schema_version=schema, source_authority=str(data["source_authority"]),
                source_revision=revision, source_digest=str(data["source_digest"]),
                analyzer_revision=str(data["analyzer_revision"]),
                analyzer_implementation_digest=str(data["analyzer_implementation_digest"]),
                observed_blocker_fingerprints=tuple(str(x) for x in data["observed_blocker_fingerprints"]),
                accepted_blocker_fingerprints=tuple(str(x) for x in data["accepted_blocker_fingerprints"]),
            )
        return PerformanceBaseline(
            schema_version=schema, source_authority="legacy", source_revision=None, source_digest="",
            analyzer_revision=str(data.get("analyzer_revision", "")), analyzer_implementation_digest="",
            observed_blocker_fingerprints=(),
            accepted_blocker_fingerprints=tuple(str(x) for x in data.get("blocker_fingerprints", ())),
        )

    def publish_baseline(self, baseline: PerformanceBaseline) -> None:
        self._baseline.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(self._baseline, self._bytes(baseline))
