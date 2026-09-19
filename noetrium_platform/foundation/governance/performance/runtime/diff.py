from __future__ import annotations

from noetrium_platform.foundation.governance.performance.api import (
    PerformanceBaseline,
    PerformanceGateReport,
    PerformanceSnapshot,
)


def gate_against_baseline(
    baseline: PerformanceBaseline,
    current: PerformanceSnapshot,
) -> PerformanceGateReport:
    if baseline.analyzer_revision != current.analyzer_revision:
        return PerformanceGateReport(
            passed=False,
            blockers=(
                "performance analyzer revision changed; reviewed baseline refresh required",
            ),
            warnings=(),
        )
    accepted = set(baseline.accepted_blocker_fingerprints)
    observed = set(current.blocker_fingerprints)
    blockers = list(sorted(observed - accepted))
    parse_errors = sum(row.parse_errors for row in current.coverage)
    if parse_errors:
        blockers.append(f"performance analyzer parse errors: {parse_errors}")
    warnings = tuple(f"resolved-baseline-debt {item}" for item in sorted(accepted - observed))
    return PerformanceGateReport(not blockers, tuple(blockers), warnings)


__all__ = ["gate_against_baseline"]
