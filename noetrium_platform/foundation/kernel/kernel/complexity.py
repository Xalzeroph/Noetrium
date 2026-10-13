from __future__ import annotations

from dataclasses import dataclass, field
import math
import sys
from typing import Mapping, Protocol, runtime_checkable

from .canonical import canonical_digest
from .context import ExecutionContext


def _name(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha256(value: str, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _pairs(
    rows: tuple[tuple[str, int], ...],
    field_name: str,
    *,
    minimum: int = 0,
) -> tuple[tuple[str, int], ...]:
    if type(rows) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    normalized: list[tuple[str, int]] = []
    for name, value in rows:
        _name(name, f"{field_name} name")
        if type(value) is not int or value < minimum:
            raise ValueError(f"{field_name} values must be integers >= {minimum}")
        normalized.append((name, value))
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class ComplexityFactor:
    """One asymptotic factor n^(p/q) * log(n)^k."""

    variable: str
    power_numerator: int = 1
    power_denominator: int = 1
    log_power: int = 0

    def __post_init__(self) -> None:
        _name(self.variable, "complexity variable")
        if type(self.power_numerator) is not int or self.power_numerator < 0:
            raise ValueError("complexity power numerator must be non-negative integer")
        if type(self.power_denominator) is not int or self.power_denominator <= 0:
            raise ValueError("complexity power denominator must be positive integer")
        if type(self.log_power) is not int or self.log_power < 0:
            raise ValueError("complexity log power must be non-negative integer")
        if self.power_numerator == 0 and self.log_power == 0:
            raise ValueError("constant factor must be omitted rather than encoded")

    def as_payload(self) -> dict[str, object]:
        return {
            "variable": self.variable,
            "power_numerator": self.power_numerator,
            "power_denominator": self.power_denominator,
            "log_power": self.log_power,
        }


@dataclass(frozen=True, slots=True)
class ComplexityMonomial:
    """Product of factors. Empty factors denotes O(1)."""

    factors: tuple[ComplexityFactor, ...] = ()

    def __post_init__(self) -> None:
        if type(self.factors) is not tuple or any(
            type(row) is not ComplexityFactor for row in self.factors
        ):
            raise TypeError("complexity monomial factors must be typed tuple")
        ordered = tuple(sorted(self.factors, key=lambda row: row.variable))
        variables = tuple(row.variable for row in ordered)
        if len(variables) != len(set(variables)):
            raise ValueError("complexity monomial variables must be unique")
        object.__setattr__(self, "factors", ordered)

    def as_payload(self) -> dict[str, object]:
        return {"factors": tuple(row.as_payload() for row in self.factors)}


@dataclass(frozen=True, slots=True)
class ComplexityBound:
    """Canonical sum-of-monomials asymptotic upper bound."""

    terms: tuple[ComplexityMonomial, ...]

    def __post_init__(self) -> None:
        if (
            type(self.terms) is not tuple
            or not self.terms
            or any(type(row) is not ComplexityMonomial for row in self.terms)
        ):
            raise TypeError("complexity bound requires non-empty typed terms")
        keyed = tuple(
            sorted(
                (
                    canonical_digest(row.as_payload()),
                    row,
                )
                for row in self.terms
            )
        )
        digests = tuple(digest for digest, _ in keyed)
        if len(digests) != len(set(digests)):
            raise ValueError("complexity bound terms must be unique")
        object.__setattr__(self, "terms", tuple(row for _, row in keyed))

    @classmethod
    def constant(cls) -> "ComplexityBound":
        return cls((ComplexityMonomial(),))

    @classmethod
    def linear(cls, variable: str) -> "ComplexityBound":
        return cls((ComplexityMonomial((ComplexityFactor(variable),)),))

    @classmethod
    def linear_sum(cls, *variables: str) -> "ComplexityBound":
        if not variables:
            raise ValueError("linear complexity sum requires variables")
        normalized = tuple(sorted(set(variables)))
        if len(normalized) != len(variables):
            raise ValueError("linear complexity sum variables must be unique")
        return cls(
            tuple(
                ComplexityMonomial((ComplexityFactor(variable),))
                for variable in normalized
            )
        )

    @classmethod
    def logarithmic(cls, variable: str) -> "ComplexityBound":
        return cls(
            (
                ComplexityMonomial(
                    (
                        ComplexityFactor(
                            variable,
                            power_numerator=0,
                            log_power=1,
                        ),
                    )
                ),
            )
        )

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    factor.variable
                    for term in self.terms
                    for factor in term.factors
                }
            )
        )

    def _log_growth_proxy(
        self,
        scale_values: Mapping[str, int] | tuple[tuple[str, int], ...],
    ) -> float:
        scales = (
            dict(scale_values)
            if not isinstance(scale_values, Mapping)
            else scale_values
        )
        missing = tuple(
            variable for variable in self.variables if variable not in scales
        )
        if missing:
            raise KeyError(
                "complexity growth proxy lacks scale variables: "
                + ", ".join(missing)
            )
        term_logs: list[float] = []
        for term in self.terms:
            log_value = 0.0
            for factor in term.factors:
                raw = scales[factor.variable]
                if type(raw) is not int or raw < 0:
                    raise ValueError(
                        "complexity scale values must be non-negative integers"
                    )
                # Big-O is asymptotic; max(1,n) keeps finite-scale zero inputs
                # from erasing fixed work, while log(max(2,n)) keeps log terms
                # defined without choosing an arbitrary additive constant.
                n = float(max(1, raw))
                if factor.power_numerator:
                    log_value += (
                        factor.power_numerator
                        / factor.power_denominator
                    ) * math.log(n)
                if factor.log_power:
                    log_value += factor.log_power * math.log(
                        math.log(float(max(2, raw)))
                    )
            term_logs.append(log_value)
        peak = max(term_logs)
        return peak + math.log(
            sum(math.exp(value - peak) for value in term_logs)
        )

    def growth_proxy(
        self,
        scale_values: Mapping[str, int] | tuple[tuple[str, int], ...],
    ) -> float:
        """Finite-scale proxy for the declared asymptotic growth function.

        This is deliberately not a Big-O proof.  It turns the symbolic bound
        into a canonical positive growth coordinate so repeated observations
        at different scales can be normalized and compared.
        """

        log_value = self._log_growth_proxy(scale_values)
        max_log = math.log(sys.float_info.max)
        if log_value >= max_log:
            return sys.float_info.max
        return max(sys.float_info.min, math.exp(log_value))

    def normalize_cost(
        self,
        cost: int | float,
        scale_values: Mapping[str, int] | tuple[tuple[str, int], ...],
    ) -> float:
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            raise TypeError("complexity normalized cost must be numeric")
        value = float(cost)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                "complexity normalized cost must be finite and non-negative"
            )
        if value == 0.0:
            return 0.0
        log_ratio = math.log(value) - self._log_growth_proxy(scale_values)
        max_log = math.log(sys.float_info.max)
        if log_ratio >= max_log:
            return sys.float_info.max
        if log_ratio <= math.log(sys.float_info.min):
            return 0.0
        return math.exp(log_ratio)

    def as_payload(self) -> dict[str, object]:
        return {"terms": tuple(row.as_payload() for row in self.terms)}


