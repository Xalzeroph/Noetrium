"""Pure built-in score reducers for Evaluation scoring protocols."""

from __future__ import annotations

from collections import Counter
from math import comb, isfinite
import statistics

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.research.experimentation.lifecycle.evaluation.api.posthoc import (
    EvaluationReducerSpec,
    EvaluationReductionResult,
    EvaluationReductionState,
    EvaluationScore,
    EvaluationScoreState,
)


PrimitiveScore = bool | float | str


def _primitive(value: object) -> PrimitiveScore:
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
        "built-in evaluation reducers accept only bool, finite numeric, "
        "or non-empty string scores"
    )


def _validate_score_cut(scores: tuple[EvaluationScore, ...]) -> None:
    if type(scores) is not tuple or not scores:
        raise ValueError("evaluation score reduction requires a non-empty tuple")
    if any(type(score) is not EvaluationScore for score in scores):
        raise TypeError("evaluation score reduction requires EvaluationScore values")
    digests = tuple(score.score_digest for score in scores)
    if len(digests) != len(set(digests)):
        raise ValueError("evaluation score reduction contains duplicate source scores")


def _scored_values(
    scores: tuple[EvaluationScore, ...],
) -> tuple[tuple[EvaluationScore, PrimitiveScore], ...]:
    rows: list[tuple[EvaluationScore, PrimitiveScore]] = []
    for score in scores:
        if score.state is EvaluationScoreState.SCORED:
            rows.append((score, _primitive(score.value)))
    if rows and len({type(value) for _, value in rows}) != 1:
        raise TypeError("evaluation score epochs must have one stable value type")
    return tuple(rows)


def _numeric(
    values: tuple[PrimitiveScore, ...],
    reducer_id: str,
) -> tuple[float, ...]:
    if any(type(row) is bool or not isinstance(row, float) for row in values):
        raise TypeError(f"evaluation reducer {reducer_id} requires numeric scores")
    return tuple(float(row) for row in values)


def _base_metadata(
    scores: tuple[EvaluationScore, ...],
) -> dict[str, JsonValue]:
    unscored = tuple(
        {
            "score_digest": score.score_digest,
            "score_id": score.score_id,
            "reason": score.reason,
        }
        for score in scores
        if score.state is EvaluationScoreState.UNSCORED
    )
    return {} if not unscored else {"unscored_sources": unscored}


def _panel_metadata(
    scores: tuple[EvaluationScore, ...],
) -> dict[str, JsonValue]:
    panel = tuple(
        {
            "score_digest": score.score_digest,
            "score_id": score.score_id,
            "state": score.state.value,
            "value": score.value,
            "reason": score.reason,
        }
        for score in scores
    )
    metadata = _base_metadata(scores)
    metadata["panel"] = panel
    return metadata


def _scored(
    spec: EvaluationReducerSpec,
    scores: tuple[EvaluationScore, ...],
    scored_count: int,
    value: JsonValue,
    *,
    metadata: dict[str, JsonValue] | None = None,
) -> EvaluationReductionResult:
    return EvaluationReductionResult(
        reducer_digest=spec.reducer_digest,
        state=EvaluationReductionState.SCORED,
        source_score_digests=tuple(score.score_digest for score in scores),
        scored_source_count=scored_count,
        value=value,
        metadata=_base_metadata(scores) if metadata is None else metadata,
    )


def _unscored(
    spec: EvaluationReducerSpec,
    scores: tuple[EvaluationScore, ...],
    scored_count: int,
    reason: str,
    *,
    metadata: dict[str, JsonValue] | None = None,
) -> EvaluationReductionResult:
    return EvaluationReductionResult(
        reducer_digest=spec.reducer_digest,
        state=EvaluationReductionState.UNSCORED,
        source_score_digests=tuple(score.score_digest for score in scores),
        scored_source_count=scored_count,
        reason=reason,
        metadata=_base_metadata(scores) if metadata is None else metadata,
    )


