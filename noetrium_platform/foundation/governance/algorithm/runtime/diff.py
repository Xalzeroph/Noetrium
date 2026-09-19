from __future__ import annotations

from collections import defaultdict

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmComplexityMigrationApproval,
    AlgorithmGovernanceApprovalSet,
    AlgorithmDiff,
    AlgorithmGateReport,
    AlgorithmPriority,
    AlgorithmSnapshot,
    AlgorithmSymbol,
    SymbolDelta,
)

_COMPLEXITY_RANK = {"O(1)": 0, "O(N)": 1, "O(N log N)": 2, "O(N^2)": 3, "O(N^3+)": 4, "recursive+iterative": 5}


def _move_signature(symbol: AlgorithmSymbol) -> tuple[object, ...]:
    """Return a location-independent algorithmic signature for unique move matching.

    The signature intentionally excludes path, line number, source-line count and
    derived risk score.  It is used only if exactly one removed and one added symbol
    share the same signature, so ambiguous look-alikes remain ordinary add/remove
    events and cannot hide newly introduced debt.
    """

    metrics = symbol.metrics
    return (
        symbol.language,
        symbol.qualified_name,
        metrics.branches,
        metrics.loops,
        metrics.max_loop_depth,
        metrics.comprehensions,
        metrics.sort_calls,
        metrics.database_calls_in_loops,
        metrics.io_calls_in_loops,
        metrics.serialization_calls_in_loops,
        metrics.lock_calls_in_loops,
        metrics.subprocess_calls_in_loops,
        metrics.recursive_calls,
        metrics.cyclomatic_estimate,
        metrics.estimated_complexity,
        tuple((finding.priority, finding.code) for finding in symbol.findings),
    )


def _match_unique_moves(
    old_only: dict[str, AlgorithmSymbol],
    new_only: dict[str, AlgorithmSymbol],
) -> tuple[tuple[tuple[str, str], ...], set[str], set[str]]:
    old_by_signature: dict[tuple[object, ...], list[str]] = defaultdict(list)
    new_by_signature: dict[tuple[object, ...], list[str]] = defaultdict(list)
    for symbol_id, symbol in old_only.items():
        old_by_signature[_move_signature(symbol)].append(symbol_id)
    for symbol_id, symbol in new_only.items():
        new_by_signature[_move_signature(symbol)].append(symbol_id)

    moved: list[tuple[str, str]] = []
    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for signature in old_by_signature.keys() & new_by_signature.keys():
        old_ids = old_by_signature[signature]
        new_ids = new_by_signature[signature]
        if len(old_ids) == 1 and len(new_ids) == 1:
            old_id, new_id = old_ids[0], new_ids[0]
            moved.append((old_id, new_id))
            matched_old.add(old_id)
            matched_new.add(new_id)
    return tuple(sorted(moved)), matched_old, matched_new


def diff_snapshots(old: AlgorithmSnapshot, new: AlgorithmSnapshot) -> AlgorithmDiff:
    old_map = {row.symbol_id: row for row in old.symbols}
    new_map = {row.symbol_id: row for row in new.symbols}
    old_only = {key: old_map[key] for key in old_map.keys() - new_map.keys()}
    new_only = {key: new_map[key] for key in new_map.keys() - old_map.keys()}
    moved, matched_old, matched_new = _match_unique_moves(old_only, new_only)
    added = tuple(sorted(new_only.keys() - matched_new))
    removed = tuple(sorted(old_only.keys() - matched_old))
    changed: list[SymbolDelta] = []
    for symbol_id in sorted(old_map.keys() & new_map.keys()):
        before = old_map[symbol_id]
        after = new_map[symbol_id]
        before_codes = {f.code for f in before.findings}
        after_codes = {f.code for f in after.findings}
        if (
            before.metrics.risk_score != after.metrics.risk_score
            or before.metrics.estimated_complexity != after.metrics.estimated_complexity
            or before_codes != after_codes
        ):
            changed.append(SymbolDelta(
                symbol_id=symbol_id,
                old_score=before.metrics.risk_score,
                new_score=after.metrics.risk_score,
                old_complexity=before.metrics.estimated_complexity,
                new_complexity=after.metrics.estimated_complexity,
                findings_added=tuple(sorted(after_codes - before_codes)),
            ))
    return AlgorithmDiff(
        added=added,
        removed=removed,
        changed=tuple(changed),
        moved=moved,
    )


