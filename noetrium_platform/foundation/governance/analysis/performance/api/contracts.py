from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PerformanceLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    SHELL = "shell"


class PerformancePriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass(frozen=True, slots=True)
class PerformanceFinding:
    priority: PerformancePriority
    code: str
    detail: str
    score: int

    @property
    def fingerprint(self) -> str:
        return f"{self.code}:{self.detail}"


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    async_functions: int = 0
    await_calls: int = 0
    blocking_calls_in_async: int = 0
    sync_subprocess_calls_in_async: int = 0
    sleep_calls_in_async: int = 0
    database_calls: int = 0
    database_calls_in_loops: int = 0
    io_calls: int = 0
    io_calls_in_loops: int = 0
    whole_file_reads: int = 0
    whole_file_writes: int = 0
    serialization_calls: int = 0
    serialization_calls_in_loops: int = 0
    lock_calls: int = 0
    lock_calls_in_loops: int = 0
    thread_pool_constructors: int = 0
    process_pool_constructors: int = 0
    task_creations: int = 0
    gather_calls: int = 0
    unbounded_fanout_calls: int = 0
    unbounded_queue_constructors: int = 0
    list_materializations: int = 0
    deep_copy_calls: int = 0
    loop_allocations: int = 0
    max_loop_depth: int = 0
    risk_score: int = 0


@dataclass(frozen=True, slots=True)
class PerformanceHotspot:
    hotspot_id: str
    relative_path: str
    language: PerformanceLanguage
    qualified_name: str
    line_start: int
    line_end: int
    metrics: PerformanceMetrics
    findings: tuple[PerformanceFinding, ...]


@dataclass(frozen=True, slots=True)
class PerformanceCoverage:
    language: PerformanceLanguage
    file_count: int
    hotspot_count: int
    parse_errors: int


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    schema_version: str
    analyzer_revision: str
    source_digest: str
    hotspots: tuple[PerformanceHotspot, ...]
    coverage: tuple[PerformanceCoverage, ...]
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
            1 for row in self.hotspots for finding in row.findings
            if finding.priority in {PerformancePriority.P0, PerformancePriority.P1}
        )

    @property
    def blocker_fingerprints(self) -> tuple[str, ...]:
        return tuple(sorted(
            f"{row.relative_path}::{row.qualified_name}::{finding.fingerprint}"
            for row in self.hotspots
            for finding in row.findings
            if finding.priority in {PerformancePriority.P0, PerformancePriority.P1}
        ))


@dataclass(frozen=True, slots=True)
class PerformanceBaseline:
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
class PerformanceGateReport:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PerformanceDocument:
    relative_path: str
    language: PerformanceLanguage
    sha256: str
    text: str


@dataclass(frozen=True, slots=True)
class PerformanceFileAnalysis:
    relative_path: str
    language: PerformanceLanguage
    source_sha256: str
    analyzer_revision: str
    hotspots: tuple[PerformanceHotspot, ...]
    parse_errors: int = 0
