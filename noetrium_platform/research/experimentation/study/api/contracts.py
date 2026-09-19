from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Self

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


def _require_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must be non-empty")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _require_nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _require_finite_number(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _require_string_tuple(
    value: object, field: str, *, non_empty: bool, unique: bool
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"{field} must contain non-empty strings")
    if non_empty and not value:
        raise ValueError(f"{field} must be non-empty")
    if unique and len(value) != len(set(value)):
        raise ValueError(f"{field} must be unique")
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    return require_sha256(value, field)


class VariantKind(StrEnum):
    CONTROL = "control"
    TREATMENT = "treatment"
    ABLATION = "ablation"
    EXTERNAL_BASELINE = "external_baseline"


@dataclass(frozen=True, slots=True)
class StudyVariantSpec:
    variant_id: str
    kind: VariantKind
    implementation_id: str
    configuration_digest: str
    budget_tier: str = "standard"
    ablates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty_string(self.variant_id, "study variant variant_id")
        if not isinstance(self.kind, VariantKind):
            raise TypeError("study variant kind must be VariantKind")
        _require_non_empty_string(self.implementation_id, "study variant implementation_id")
        _require_sha256(self.configuration_digest, "study variant configuration_digest")
        _require_non_empty_string(self.budget_tier, "study variant budget_tier")
        _require_string_tuple(
            self.ablates, "study variant ablates", non_empty=False, unique=True
        )


@dataclass(frozen=True, slots=True)
class StudyConcurrencyPolicy:
    """Frozen execution-concurrency identity for a scientific study.

    Parallelism can change contention, timing and therefore observations.  It is
    part of the protocol digest rather than an invisible runtime tuning knob.
    """

    max_parallel_repetitions: int
    parallel_assignments: bool
    cpu_isolation: str
    gpu_isolation: str
    environment_isolation: str
    model_admission_policy: str
    scheduler_policy: str
    repetition_timeout_seconds: float
    max_parallel_assignments: int

    @classmethod
    def serial_shared_v1(cls, *, repetition_timeout_seconds: float) -> Self:
        """Versioned canonical serial/shared execution policy.

        The factory is a stable named scientific contract; callers must still
        state the timeout explicitly because it participates in execution identity.
        """
        return cls(
            max_parallel_repetitions=1,
            parallel_assignments=False,
            cpu_isolation="shared",
            gpu_isolation="shared",
            environment_isolation="shared",
            model_admission_policy="runtime-hierarchical-v1",
            scheduler_policy="deterministic-priority-fair-v1",
            repetition_timeout_seconds=repetition_timeout_seconds,
            max_parallel_assignments=1,
        )

    @classmethod
    def isolated_parallel_v1(
        cls,
        *,
        max_parallel_repetitions: int,
        max_parallel_assignments: int,
        repetition_timeout_seconds: float,
        cpu_isolation: str = "worker",
        gpu_isolation: str = "provider-admission",
        environment_isolation: str = "per-assignment",
        model_admission_policy: str = "runtime-hierarchical-v1",
        scheduler_policy: str = "deterministic-priority-fair-v1",
    ) -> Self:
        """Canonical high-throughput policy for independently isolated assignments.

        The scientific protocol freezes *allowed* concurrency and isolation
        semantics. Runtime resource admission may execute fewer assignments when
        hardware/model capacity is lower, but it may never exceed these bounds.
        """
        return cls(
            max_parallel_repetitions=max_parallel_repetitions,
            parallel_assignments=True,
            cpu_isolation=cpu_isolation,
            gpu_isolation=gpu_isolation,
            environment_isolation=environment_isolation,
            model_admission_policy=model_admission_policy,
            scheduler_policy=scheduler_policy,
            repetition_timeout_seconds=repetition_timeout_seconds,
            max_parallel_assignments=max_parallel_assignments,
        )

    def __post_init__(self) -> None:
        _require_positive_int(
            self.max_parallel_repetitions, "max_parallel_repetitions"
        )
        if type(self.parallel_assignments) is not bool:
            raise TypeError("parallel_assignments must be boolean")
        _require_positive_int(self.max_parallel_assignments, "max_parallel_assignments")
        if self.parallel_assignments and self.max_parallel_assignments < 2:
            raise ValueError(
                "parallel_assignments requires max_parallel_assignments greater than one"
            )
        timeout = _require_finite_number(
            self.repetition_timeout_seconds, "repetition_timeout_seconds"
        )
        if timeout <= 0:
            raise ValueError("repetition_timeout_seconds must be positive")
        for name, value in (
            ("cpu_isolation", self.cpu_isolation),
            ("gpu_isolation", self.gpu_isolation),
            ("environment_isolation", self.environment_isolation),
            ("model_admission_policy", self.model_admission_policy),
            ("scheduler_policy", self.scheduler_policy),
        ):
            _require_non_empty_string(value, f"study concurrency {name}")


