from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    EvaluationMetricSpec,
    EvaluationReducerKind,
    EvaluationReducerSpec,
    EvaluationReductionState,
    EvaluationScore,
    EvaluationScoreState,
    EvaluationScoreView,
    EvaluationScoringProtocol,
)
from noetrium_platform.research.experimentation.lifecycle.evaluation.runtime import (
    reduce_evaluation_scores,
)


def _score(index: int, value) -> EvaluationScore:
    return EvaluationScore.scored(
        f"epoch-{index}",
        value,
        explanation=f"grader explanation {index}",
        metadata={"epoch": index},
    )


def test_pass_estimators_use_scored_epoch_cut() -> None:
    scores = (_score(0, 1.0), _score(1, 0.0), _score(2, 1.0))

    pass_at = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-at-2",
            EvaluationReducerKind.PASS_AT_K,
            k=2,
        ),
        scores,
    )
    pass_k = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-k-2",
            EvaluationReducerKind.PASS_K,
            k=2,
        ),
        scores,
    )

    assert pass_at.state is EvaluationReductionState.SCORED
    assert pass_at.value == pytest.approx(1.0)
    assert pass_at.source_count == 3
    assert pass_at.scored_source_count == 3
    assert pass_k.state is EvaluationReductionState.SCORED
    assert pass_k.value == pytest.approx(1.0 / 3.0)


def test_insufficient_scored_epochs_are_unscored_not_zero() -> None:
    scores = (
        _score(0, 1.0),
        EvaluationScore.unscored(
            "epoch-1",
            reason="grader_failed",
            explanation="grader response did not match the schema",
        ),
        _score(2, 1.0),
        _score(3, 0.0),
    )
    result = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "pass-at-4",
            EvaluationReducerKind.PASS_AT_K,
            k=4,
        ),
        scores,
    )

    assert result.state is EvaluationReductionState.UNSCORED
    assert result.value is None
    assert result.reason == "insufficient_scored_epochs"
    assert result.source_count == 4
    assert result.scored_source_count == 3
    assert result.metadata["unscored_sources"][0]["reason"] == "grader_failed"


def test_majority_counts_unscored_panel_member_toward_threshold() -> None:
    scores = (
        _score(0, True),
        _score(1, True),
        EvaluationScore.unscored(
            "epoch-2",
            reason="grader_failed",
        ),
        EvaluationScore.unscored(
            "epoch-3",
            reason="scoring_failed",
        ),
    )
    result = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "majority",
            EvaluationReducerKind.MAJORITY,
        ),
        scores,
    )

    assert result.state is EvaluationReductionState.UNSCORED
    assert result.reason == "no_majority"
    assert result.scored_source_count == 2
    assert len(result.metadata["panel"]) == 4
    assert result.metadata["panel"][2]["state"] == "unscored"


def test_mode_and_majority_fail_closed_on_ambiguous_epoch_cut() -> None:
    mode = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin("mode", EvaluationReducerKind.MODE),
        (_score(0, "a"), _score(1, "b")),
    )
    majority = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin(
            "majority",
            EvaluationReducerKind.MAJORITY,
        ),
        (_score(2, True), _score(3, False)),
    )

    assert mode.state is EvaluationReductionState.UNSCORED
    assert mode.reason == "mode_tie"
    assert majority.state is EvaluationReductionState.UNSCORED
    assert majority.reason == "no_majority"


def test_all_unscored_epochs_preserve_reason_provenance() -> None:
    scores = (
        EvaluationScore.unscored("epoch-0", reason="refusal"),
        EvaluationScore.unscored("epoch-1", reason="grader_failed"),
    )
    result = reduce_evaluation_scores(
        EvaluationReducerSpec.builtin("mean", EvaluationReducerKind.MEAN),
        scores,
    )

    assert result.state is EvaluationReductionState.UNSCORED
    assert result.reason == "no_scored_epochs"
    assert result.scored_source_count == 0
    assert tuple(
        row["reason"] for row in result.metadata["unscored_sources"]
    ) == ("refusal", "grader_failed")


def test_reducer_rejects_mixed_scored_value_types() -> None:
    with pytest.raises(TypeError, match="stable value type"):
        reduce_evaluation_scores(
            EvaluationReducerSpec.builtin("mode", EvaluationReducerKind.MODE),
            (_score(0, True), _score(1, 1.0)),
        )


def test_evaluation_score_identity_binds_explanation_and_metadata() -> None:
    first = EvaluationScore.scored(
        "epoch-0",
        1.0,
        answer="answer",
        explanation="grader trace A",
        metadata={"judge": "a"},
    )
    changed = EvaluationScore.scored(
        "epoch-0",
        1.0,
        answer="answer",
        explanation="grader trace B",
        metadata={"judge": "a"},
    )

    assert first.state is EvaluationScoreState.SCORED
    assert first.score_digest != changed.score_digest


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
        reduce_evaluation_scores(
            custom,
            (_score(0, 1.0), _score(1, 2.0)),
        )
