"""Pure built-in score reducers for Evaluation scoring protocols."""

from __future__ import annotations

from collections import Counter
from math import comb, isfinite
import statistics

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from noetrium_platform.research.experimentation.lifecycle.evaluation.api.posthoc import (
    EvaluationReducerSpec,
    EvaluationReductionResult,
    EvaluationReductionState,
)


def _primitive(value: object) -> bool | float | str:
    if type(value) is bool:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not isfinite(number):
            raise ValueError("evaluation score values must be finite")
        return number
    if type(value) is str and value.strip():
        return value
    raise TypeError(
        "built-in evaluation reducers accept only bool, finite numeric, or non-empty string scores"
    )


def _numeric(values: tuple[bool | float | str, ...], reducer_id: str) -> tuple[float, ...]:
    if any(type(row) is bool or not isinstance(row, float) for row in values):
        raise TypeError(f"evaluation reducer {reducer_id} requires numeric scores")
    return tuple(float(row) for row in values)


def _scored(spec: EvaluationReducerSpec, count: int, value: JsonValue) -> EvaluationReductionResult:
    return EvaluationReductionResult(
        reducer_digest=spec.reducer_digest,
        state=EvaluationReductionState.SCORED,
        source_count=count,
        value=value,
    )


def _unscored(spec: EvaluationReducerSpec, count: int, reason: str) -> EvaluationReductionResult:
    return EvaluationReductionResult(
        reducer_digest=spec.reducer_digest,
        state=EvaluationReductionState.UNSCORED,
        source_count=count,
        reason=reason,
    )


def _k_configuration(spec: EvaluationReducerSpec) -> tuple[int, float]:
    raw_k = spec.configuration.get("k")
    raw_threshold = spec.configuration.get("threshold")
    if type(raw_k) is not int or raw_k <= 0:
        raise ValueError(f"evaluation reducer {spec.reducer_id} requires positive integer k")
    if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
        raise TypeError(f"evaluation reducer {spec.reducer_id} threshold must be numeric")
    threshold = float(raw_threshold)
    if not isfinite(threshold):
        raise ValueError(f"evaluation reducer {spec.reducer_id} threshold must be finite")
    return raw_k, threshold


def reduce_evaluation_scores(
    spec: EvaluationReducerSpec,
    values: tuple[JsonValue, ...],
) -> EvaluationReductionResult:
    """Reduce one scored epoch cut according to a frozen reducer identity.

    Custom operation ids deliberately fail here: they belong in a downstream
    EvaluationProgram handler, while this helper is authoritative only for the
    platform's versioned built-ins.
    """

    if type(spec) is not EvaluationReducerSpec:
        raise TypeError("evaluation score reduction requires EvaluationReducerSpec")
    if type(values) is not tuple or not values:
        raise ValueError("evaluation score reduction requires a non-empty tuple")
    normalized = tuple(_primitive(value) for value in values)
    count = len(normalized)
    operation = spec.operation_id

    if operation == "evaluation.reducer.collect":
        return _scored(spec, count, normalized)

    if operation == "evaluation.reducer.mode":
        frequencies = Counter(normalized)
        best = max(frequencies.values())
        winners = tuple(value for value, frequency in frequencies.items() if frequency == best)
        if len(winners) != 1:
            return _unscored(spec, count, "mode_tie")
        return _scored(spec, count, winners[0])

    if operation == "evaluation.reducer.majority":
        frequencies = Counter(normalized)
        winners = tuple(
            value for value, frequency in frequencies.items()
            if frequency > count / 2
        )
        if len(winners) != 1:
            return _unscored(spec, count, "no_majority")
        return _scored(spec, count, winners[0])

    numbers = _numeric(normalized, spec.reducer_id)
    if operation == "evaluation.reducer.mean":
        return _scored(spec, count, statistics.fmean(numbers))
    if operation == "evaluation.reducer.median":
        return _scored(spec, count, float(statistics.median(numbers)))
    if operation == "evaluation.reducer.max":
        return _scored(spec, count, max(numbers))

    if operation in {
        "evaluation.reducer.pass_at_k",
        "evaluation.reducer.pass_k",
        "evaluation.reducer.at_least_k",
    }:
        k, threshold = _k_configuration(spec)
        if count < k:
            return _unscored(spec, count, "insufficient_scored_epochs")
        correct = sum(value >= threshold for value in numbers)
        if operation == "evaluation.reducer.at_least_k":
            return _scored(spec, count, 1.0 if correct >= k else 0.0)
        denominator = comb(count, k)
        if operation == "evaluation.reducer.pass_at_k":
            failures = count - correct
            probability = (
                1.0
                if failures < k
                else 1.0 - (comb(failures, k) / denominator)
            )
            return _scored(spec, count, probability)
        probability = 0.0 if correct < k else comb(correct, k) / denominator
        return _scored(spec, count, probability)

    raise LookupError(
        f"evaluation reducer operation is not a platform built-in: {operation}"
    )


__all__ = ["reduce_evaluation_scores"]