@dataclass(frozen=True, slots=True)
class ComplexityContract:
    """Mathematically declared asymptotic bounds for one immutable implementation."""

    algorithm_id: str
    implementation_digest: str
    time_upper_bound: ComplexityBound
    space_upper_bound: ComplexityBound
    assumptions: tuple[str, ...] = ()
    time_lower_bound: ComplexityBound | None = None
    space_lower_bound: ComplexityBound | None = None
    contract_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _name(self.algorithm_id, "complexity algorithm_id")
        _sha256(self.implementation_digest, "complexity implementation_digest")
        if type(self.time_upper_bound) is not ComplexityBound:
            raise TypeError("complexity time_upper_bound must be typed")
        if type(self.space_upper_bound) is not ComplexityBound:
            raise TypeError("complexity space_upper_bound must be typed")
        for field_name in ("time_lower_bound", "space_lower_bound"):
            value = getattr(self, field_name)
            if value is not None and type(value) is not ComplexityBound:
                raise TypeError(f"complexity {field_name} must be typed or None")
        if type(self.assumptions) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.assumptions
        ):
            raise TypeError("complexity assumptions must be text tuple")
        ordered = tuple(sorted(set(self.assumptions)))
        if len(ordered) != len(self.assumptions):
            raise ValueError("complexity assumptions must be unique")
        object.__setattr__(self, "assumptions", ordered)
        object.__setattr__(
            self,
            "contract_digest",
            canonical_digest(
                {
                    "algorithm_id": self.algorithm_id,
                    "implementation_digest": self.implementation_digest,
                    "time_upper_bound": self.time_upper_bound.as_payload(),
                    "space_upper_bound": self.space_upper_bound.as_payload(),
                    "time_lower_bound": (
                        None
                        if self.time_lower_bound is None
                        else self.time_lower_bound.as_payload()
                    ),
                    "space_lower_bound": (
                        None
                        if self.space_lower_bound is None
                        else self.space_lower_bound.as_payload()
                    ),
                    "assumptions": self.assumptions,
                }
            ),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "algorithm_id": self.algorithm_id,
            "implementation_digest": self.implementation_digest,
            "time_upper_bound": self.time_upper_bound.as_payload(),
            "space_upper_bound": self.space_upper_bound.as_payload(),
            "time_lower_bound": (
                None
                if self.time_lower_bound is None
                else self.time_lower_bound.as_payload()
            ),
            "space_lower_bound": (
                None
                if self.space_lower_bound is None
                else self.space_lower_bound.as_payload()
            ),
            "time_tight": self.time_tight,
            "space_tight": self.space_tight,
            "assumptions": self.assumptions,
            "contract_digest": self.contract_digest,
        }

    @property
    def time_tight(self) -> bool:
        return (
            self.time_lower_bound is not None
            and self.time_lower_bound == self.time_upper_bound
        )

    @property
    def space_tight(self) -> bool:
        return (
            self.space_lower_bound is not None
            and self.space_lower_bound == self.space_upper_bound
        )