def _approved_complexity_migration(
    before: AlgorithmSymbol,
    after: AlgorithmSymbol,
    *,
    current: AlgorithmSnapshot,
    approval_set: AlgorithmGovernanceApprovalSet | None,
) -> AlgorithmComplexityMigrationApproval | None:
    if current.source_revision is None or approval_set is None:
        return None
    return approval_set.complexity_migration_for(
        symbol_id=after.symbol_id,
        source_git_sha=current.source_revision,
        source_digest=current.source_digest,
        analyzer_revision=current.analyzer_revision,
        analyzer_implementation_digest=current.analyzer_implementation_digest,
        old_complexity=before.metrics.estimated_complexity,
        new_complexity=after.metrics.estimated_complexity,
    )


def gate_against_baseline(
    old: AlgorithmSnapshot,
    new: AlgorithmSnapshot,
    *,
    approval_set: AlgorithmGovernanceApprovalSet | None = None,
) -> AlgorithmGateReport:
    diff = diff_snapshots(old, new)
    if old.analyzer_revision != new.analyzer_revision:
        return AlgorithmGateReport(
            passed=False,
            blockers=(
                "algorithm analyzer revision changed: "
                f"{old.analyzer_revision} -> {new.analyzer_revision}; "
                "reviewed baseline refresh required",
            ),
            warnings=(),
            diff=diff,
        )

    new_map = {row.symbol_id: row for row in new.symbols}
    old_map = {row.symbol_id: row for row in old.symbols}
    blockers: list[str] = []
    warnings: list[str] = []
    for old_id, new_id in diff.moved:
        warnings.append(f"algorithm symbol moved: {old_id} -> {new_id}")
    for symbol_id in diff.added:
        symbol = new_map[symbol_id]
        priorities = {finding.priority for finding in symbol.findings}
        if AlgorithmPriority.P0 in priorities or AlgorithmPriority.P1 in priorities:
            blockers.append(f"new high-priority algorithm debt: {symbol_id}")
        elif symbol.findings:
            warnings.append(f"new algorithm debt: {symbol_id}")
    for delta in diff.changed:
        before = old_map[delta.symbol_id]
        after = new_map[delta.symbol_id]
        before_rank = _COMPLEXITY_RANK.get(before.metrics.estimated_complexity, 99)
        after_rank = _COMPLEXITY_RANK.get(after.metrics.estimated_complexity, 99)
        if after_rank > before_rank:
            approval = _approved_complexity_migration(
                before, after, current=new, approval_set=approval_set
            )
            if approval is not None:
                warnings.append(
                    f"approved lower-bound complexity migration {approval.migration_id}: "
                    f"{delta.symbol_id} {before.metrics.estimated_complexity} -> {after.metrics.estimated_complexity}"
                )
            else:
                blockers.append(
                    f"complexity regression {delta.symbol_id}: "
                    f"{before.metrics.estimated_complexity} -> {after.metrics.estimated_complexity}"
                )
        elif after.metrics.risk_score >= before.metrics.risk_score + 15:
            blockers.append(
                f"risk-score regression {delta.symbol_id}: "
                f"{before.metrics.risk_score} -> {after.metrics.risk_score}"
            )
        elif after.metrics.risk_score > before.metrics.risk_score:
            warnings.append(
                f"risk-score increased {delta.symbol_id}: "
                f"{before.metrics.risk_score} -> {after.metrics.risk_score}"
            )
        for finding in after.findings:
            if finding.code in delta.findings_added and finding.priority in {AlgorithmPriority.P0, AlgorithmPriority.P1}:
                blockers.append(f"new {finding.priority} finding {finding.code}: {delta.symbol_id}")
    return AlgorithmGateReport(
        passed=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        diff=diff,
    )


__all__ = ["diff_snapshots", "gate_against_baseline"]