def _require_variants(value: object) -> tuple[StudyVariantSpec, ...]:
    if type(value) is not tuple:
        raise TypeError("study protocol variants must be a tuple")
    if not value:
        raise ValueError("study protocol requires at least one variant")
    if any(not isinstance(item, StudyVariantSpec) for item in value):
        raise TypeError("study protocol variants must contain StudyVariantSpec")
    variant_ids = tuple(item.variant_id for item in value)
    if len(variant_ids) != len(set(variant_ids)):
        raise ValueError("study protocol contains duplicate variants")
    return value


def _require_concurrency_policy(value: object) -> StudyConcurrencyPolicy:
    if not isinstance(value, StudyConcurrencyPolicy):
        raise TypeError("study protocol concurrency_policy must be StudyConcurrencyPolicy")
    return value


def _require_variant_budget_tiers(
    variants: tuple[StudyVariantSpec, ...], budget_tiers: tuple[str, ...]
) -> None:
    unknown = {item.budget_tier for item in variants} - set(budget_tiers)
    if unknown:
        raise ValueError(f"study variants use undeclared budget tiers: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class StudyProtocol:
    """Frozen research design consumed by every environment adapter."""

    study_id: str
    workload_id: str
    variants: tuple[StudyVariantSpec, ...]
    repetitions: int
    seed_schedule_digest: str
    metric_names: tuple[str, ...]
    task_manifest_digest: str
    budget_tiers: tuple[str, ...]
    concurrency_policy: StudyConcurrencyPolicy
    protocol_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study protocol study_id")
        _require_non_empty_string(self.workload_id, "study protocol workload_id")
        variants = _require_variants(self.variants)
        _require_positive_int(self.repetitions, "study protocol repetitions")
        _require_sha256(self.seed_schedule_digest, "study protocol seed_schedule_digest")
        metric_names = _require_string_tuple(
            self.metric_names, "study protocol metric_names", non_empty=False, unique=True
        )
        del metric_names
        _require_sha256(self.task_manifest_digest, "study protocol task_manifest_digest")
        budget_tiers = _require_string_tuple(
            self.budget_tiers, "study protocol budget_tiers", non_empty=True, unique=True
        )
        _require_concurrency_policy(self.concurrency_policy)
        _require_variant_budget_tiers(variants, budget_tiers)
        object.__setattr__(self, "protocol_digest", canonical_digest({
            "study_id": self.study_id,
            "workload_id": self.workload_id,
            "variants": self.variants,
            "repetitions": self.repetitions,
            "seed_schedule_digest": self.seed_schedule_digest,
            "metric_names": self.metric_names,
            "task_manifest_digest": self.task_manifest_digest,
            "budget_tiers": self.budget_tiers,
            "concurrency_policy": self.concurrency_policy,
        }))


@dataclass(frozen=True, slots=True)
class StudyAssignment:
    study_id: str
    variant_id: str
    repetition: int
    seed: str
    task_id: str | None = None
    assignment_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study assignment study_id")
        _require_non_empty_string(self.variant_id, "study assignment variant_id")
        _require_nonnegative_int(self.repetition, "study assignment repetition")
        _require_non_empty_string(self.seed, "study assignment seed")
        if self.task_id is not None:
            _require_non_empty_string(self.task_id, "study assignment task_id")
        object.__setattr__(self, "assignment_digest", canonical_digest({
            "study_id": self.study_id,
            "variant_id": self.variant_id,
            "repetition": self.repetition,
            "seed": self.seed,
            "task_id": self.task_id,
        }))


def _require_assignments(value: object) -> tuple[StudyAssignment, ...]:
    if type(value) is not tuple:
        raise TypeError("study execution unit assignments must be a tuple")
    if not value:
        raise ValueError("study execution unit assignments must be non-empty")
    if any(not isinstance(item, StudyAssignment) for item in value):
        raise TypeError("study execution unit assignments must contain StudyAssignment")
    return value


def _require_unit_assignment_identity(
    study_id: str, repetition: int, assignments: tuple[StudyAssignment, ...]
) -> tuple[str, ...]:
    if any(item.study_id != study_id for item in assignments):
        raise ValueError("study execution unit contains another study")
    if any(item.repetition != repetition for item in assignments):
        raise ValueError("study execution unit mixes repetitions")
    digests = tuple(item.assignment_digest for item in assignments)
    if len(digests) != len(set(digests)):
        raise ValueError("study execution unit contains duplicate assignments")
    return digests


@dataclass(frozen=True, slots=True)
class StudyExecutionUnit:
    """One reproducible repetition group passed to an environment adapter."""

    study_id: str
    repetition: int
    assignments: tuple[StudyAssignment, ...]
    unit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study execution unit study_id")
        _require_nonnegative_int(self.repetition, "study execution unit repetition")
        assignments = _require_assignments(self.assignments)
        digests = _require_unit_assignment_identity(
            self.study_id, self.repetition, assignments
        )
        object.__setattr__(self, "unit_digest", canonical_digest({
            "study_id": self.study_id,
            "repetition": self.repetition,
            "assignments": digests,
        }))


def _require_report_items(value: object, item_type: type, field: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"study matrix report {field} must be a tuple")
    if any(not isinstance(item, item_type) for item in value):
        raise TypeError(
            f"study matrix report {field} must contain {item_type.__name__}"
        )


@dataclass(frozen=True, slots=True)
class StudyMatrixExecutionReport:
    """Complete observations and aggregates for one frozen study matrix."""

    protocol_digest: str
    observations: tuple["StudyMetricObservation", ...]
    aggregates: tuple["StudyMetricAggregate", ...]
    binding_digest: str
    plan_digest: str

    def __post_init__(self) -> None:
        _require_sha256(self.protocol_digest, "study matrix report protocol_digest")
        _require_report_items(self.observations, StudyMetricObservation, "observations")
        _require_report_items(self.aggregates, StudyMetricAggregate, "aggregates")
        _require_sha256(self.binding_digest, "study matrix report binding_digest")
        _require_sha256(self.plan_digest, "study matrix report plan_digest")


def _require_metric_rows(value: object) -> tuple[tuple[str, float], ...]:
    if type(value) is not tuple:
        raise TypeError("study metric observation metrics must be a tuple")
    if not value:
        raise ValueError("study metric observation requires at least one metric")
    names: list[str] = []
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("study metric observation metric rows must be pairs")
        name, metric_value = row
        _require_non_empty_string(name, "study metric observation metric name")
        _require_finite_number(metric_value, f"study metric observation {name}")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("study metric observation requires unique metrics")
    return value


@dataclass(frozen=True, slots=True)
class StudyMetricObservation:
    assignment: StudyAssignment
    metrics: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, StudyAssignment):
            raise TypeError("study metric observation assignment must be StudyAssignment")
        _require_metric_rows(self.metrics)


@dataclass(frozen=True, slots=True)
class StudyMetricAggregate:
    study_id: str
    variant_id: str
    metric_name: str
    count: int
    mean: float
    sample_variance: float
    standard_error: float

    def __post_init__(self) -> None:
        _require_non_empty_string(self.study_id, "study aggregate study_id")
        _require_non_empty_string(self.variant_id, "study aggregate variant_id")
        _require_non_empty_string(self.metric_name, "study aggregate metric_name")
        _require_positive_int(self.count, "study aggregate count")
        _require_finite_number(self.mean, "study aggregate mean")
        variance = _require_finite_number(
            self.sample_variance, "study aggregate sample_variance"
        )
        error = _require_finite_number(
            self.standard_error, "study aggregate standard_error"
        )
        if variance < 0 or error < 0:
            raise ValueError("study aggregate variance and standard error cannot be negative")


__all__ = [
    "StudyConcurrencyPolicy",
    "StudyAssignment",
    "StudyExecutionUnit",
    "StudyMatrixExecutionReport",
    "StudyMetricAggregate",
    "StudyMetricObservation",
    "StudyProtocol",
    "StudyVariantSpec",
    "VariantKind",
]
