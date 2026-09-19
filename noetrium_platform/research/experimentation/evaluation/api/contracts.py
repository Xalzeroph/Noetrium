from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


def _require_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _require_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if any(type(item) is not str for item in value):
        raise TypeError(f"{field} must contain strings")
    if any(not item.strip() for item in value):
        raise ValueError(f"{field} must contain non-empty strings")
    return value


def _require_metrics(value: object) -> tuple[tuple[str, float], ...]:
    if type(value) is not tuple:
        raise TypeError("branch receipt metrics must be a tuple")
    names: set[str] = set()
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("branch receipt metric rows must be two-item tuples")
        name, metric = row
        _require_string(name, "branch receipt metric name")
        if name in names:
            raise ValueError(f"branch receipt contains duplicate metric: {name}")
        if type(metric) not in {int, float}:
            raise TypeError(f"branch receipt metric must be numeric: {name}")
        try:
            finite = math.isfinite(metric)
        except OverflowError as exc:
            raise ValueError(f"branch receipt metric is not finite: {name}") from exc
        if not finite:
            raise ValueError(f"branch receipt metric is not finite: {name}")
        names.add(name)
    return value


def _metric_names(receipt: "BranchReceipt") -> frozenset[str]:
    return frozenset(name for name, _ in receipt.metrics)


@dataclass(frozen=True, slots=True)
class BranchReceipt:
    branch_id: str
    source_checkpoint_id: str
    workload_id: str
    environment_generation: str
    task_manifest_digest: str
    branch_writes: tuple[str, ...]
    lifetime_writes: tuple[str, ...]
    private_to_method_flows: tuple[str, ...]
    metrics: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        for field, value in (
            ("branch_id", self.branch_id),
            ("source_checkpoint_id", self.source_checkpoint_id),
            ("workload_id", self.workload_id),
            ("environment_generation", self.environment_generation),
            ("task_manifest_digest", self.task_manifest_digest),
        ):
            _require_string(value, f"branch receipt {field}")
        _require_string_tuple(self.branch_writes, "branch receipt branch_writes")
        _require_string_tuple(self.lifetime_writes, "branch receipt lifetime_writes")
        _require_string_tuple(self.private_to_method_flows, "branch receipt private_to_method_flows")
        _require_metrics(self.metrics)


@dataclass(frozen=True, slots=True)
class ComparabilityProof:
    valid: bool
    pair_id: str
    violations: tuple[str, ...]
    source_checkpoint_id: str
    workload_id: str
    environment_generation: str
    task_manifest_digest: str

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise TypeError("comparability proof valid must be a bool")
        for field, value in (
            ("pair_id", self.pair_id),
            ("source_checkpoint_id", self.source_checkpoint_id),
            ("workload_id", self.workload_id),
            ("environment_generation", self.environment_generation),
            ("task_manifest_digest", self.task_manifest_digest),
        ):
            _require_string(value, f"comparability proof {field}")
        violations = _require_string_tuple(self.violations, "comparability proof violations")
        if len(violations) != len(set(violations)):
            raise ValueError("comparability proof violations must be unique")
        if self.valid != (not violations):
            raise ValueError("comparability proof validity must match violation state")


@dataclass(frozen=True, slots=True)
class PairedEvaluationResult:
    control: BranchReceipt
    candidate: BranchReceipt
    proof: ComparabilityProof

    def __post_init__(self) -> None:
        if type(self.control) is not BranchReceipt or type(self.candidate) is not BranchReceipt:
            raise TypeError("paired evaluation receipts must be BranchReceipt values")
        if type(self.proof) is not ComparabilityProof:
            raise TypeError("paired evaluation proof must be a ComparabilityProof")
        if self.proof.source_checkpoint_id != self.control.source_checkpoint_id:
            raise ValueError("paired evaluation proof source checkpoint must match control")
        if self.proof.workload_id != self.control.workload_id:
            raise ValueError("paired evaluation proof workload must match control")
        if self.proof.environment_generation != self.control.environment_generation:
            raise ValueError("paired evaluation proof environment generation must match control")
        if self.proof.task_manifest_digest != self.control.task_manifest_digest:
            raise ValueError("paired evaluation proof task manifest must match control")


def _identity_violations(control: BranchReceipt, candidate: BranchReceipt) -> tuple[str, ...]:
    violations: list[str] = []
    if control.branch_id == candidate.branch_id:
        violations.append("control and candidate branch ids must differ")
    fields = (
        ("source_checkpoint_id", control.source_checkpoint_id, candidate.source_checkpoint_id),
        ("workload_id", control.workload_id, candidate.workload_id),
        ("environment_generation", control.environment_generation, candidate.environment_generation),
        ("task_manifest_digest", control.task_manifest_digest, candidate.task_manifest_digest),
    )
    violations.extend(f"{name} mismatch" for name, left, right in fields if left != right)
    if _metric_names(control) != _metric_names(candidate):
        violations.append("metric schema mismatch")
    return tuple(violations)


def _effect_violations(control: BranchReceipt, candidate: BranchReceipt) -> tuple[str, ...]:
    violations: list[str] = []
    if control.lifetime_writes:
        violations.append("control branch wrote lifetime state")
    if candidate.lifetime_writes:
        violations.append("candidate branch wrote lifetime state")
    if any(item.startswith("candidate->control") for item in candidate.branch_writes):
        violations.append("candidate wrote control branch state")
    if control.private_to_method_flows or candidate.private_to_method_flows:
        violations.append("private evaluation/control evidence flowed into method state")
    return tuple(violations)


def _comparability_violations(control: BranchReceipt, candidate: BranchReceipt) -> tuple[str, ...]:
    return _identity_violations(control, candidate) + _effect_violations(control, candidate)


def build_comparability_proof(control: BranchReceipt, candidate: BranchReceipt) -> ComparabilityProof:
    """Build a fail-closed proof that two branch receipts are scientifically comparable."""

    if type(control) is not BranchReceipt or type(candidate) is not BranchReceipt:
        raise TypeError("comparability requires BranchReceipt values")
    violations = _comparability_violations(control, candidate)
    raw = json.dumps(
        {
            "c": control.branch_id,
            "x": candidate.branch_id,
            "cp": control.source_checkpoint_id,
            "w": control.workload_id,
            "e": control.environment_generation,
            "t": control.task_manifest_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    pair_id = "pair_" + hashlib.sha256(raw).hexdigest()[:20]
    return ComparabilityProof(
        not violations,
        pair_id,
        tuple(violations),
        control.source_checkpoint_id,
        control.workload_id,
        control.environment_generation,
        control.task_manifest_digest,
    )


__all__ = ["BranchReceipt", "ComparabilityProof", "PairedEvaluationResult", "build_comparability_proof"]
