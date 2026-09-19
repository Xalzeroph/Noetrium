from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from enum import StrEnum
from typing import Mapping


class AlgorithmLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    SHELL = "shell"


class AlgorithmPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    relative_path: str
    language: AlgorithmLanguage
    sha256: str
    text: str


@dataclass(frozen=True, slots=True)
class AlgorithmMetrics:
    source_lines: int = 0
    branches: int = 0
    loops: int = 0
    max_loop_depth: int = 0
    comprehensions: int = 0
    sort_calls: int = 0
    database_calls_in_loops: int = 0
    io_calls_in_loops: int = 0
    serialization_calls_in_loops: int = 0
    lock_calls_in_loops: int = 0
    subprocess_calls_in_loops: int = 0
    recursive_calls: int = 0
    call_count: int = 0
    cyclomatic_estimate: int = 1
    risk_score: int = 0
    estimated_complexity: str = "O(1)"


@dataclass(frozen=True, slots=True)
class AlgorithmFinding:
    priority: AlgorithmPriority
    code: str
    detail: str
    score: int


@dataclass(frozen=True, slots=True)
class AlgorithmSymbol:
    symbol_id: str
    relative_path: str
    language: AlgorithmLanguage
    qualified_name: str
    line_start: int
    line_end: int
    metrics: AlgorithmMetrics
    findings: tuple[AlgorithmFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class LanguageCoverage:
    language: AlgorithmLanguage
    file_count: int
    symbol_count: int
    parse_errors: int


@dataclass(frozen=True, slots=True)
class AlgorithmSnapshot:
    schema_version: str
    analyzer_revision: str
    source_digest: str
    symbols: tuple[AlgorithmSymbol, ...]
    coverage: tuple[LanguageCoverage, ...]
    generated_unix_ns: int
    source_authority: str = "filesystem"
    source_revision: str | None = None
    analyzer_implementation_digest: str = ""

    @property
    def candidate_count(self) -> int:
        return sum(1 for symbol in self.symbols if symbol.findings)


@dataclass(frozen=True, slots=True)
class AlgorithmBaselineApproval:
    approval_id: str
    source_git_sha: str
    source_digest: str
    analyzer_revision: str
    analyzer_implementation_digest: str
    snapshot_digest: str
    decision: str
    authority: str
    scope: str
    review_state: str
    review_evidence_refs: tuple[str, ...]
    issued_at: str
    note: str
    approval_record_sha256: str

    @property
    def approved(self) -> bool:
        return self.decision == "approved"


@dataclass(frozen=True, slots=True)
class AlgorithmComplexityMigrationApproval:
    migration_id: str
    symbol_id: str
    source_git_sha: str
    source_digest: str
    analyzer_revision: str
    analyzer_implementation_digest: str
    old_complexity: str
    new_complexity: str
    decision: str
    authority: str
    scope: str
    review_state: str
    review_evidence_refs: tuple[str, ...]
    issued_at: str
    rationale: str
    approval_record_sha256: str

    @property
    def approved(self) -> bool:
        return self.decision == "approved"


@dataclass(frozen=True, slots=True)
class AlgorithmGovernanceApprovalSet:
    schema_version: str
    authority: str
    baseline_approvals: tuple[AlgorithmBaselineApproval, ...]
    complexity_migrations: tuple[AlgorithmComplexityMigrationApproval, ...]
    default_decision: str
    rule: str
    _baseline_index: Mapping[tuple[str, str, str, str, str], AlgorithmBaselineApproval] = field(
        init=False, repr=False, compare=False
    )
    _complexity_index: Mapping[
        tuple[str, str, str, str, str, str, str], AlgorithmComplexityMigrationApproval
    ] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        approved_baselines = tuple(row for row in self.baseline_approvals if row.approved)
        baseline_index = {
            (
                row.source_git_sha, row.source_digest, row.analyzer_revision,
                row.analyzer_implementation_digest, row.snapshot_digest,
            ): row
            for row in approved_baselines
        }
        approved_migrations = tuple(row for row in self.complexity_migrations if row.approved)
        complexity_index = {
            (
                row.symbol_id, row.source_git_sha, row.source_digest, row.analyzer_revision,
                row.analyzer_implementation_digest, row.old_complexity, row.new_complexity,
            ): row
            for row in approved_migrations
        }
        if len(baseline_index) != len(approved_baselines):
            raise ValueError("approved algorithm baseline identities must be unique")
        if len(complexity_index) != len(approved_migrations):
            raise ValueError("approved algorithm complexity migration identities must be unique")
        object.__setattr__(self, "_baseline_index", MappingProxyType(baseline_index))
        object.__setattr__(self, "_complexity_index", MappingProxyType(complexity_index))

    def baseline_approval_for(
        self, *, source_git_sha: str, source_digest: str, analyzer_revision: str,
        analyzer_implementation_digest: str, snapshot_digest: str,
    ) -> AlgorithmBaselineApproval | None:
        return self._baseline_index.get((
            source_git_sha, source_digest, analyzer_revision,
            analyzer_implementation_digest, snapshot_digest,
        ))

    def complexity_migration_for(
        self, *, symbol_id: str, source_git_sha: str, source_digest: str,
        analyzer_revision: str, analyzer_implementation_digest: str,
        old_complexity: str, new_complexity: str,
    ) -> AlgorithmComplexityMigrationApproval | None:
        return self._complexity_index.get((
            symbol_id, source_git_sha, source_digest, analyzer_revision,
            analyzer_implementation_digest, old_complexity, new_complexity,
        ))


@dataclass(frozen=True, slots=True)
class SymbolDelta:
    symbol_id: str
    old_score: int | None
    new_score: int | None
    old_complexity: str | None
    new_complexity: str | None
    findings_added: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AlgorithmDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[SymbolDelta, ...]
    moved: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AlgorithmGateReport:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    diff: AlgorithmDiff


@dataclass(frozen=True, slots=True)
class FileAnalysis:
    relative_path: str
    language: AlgorithmLanguage
    source_sha256: str
    analyzer_revision: str
    symbols: tuple[AlgorithmSymbol, ...]
    parse_errors: int = 0


__all__ = [
    "AlgorithmBaselineApproval",
    "AlgorithmComplexityMigrationApproval",
    "AlgorithmDiff",
    "AlgorithmGovernanceApprovalSet",
    "AlgorithmFinding",
    "AlgorithmGateReport",
    "AlgorithmLanguage",
    "AlgorithmMetrics",
    "AlgorithmPriority",
    "AlgorithmSnapshot",
    "AlgorithmSymbol",
    "FileAnalysis",
    "LanguageCoverage",
    "SourceDocument",
    "SymbolDelta",
]