@dataclass(frozen=True, slots=True)
class RuntimeCostObservation:
    """Exact measured cost facts for one graph-bound execution interval."""

    coordinate_digest: str
    algorithm_id: str
    implementation_digest: str | None
    contract_digest: str | None
    outcome: str
    wall_ns: int
    cpu_ns: int
    rss_start_bytes: int | None = None
    rss_end_bytes: int | None = None
    rss_peak_process_bytes: int | None = None
    work_ns: int | None = None
    critical_span_ns: int | None = None
    scale_values: tuple[tuple[str, int], ...] = ()
    work_counters: tuple[tuple[str, int], ...] = ()
    time_ns: tuple[tuple[str, int], ...] = ()
    wait_ns: tuple[tuple[str, int], ...] = ()
    io_bytes: tuple[tuple[str, int], ...] = ()
    memory_bytes: tuple[tuple[str, int], ...] = ()
    observation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha256(self.coordinate_digest, "runtime cost coordinate_digest")
        _name(self.algorithm_id, "runtime cost algorithm_id")
        if self.implementation_digest is not None:
            _sha256(
                self.implementation_digest,
                "runtime cost implementation_digest",
            )
        if self.contract_digest is not None:
            _sha256(self.contract_digest, "runtime cost contract_digest")
        if self.outcome not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("runtime cost outcome is invalid")
        for name in ("wall_ns", "cpu_ns"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"runtime cost {name} must be non-negative integer")
        for name in (
            "rss_start_bytes",
            "rss_end_bytes",
            "rss_peak_process_bytes",
            "work_ns",
            "critical_span_ns",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"runtime cost {name} must be non-negative integer or None")
        if (
            self.work_ns is not None
            and self.critical_span_ns is not None
            and self.critical_span_ns > self.work_ns
        ):
            raise ValueError("runtime cost critical span cannot exceed total work")
        for name in (
            "scale_values",
            "work_counters",
            "time_ns",
            "wait_ns",
            "io_bytes",
            "memory_bytes",
        ):
            object.__setattr__(
                self,
                name,
                _pairs(getattr(self, name), f"runtime cost {name}"),
            )
        object.__setattr__(
            self,
            "observation_digest",
            canonical_digest(self._digest_payload()),
        )

    def _digest_payload(self) -> dict[str, object]:
        return {
            "coordinate_digest": self.coordinate_digest,
            "algorithm_id": self.algorithm_id,
            "implementation_digest": self.implementation_digest,
            "contract_digest": self.contract_digest,
            "outcome": self.outcome,
            "wall_ns": self.wall_ns,
            "cpu_ns": self.cpu_ns,
            "rss_start_bytes": self.rss_start_bytes,
            "rss_end_bytes": self.rss_end_bytes,
            "rss_peak_process_bytes": self.rss_peak_process_bytes,
            "work_ns": self.work_ns,
            "critical_span_ns": self.critical_span_ns,
            "scale_values": self.scale_values,
            "work_counters": self.work_counters,
            "time_ns": self.time_ns,
            "wait_ns": self.wait_ns,
            "io_bytes": self.io_bytes,
            "memory_bytes": self.memory_bytes,
        }

    @property
    def average_parallelism(self) -> float | None:
        if (
            self.work_ns is None
            or self.critical_span_ns is None
            or self.critical_span_ns == 0
        ):
            return None
        return self.work_ns / self.critical_span_ns

    def as_payload(self) -> dict[str, object]:
        return {
            **self._digest_payload(),
            "average_parallelism": self.average_parallelism,
            "observation_digest": self.observation_digest,
        }