def _k_configuration(spec: EvaluationReducerSpec) -> tuple[int, float]:
    raw_k = spec.configuration.get("k")
    raw_threshold = spec.configuration.get("threshold")
    if type(raw_k) is not int or raw_k <= 0:
        raise ValueError(
            f"evaluation reducer {spec.reducer_id} requires positive integer k"
        )
    if isinstance(raw_threshold, bool) or not isinstance(
        raw_threshold, (int, float)
    ):
        raise TypeError(
            f"evaluation reducer {spec.reducer_id} threshold must be numeric"
        )
    threshold = float(raw_threshold)
    if not isfinite(threshold):
        raise ValueError(
            f"evaluation reducer {spec.reducer_id} threshold must be finite"
        )
    return raw_k, threshold


def reduce_evaluation_scores(
    spec: EvaluationReducerSpec,
    scores: tuple[EvaluationScore, ...],
) -> EvaluationReductionResult:
    """Reduce one epoch-score cut according to a frozen reducer identity.

    Every source score remains independently addressable by digest. Built-ins
    exclude UNSCORED values from numeric estimators, while strict-majority keeps
    the full panel size as the voting threshold so scorer/grader abstention cannot
    silently lower the bar.

    Custom operation ids deliberately fail here: they belong in a downstream
    EvaluationProgram handler, while this helper is authoritative only for the
    platform's versioned built-ins.
    """

    if type(spec) is not EvaluationReducerSpec:
        raise TypeError("evaluation score reduction requires EvaluationReducerSpec")
    _validate_score_cut(scores)
    scored_rows = _scored_values(scores)
    scored_count = len(scored_rows)
    operation = spec.operation_id

    if not scored_rows:
        return _unscored(spec, scores, 0, "no_scored_epochs")

    normalized = tuple(value for _, value in scored_rows)

    if operation == "evaluation.reducer.collect":
        return _scored(spec, scores, scored_count, normalized)

    if operation == "evaluation.reducer.mode":
        frequencies = Counter(normalized)
        best = max(frequencies.values())
        winners = tuple(
            value
            for value, frequency in frequencies.items()
            if frequency == best
        )
        if len(winners) != 1:
            return _unscored(spec, scores, scored_count, "mode_tie")
        return _scored(spec, scores, scored_count, winners[0])

    if operation == "evaluation.reducer.majority":
        frequencies = Counter(normalized)
        panel_size = len(scores)
        winners = tuple(
            value
            for value, frequency in frequencies.items()
            if frequency * 2 > panel_size
        )
        metadata = _panel_metadata(scores)
        if len(winners) != 1:
            return _unscored(
                spec,
                scores,
                scored_count,
                "no_majority",
                metadata=metadata,
            )
        return _scored(
            spec,
            scores,
            scored_count,
            winners[0],
            metadata=metadata,
        )

    numbers = _numeric(normalized, spec.reducer_id)
    if operation == "evaluation.reducer.mean":
        return _scored(
            spec,
            scores,
            scored_count,
            statistics.fmean(numbers),
        )
    if operation == "evaluation.reducer.median":
        return _scored(
            spec,
            scores,
            scored_count,
            float(statistics.median(numbers)),
        )
    if operation == "evaluation.reducer.max":
        return _scored(spec, scores, scored_count, max(numbers))

    if operation in {
        "evaluation.reducer.pass_at_k",
        "evaluation.reducer.pass_k",
        "evaluation.reducer.at_least_k",
    }:
        k, threshold = _k_configuration(spec)
        if scored_count < k:
            return _unscored(
                spec,
                scores,
                scored_count,
                "insufficient_scored_epochs",
            )
        correct = sum(value >= threshold for value in numbers)
        if operation == "evaluation.reducer.at_least_k":
            return _scored(
                spec,
                scores,
                scored_count,
                1.0 if correct >= k else 0.0,
            )
        denominator = comb(scored_count, k)
        if operation == "evaluation.reducer.pass_at_k":
            failures = scored_count - correct
            probability = (
                1.0
                if failures < k
                else 1.0 - (comb(failures, k) / denominator)
            )
            return _scored(spec, scores, scored_count, probability)
        probability = (
            0.0 if correct < k else comb(correct, k) / denominator
        )
        return _scored(spec, scores, scored_count, probability)

    raise LookupError(
        f"evaluation reducer operation is not a platform built-in: {operation}"
    )


__all__ = ["reduce_evaluation_scores"]
