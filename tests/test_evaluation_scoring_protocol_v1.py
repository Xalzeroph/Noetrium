from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    EvaluationMetricSpec,
    EvaluationReducerKind,
    EvaluationReducerSpec,
    EvaluationReductionState,
    EvaluationScoreView,
    EvaluationScoringProtocol,
)
from noetrium_platform.research.experimentation.lifecycle.evaluation.runtime import (
    reduce_evaluation_scores,
)


def test_pass_estimators_use_scored_epoch_cut() -> None:
    values = (1.0, 0.0, 1.0)

    pass_at = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-at-2",
            EvaluationReducerKind.PASS_AT_K,
            k=2,
        ),
        values,
    )
    pass_k = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-k-2",
            EvaluationReducerKind.PASS_K,
            k=2,
        ),
        values,
    )

    assert pass_at.state is EvaluationReductionState.SCORED
    assert pass_at.value == pytest.approx(1.0)
    assert pass_k.state is EvaluationReductionState.SCORED
    assert pass_k.value == pytest.approx(1.0 / 3.0)


def test_insufficient_scored_epochs_are_unscored_not_zero() -> None:
    result = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-at-4",
            EvaluationReducerKind.PASS_AT_K,
            k=4,
        ),
        (1.0, 0.0, 1.0),
    )

    assert result.state is EvaluationReductionState.UNSCORED
    assert result.value is None
    assert result.reason == "insufficient_scored_epochs"


def test_mode_and_majority_fail_closed_on_ambiguous_epoch_cut() -> None:
    mode = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin("mode", EvaluationReducerKind.MODE),
        ("a", "b"),
    )
    majority = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "majority",
            EvaluationReducerKind.MAJORITY,
        ),
        (True, False),
    )

    assert mode.state is EvaluationReductionState.UNSCORED
    assert mode.reason == "mode_tie"
    assert majority.state is EvaluationReductionState.UNSCORED
    assert majority.reason == "no_majority"


def test_reducer_rejects_mixed_epoch_value_types() -> None:
    with pytest.raises(TypeError, match="stable value type"):
        reduce_evaluation_scores(
            EvaluationReducerSpec.builtin("mode", EvaluationReducerKind.MODE),
            (True, 1.0),
        )


def test_metric_score_view_is_explicit_and_reducer_refs_are_closed() -> None:
    reducer = EvaluationReducerSpec.builtin(
        "epoch-mean",
        EvaluationReducerKind.MEAN,
    )
    reduced = EvaluationMetricSpec(
        "accuracy",
        "score",
        EvaluationScoreView.REDUCED,
        "evaluation.metric.accuracy",
        "a" * 64,
        reducer_id="epoch-mean",
    )
    protocol = EvaluationScoringProtocol(
        "explicit-score-views",
        (reducer,),
        (reduced,),
        "accuracy",
    )
    assert protocol.reducer("epoch-mean") is reducer

    with pytest.raises(ValueError, match="cannot bind reducer"):
        EvaluationMetricSpec(
            "frequency",
            "score",
            EvaluationScoreView.UNREDUCED,
            "evaluation.metric.frequency",
            "b" * 64,
            reducer_id="epoch-mean",
        )

    with pytest.raises(ValueError, match="unknown reducers"):
        EvaluationScoringProtocol(
            "bad",
            (),
            (reduced,),
            "accuracy",
        )


def test_custom_reducer_identity_is_open_but_not_implicitly_executed() -> None:
    custom = EvaluationReducerSpec(
        "paper-reducer",
        "paper.custom.reducer",
        "c" * 64,
        {"temperature": 0.25},
    )
    with pytest.raises(LookupError, match="not a platform built-in"):
        reduce_evaluation_scores(custom, (1.0, 2.0))