@runtime_checkable
class CostObservationSinkPort(Protocol):
    def observe(
        self,
        context: ExecutionContext,
        observation: RuntimeCostObservation,
        *,
        contract: ComplexityContract | None = None,
    ) -> object: ...



from contextvars import ContextVar, Token
import os
from pathlib import Path
from threading import RLock

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX host
    resource = None
import time

from .context import ExecutionContext


_CURRENT_COST_SCOPE: ContextVar["RuntimeCostScope | None"] = ContextVar(
    "noetrium_runtime_cost_scope",
    default=None,
)


def _current_rss_bytes() -> int | None:
    try:
        raw = (Path("/proc/self/statm")).read_text(encoding="ascii").split()
        if len(raw) < 2:
            return None
        return int(raw[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, TypeError):
        return None


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (OSError, ValueError, TypeError):
        return None
    if value < 0:
        return None
    # Linux reports KiB; Darwin reports bytes.
    return value if sys.platform == "darwin" else value * 1024


class RuntimeCostScope:
    """Low-overhead graph-bound accumulator for measured execution costs."""

    def __init__(
        self,
        context: ExecutionContext,
        *,
        algorithm_id: str,
        implementation_digest: str | None = None,
        contract: ComplexityContract | None = None,
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise TypeError("runtime cost scope requires ExecutionContext")
        if context.graph_coordinate is None:
            raise ValueError("runtime cost scope requires graph execution coordinate")
        if type(algorithm_id) is not str or not algorithm_id.strip():
            raise ValueError("runtime cost scope algorithm_id must be non-empty")
        if contract is not None:
            if type(contract) is not ComplexityContract:
                raise TypeError("runtime cost scope contract must be typed")
            if contract.algorithm_id != algorithm_id:
                raise ValueError("runtime cost scope contract algorithm identity drift")
            if implementation_digest is None:
                implementation_digest = contract.implementation_digest
            elif implementation_digest != contract.implementation_digest:
                raise ValueError(
                    "runtime cost scope implementation/contract identity drift"
                )
        self.context = context
        self.algorithm_id = algorithm_id
        self.implementation_digest = implementation_digest
        self.contract = contract
        self._lock = RLock()
        self._scale: dict[str, int] = {}
        self._work: dict[str, int] = {}
        self._time_ns: dict[str, int] = {}
        self._wait_ns: dict[str, int] = {}
        self._io_bytes: dict[str, int] = {}
        self._memory_bytes: dict[str, int] = {}
        self._work_ns: int | None = None
        self._critical_span_ns: int | None = None
        self._started_wall_ns: int | None = None
        self._started_cpu_ns: int | None = None
        self._rss_start_bytes: int | None = None
        self._token: Token | None = None
        self.observation: RuntimeCostObservation | None = None

    def _increment(self, target: dict[str, int], name: str, value: int) -> None:
        if type(name) is not str or not name.strip():
            raise ValueError("runtime cost counter name must be non-empty")
        if type(value) is not int or value < 0:
            raise ValueError("runtime cost counter increment must be non-negative")
        with self._lock:
            target[name] = target.get(name, 0) + value

    def set_scale(self, name: str, value: int) -> None:
        if type(name) is not str or not name.strip():
            raise ValueError("runtime cost scale name must be non-empty")
        if type(value) is not int or value < 0:
            raise ValueError("runtime cost scale value must be non-negative")
        with self._lock:
            self._scale[name] = value

    def add_work(self, name: str, count: int = 1) -> None:
        self._increment(self._work, name, count)

    def add_time_ns(self, name: str, value: int) -> None:
        self._increment(self._time_ns, name, value)

    def add_wait_ns(self, name: str, value: int) -> None:
        self._increment(self._wait_ns, name, value)

    def add_io_bytes(self, name: str, value: int) -> None:
        self._increment(self._io_bytes, name, value)

    def set_memory_bytes(self, name: str, value: int) -> None:
        if type(name) is not str or not name.strip():
            raise ValueError("runtime cost memory name must be non-empty")
        if type(value) is not int or value < 0:
            raise ValueError("runtime cost memory value must be non-negative")
        with self._lock:
            self._memory_bytes[name] = value

    def set_work_span(self, *, work_ns: int, critical_span_ns: int) -> None:
        if (
            type(work_ns) is not int
            or type(critical_span_ns) is not int
            or work_ns < 0
            or critical_span_ns < 0
            or critical_span_ns > work_ns
        ):
            raise ValueError("runtime cost work/span values are invalid")
        with self._lock:
            self._work_ns = work_ns
            self._critical_span_ns = critical_span_ns

    def __enter__(self) -> "RuntimeCostScope":
        if self._token is not None:
            raise RuntimeError("runtime cost scope cannot be entered twice")
        self._started_wall_ns = time.perf_counter_ns()
        self._started_cpu_ns = time.process_time_ns()
        self._rss_start_bytes = _current_rss_bytes()
        self._token = _CURRENT_COST_SCOPE.set(self)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        completed_wall_ns = time.perf_counter_ns()
        completed_cpu_ns = time.process_time_ns()
        token = self._token
        if token is None or self._started_wall_ns is None or self._started_cpu_ns is None:
            raise RuntimeError("runtime cost scope exit without active scope")
        self._token = None
        _CURRENT_COST_SCOPE.reset(token)
        if exc_type is None:
            outcome = "succeeded"
        elif issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            outcome = "cancelled"
        else:
            outcome = "failed"
        coordinate = self.context.graph_coordinate
        if coordinate is None:
            raise RuntimeError("runtime cost scope lost graph coordinate")
        rss_end = _current_rss_bytes()
        rss_peak = _peak_rss_bytes()
        observed_rss = tuple(
            value
            for value in (self._rss_start_bytes, rss_end, rss_peak)
            if value is not None
        )
        if observed_rss:
            rss_peak = max(observed_rss)
        with self._lock:
            self.observation = RuntimeCostObservation(
                coordinate_digest=coordinate.coordinate_digest,
                algorithm_id=self.algorithm_id,
                implementation_digest=self.implementation_digest,
                contract_digest=(
                    None if self.contract is None else self.contract.contract_digest
                ),
                outcome=outcome,
                wall_ns=max(0, completed_wall_ns - self._started_wall_ns),
                cpu_ns=max(0, completed_cpu_ns - self._started_cpu_ns),
                rss_start_bytes=self._rss_start_bytes,
                rss_end_bytes=rss_end,
                rss_peak_process_bytes=rss_peak,
                work_ns=self._work_ns,
                critical_span_ns=self._critical_span_ns,
                scale_values=tuple(self._scale.items()),
                work_counters=tuple(self._work.items()),
                time_ns=tuple(self._time_ns.items()),
                wait_ns=tuple(self._wait_ns.items()),
                io_bytes=tuple(self._io_bytes.items()),
                memory_bytes=tuple(self._memory_bytes.items()),
            )
        return False


def current_runtime_cost_scope() -> RuntimeCostScope | None:
    return _CURRENT_COST_SCOPE.get()


def set_cost_scale(name: str, value: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.set_scale(name, value)


def add_cost_work(name: str, count: int = 1) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.add_work(name, count)


def add_cost_time_ns(name: str, value: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.add_time_ns(name, value)


def add_cost_wait_ns(name: str, value: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.add_wait_ns(name, value)


def add_cost_io_bytes(name: str, value: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.add_io_bytes(name, value)


def set_cost_memory_bytes(name: str, value: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.set_memory_bytes(name, value)


def set_cost_work_span(*, work_ns: int, critical_span_ns: int) -> None:
    scope = current_runtime_cost_scope()
    if scope is not None:
        scope.set_work_span(work_ns=work_ns, critical_span_ns=critical_span_ns)


__all__ = [
    "ComplexityBound",
    "ComplexityContract",
    "ComplexityFactor",
    "ComplexityMonomial",
    "CostObservationSinkPort",
    "RuntimeCostObservation",
    "RuntimeCostScope",
    "add_cost_io_bytes",
    "add_cost_time_ns",
    "add_cost_wait_ns",
    "add_cost_work",
    "current_runtime_cost_scope",
    "set_cost_memory_bytes",
    "set_cost_scale",
    "set_cost_work_span",
]
