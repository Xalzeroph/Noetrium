from __future__ import annotations

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmFinding,
    AlgorithmMetrics,
    AlgorithmPriority,
)


def estimated_complexity(*, loops: int, max_loop_depth: int, sort_calls: int, recursive_calls: int) -> str:
    if recursive_calls and max_loop_depth >= 1:
        return "recursive+iterative"
    if max_loop_depth >= 3:
        return "O(N^3+)"
    if max_loop_depth == 2:
        return "O(N^2)"
    if max_loop_depth == 1 and sort_calls:
        return "O(N log N)"
    if max_loop_depth == 1 or loops:
        return "O(N)"
    if sort_calls:
        return "O(N log N)"
    return "O(1)"


def score_metrics(metrics: AlgorithmMetrics, *, declared_complexity: str | None = None, rationale: str | None = None) -> tuple[int, tuple[AlgorithmFinding, ...]]:
    score = 0
    score += min(metrics.source_lines // 20, 12)
    score += min(max(0, metrics.cyclomatic_estimate - 5), 18)
    effective_loop_depth = metrics.max_loop_depth
    if declared_complexity == "O(1)":
        effective_loop_depth = 0
    elif declared_complexity in {"O(N)", "O(N log N)"}:
        effective_loop_depth = min(effective_loop_depth, 1)
    elif declared_complexity == "O(N^2)":
        effective_loop_depth = min(effective_loop_depth, 2)
    score += effective_loop_depth * 10
    score += min(metrics.loops, 8) * 2
    score += min(metrics.comprehensions, 8)
    score += min(metrics.sort_calls, 4) * 3
    score += metrics.database_calls_in_loops * 14
    score += metrics.io_calls_in_loops * 10
    score += metrics.serialization_calls_in_loops * 8
    score += metrics.lock_calls_in_loops * 12
    score += metrics.subprocess_calls_in_loops * 14
    score += metrics.recursive_calls * 8
    score = min(score, 100)

    findings: list[AlgorithmFinding] = []
    if declared_complexity is None:
        if metrics.max_loop_depth >= 3:
            findings.append(AlgorithmFinding(AlgorithmPriority.P1, "deep-nested-loop", "loop nesting depth is at least 3", score))
        elif metrics.max_loop_depth == 2:
            findings.append(AlgorithmFinding(AlgorithmPriority.P2, "nested-loop", "loop nesting depth is 2; verify bounded cardinalities or indexing", score))
    elif rationale:
        findings.append(AlgorithmFinding(AlgorithmPriority.P3, "complexity-contract", f"declared {declared_complexity}: {rationale}", score))
    if metrics.database_calls_in_loops:
        findings.append(AlgorithmFinding(AlgorithmPriority.P1, "database-in-loop", "database operation appears in a loop body; consider bulk query/write", score))
    if metrics.subprocess_calls_in_loops:
        findings.append(AlgorithmFinding(AlgorithmPriority.P1, "subprocess-in-loop", "external process invocation appears in a loop body", score))
    if metrics.io_calls_in_loops:
        findings.append(AlgorithmFinding(AlgorithmPriority.P2, "io-in-loop", "filesystem/network I/O appears in a loop body", score))
    if metrics.serialization_calls_in_loops:
        findings.append(AlgorithmFinding(AlgorithmPriority.P2, "serialization-in-loop", "serialization appears in a loop body", score))
    if metrics.lock_calls_in_loops:
        findings.append(AlgorithmFinding(AlgorithmPriority.P2, "lock-in-loop", "lock acquisition appears in a loop body", score))
    if metrics.recursive_calls and metrics.max_loop_depth:
        findings.append(AlgorithmFinding(AlgorithmPriority.P2, "recursion-plus-loop", "recursive and iterative amplification coexist", score))
    if metrics.source_lines >= 180 or metrics.cyclomatic_estimate >= 30:
        findings.append(AlgorithmFinding(AlgorithmPriority.P2, "large-control-surface", "large or branch-heavy algorithm should be decomposed into explicit policies/ports", score))
    if score >= 30 and not findings:
        findings.append(AlgorithmFinding(AlgorithmPriority.P3, "complexity-review", "static complexity score warrants targeted benchmark/review", score))
    return score, tuple(findings)


__all__ = ["estimated_complexity", "score_metrics"]
