from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RoleCanaryResult:
    role: str
    total: int
    passed: int
    critical_total: int
    critical_passed: int
    contract_errors: int

    def __post_init__(self) -> None:
        for field in ("total", "passed", "critical_total", "critical_passed", "contract_errors"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"role canary {field} must be a non-negative integer")
        if self.passed > self.total or self.critical_passed > self.critical_total or self.critical_total > self.total:
            raise ValueError("role canary counts are inconsistent")

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class PerformanceSample:
    concurrency: int
    ttft_p50: float
    ttft_p99: float
    tpot_p50: float
    tpot_p99: float
    output_tokens_per_second: float
    error_rate: float

    def __post_init__(self) -> None:
        if type(self.concurrency) is not int or self.concurrency <= 0:
            raise ValueError("qualification performance concurrency must be positive")
        for field in ("ttft_p50", "ttft_p99", "tpot_p50", "tpot_p99", "output_tokens_per_second", "error_rate"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"qualification performance {field} must be finite and non-negative")
        if self.error_rate > 1:
            raise ValueError("qualification performance error_rate must be <= 1")


@dataclass(frozen=True, slots=True)
class PreemptiveReturnSample:
    """Measured protected-flow return while low-priority borrowers are active."""

    borrower_concurrency: int
    return_concurrency: int
    borrower_priority: int
    protected_priority: int
    return_ttft_p99: float
    return_tpot_p99: float
    borrower_active_during_return: bool

    def __post_init__(self) -> None:
        for field in ("borrower_concurrency", "return_concurrency"):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"preemptive return {field} must be a positive integer"
                )
        if type(self.borrower_priority) is not int or type(self.protected_priority) is not int:
            raise TypeError("preemptive return priorities must be integers")
        if self.protected_priority >= self.borrower_priority:
            raise ValueError(
                "protected model priority must outrank borrower priority"
            )
        for field in ("return_ttft_p99", "return_tpot_p99"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
            ):
                raise ValueError(
                    f"preemptive return {field} must be finite and positive"
                )
        if type(self.borrower_active_during_return) is not bool:
            raise TypeError(
                "preemptive return borrower_active_during_return must be bool"
            )


def measured_latency_isolation_concurrency(
    performance: tuple[PerformanceSample, ...],
    *,
    max_qualified_concurrency: int,
) -> int:
    """Largest measured concurrency with no p99 TTFT/TPOT regression vs solo."""

    if type(performance) is not tuple:
        raise TypeError("latency isolation performance evidence must be a tuple")
    if type(max_qualified_concurrency) is not int or max_qualified_concurrency <= 0:
        raise ValueError("max qualified concurrency must be positive")
    samples = tuple(
        sorted(
            (
                row
                for row in performance
                if row.concurrency <= max_qualified_concurrency
            ),
            key=lambda row: row.concurrency,
        )
    )
    if not samples:
        raise ValueError(
            "qualification evidence has no performance samples within "
            "the qualified concurrency ceiling"
        )
    solo = tuple(row for row in samples if row.concurrency == 1)
    if len(solo) != 1:
        raise ValueError(
            "latency isolation qualification requires exactly one solo "
            "concurrency sample"
        )
    baseline = solo[0]
    if baseline.ttft_p99 <= 0 or baseline.tpot_p99 <= 0:
        raise ValueError(
            "latency isolation solo sample requires positive TTFT-p99/TPOT-p99"
        )
    eligible = tuple(
        row.concurrency
        for row in samples
        if (
            row.ttft_p99 > 0
            and row.tpot_p99 > 0
            and float(row.ttft_p99) <= float(baseline.ttft_p99)
            and float(row.tpot_p99) <= float(baseline.tpot_p99)
        )
    )
    if not eligible:
        raise RuntimeError("solo qualification sample must isolate itself")
    return max(eligible)


@dataclass(frozen=True, slots=True)
class ResourceQualificationMeasurements:
    peak_gpu_memory_bytes_per_device: int
    peak_host_memory_bytes: int
    max_qualified_concurrency: int
    max_prefill_queued_tokens: int

    def __post_init__(self) -> None:
        for field in (
            "peak_gpu_memory_bytes_per_device",
            "peak_host_memory_bytes",
            "max_qualified_concurrency",
            "max_prefill_queued_tokens",
        ):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"qualification resource measurement {field} must be a positive integer"
                )


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    model_stack_digest: str
    canaries: tuple[RoleCanaryResult, ...]
    performance: tuple[PerformanceSample, ...]
    prefill_input_tokens_per_second: float
    preemptive_return: PreemptiveReturnSample | None
    exact_output_reproducibility_checked: bool
    long_context_checked: bool
    tool_call_checked: bool

    def all_critical_pass(self) -> bool:
        return all(c.critical_passed == c.critical_total for c in self.canaries)


@dataclass(frozen=True, slots=True)
class QualificationPolicy:
    minimum_role_pass_rate: float = 0.98
    require_zero_critical_failures: bool = True
    max_error_rate: float = 0.001
    require_exact_output_reproducibility: bool = False
    require_long_context_checked: bool = False
    require_tool_call_checked: bool = True

    def __post_init__(self) -> None:
        for field in ("minimum_role_pass_rate", "max_error_rate"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= value <= 1
            ):
                raise ValueError(f"qualification policy {field} must be finite and within [0, 1]")


@dataclass(frozen=True, slots=True)
class QualificationDecision:
    qualified: bool
    reasons: tuple[str, ...]


def evaluate_qualification(evidence: QualificationEvidence, policy: QualificationPolicy) -> QualificationDecision:
    reasons: list[str] = []
    for c in evidence.canaries:
        if c.pass_rate < policy.minimum_role_pass_rate:
            reasons.append(f"role {c.role} pass_rate {c.pass_rate:.4f} below {policy.minimum_role_pass_rate:.4f}")
        if policy.require_zero_critical_failures and c.critical_passed != c.critical_total:
            reasons.append(f"role {c.role} has critical failures")
    for p in evidence.performance:
        if p.error_rate > policy.max_error_rate:
            reasons.append(f"concurrency {p.concurrency} error_rate {p.error_rate:.6f} above {policy.max_error_rate:.6f}")
    if policy.require_exact_output_reproducibility and not evidence.exact_output_reproducibility_checked:
        reasons.append("exact-output reproducibility not checked")
    if policy.require_long_context_checked and not evidence.long_context_checked:
        reasons.append("long-context contract not checked")
    if policy.require_tool_call_checked and not evidence.tool_call_checked:
        reasons.append("tool-call contract not checked")
    return QualificationDecision(not reasons, tuple(reasons))
