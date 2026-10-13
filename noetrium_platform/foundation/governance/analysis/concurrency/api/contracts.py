from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConcurrencyLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    SHELL = "shell"


class ConcurrencyPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass(frozen=True, slots=True)
class ConcurrencyFinding:
    priority: ConcurrencyPriority
    code: str
    detail: str
    line: int

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.line}:{self.detail}"


@dataclass(frozen=True, slots=True)
class ConcurrencyMetrics:
    async_functions: int = 0
    await_calls: int = 0
    thread_constructors: int = 0
    daemon_threads: int = 0
    thread_pool_constructors: int = 0
    process_pool_constructors: int = 0
    task_creations: int = 0
    subprocess_constructors: int = 0
    queue_constructors: int = 0
    unbounded_queues: int = 0
    lock_constructors: int = 0
    lock_scopes: int = 0
    blocking_calls_in_async: int = 0
    blocking_calls_under_lock: int = 0
    fanout_in_loops: int = 0
    timeoutless_waits: int = 0
    lifecycle_join_calls: int = 0


@dataclass(frozen=True, slots=True)
class ConcurrencyHotspot:
    hotspot_id: str
    relative_path: str
    language: ConcurrencyLanguage
    qualified_name: str
    line_start: int
    line_end: int
    metrics: ConcurrencyMetrics
    findings: tuple[ConcurrencyFinding, ...]


@dataclass(frozen=True, slots=True)
class ConcurrencyCoverage:
    language: ConcurrencyLanguage
    file_count: int
    hotspot_count: int
    parse_errors: int


@dataclass(frozen=True, slots=True)
class ConcurrencySnapshot:
    schema_version: str
    analyzer_revision: str
    source_digest: str
    hotspots: tuple[ConcurrencyHotspot, ...]
    coverage: tuple[ConcurrencyCoverage, ...]
    generated_unix_ns: int
    source_authority: str = "filesystem"
    source_revision: str | None = None
    analyzer_implementation_digest: str = ""

    @property
    def finding_count(self) -> int:
        return sum(len(row.findings) for row in self.hotspots)

    @property
    def blocker_count(self) -> int:
        return sum(
            finding.priority in {ConcurrencyPriority.P0, ConcurrencyPriority.P1}
            for row in self.hotspots
            for finding in row.findings
        )

    @property
    def blocker_fingerprints(self) -> tuple[str, ...]:
        return tuple(sorted(
            f"{row.relative_path}::{row.qualified_name}::{finding.fingerprint}"
            for row in self.hotspots
            for finding in row.findings
            if finding.priority in {ConcurrencyPriority.P0, ConcurrencyPriority.P1}
        ))


@dataclass(frozen=True, slots=True)
class ConcurrencyDocument:
    relative_path: str
    language: ConcurrencyLanguage
    sha256: str
    text: str


@dataclass(frozen=True, slots=True)
class ConcurrencyFileAnalysis:
    relative_path: str
    language: ConcurrencyLanguage
    source_sha256: str
    analyzer_revision: str
    hotspots: tuple[ConcurrencyHotspot, ...]
    parse_errors: int = 0


@dataclass(frozen=True, slots=True)
class ConcurrencyBaseline:
    schema_version: str
    source_authority: str
    source_revision: str | None
    source_digest: str
    analyzer_revision: str
    analyzer_implementation_digest: str
    observed_blocker_fingerprints: tuple[str, ...]
    accepted_blocker_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.schema_version.endswith(".v2"):
            return
        observed = self.observed_blocker_fingerprints
        accepted = self.accepted_blocker_fingerprints
        if observed != tuple(sorted(set(observed))):
            raise ValueError("observed blocker fingerprints must be sorted and unique")
        if accepted != tuple(sorted(set(accepted))):
            raise ValueError("accepted blocker fingerprints must be sorted and unique")
        if not set(accepted).issubset(observed):
            raise ValueError("accepted blocker fingerprints must be a subset of observed blocker fingerprints")


@dataclass(frozen=True, slots=True)
class ConcurrencyGateReport:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
