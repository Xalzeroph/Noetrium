from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.request.prompt.runtime.budget import (
    ModelRequestBudgetExceeded,
    ModelRequestProjection,
    ModelRequestReprojectionFailed,
    fit_model_request_budget_with_reprojection,
)


class LengthCounter:
    def count(self, text: str) -> int:
        return len(text)


def test_overflow_allows_exactly_one_semantic_owner_reprojection() -> None:
    source = {
        "messages": [{"role": "user", "content": "x" * 90}],
        "max_tokens": 20,
    }
    calls: list[int] = []

    def reproject(report):
        calls.append(report.input_tokens)
        return ModelRequestProjection(
            "agent.history.compaction",
            {
                "messages": [{"role": "user", "content": "x" * 40}],
                "max_tokens": 20,
            },
            "x" * 40,
        )

    fitted, prompt, report, receipt = fit_model_request_budget_with_reprojection(
        source,
        context_length=100,
        token_counter=LengthCounter(),
        minimum_output_tokens=20,
        reproject=reproject,
    )

    assert len(calls) == 1
    assert fitted["max_tokens"] == 20
    assert prompt == "x" * 40
    assert report is not None and report.fits
    assert receipt is not None and receipt.reduced_input
    assert receipt.attempt_count == 1
    assert receipt.projection_id == "agent.history.compaction"


def test_reprojection_cannot_change_output_reservation() -> None:
    source = {
        "messages": [{"role": "user", "content": "x" * 90}],
        "max_tokens": 20,
    }

    def reproject(_report):
        return ModelRequestProjection(
            "bad-projector",
            {"messages": [{"role": "user", "content": "x"}], "max_tokens": 19},
        )

    with pytest.raises(ValueError, match="cannot change model output reservation"):
        fit_model_request_budget_with_reprojection(
            source,
            context_length=100,
            token_counter=LengthCounter(),
            minimum_output_tokens=20,
            reproject=reproject,
        )


def test_second_overflow_fails_closed_with_reprojection_receipt() -> None:
    source = {
        "messages": [{"role": "user", "content": "x" * 90}],
        "max_tokens": 20,
    }
    calls = 0

    def reproject(_report):
        nonlocal calls
        calls += 1
        return ModelRequestProjection(
            "still-too-large",
            {
                "messages": [{"role": "user", "content": "y" * 89}],
                "max_tokens": 20,
            },
        )

    with pytest.raises(ModelRequestReprojectionFailed) as raised:
        fit_model_request_budget_with_reprojection(
            source,
            context_length=100,
            token_counter=LengthCounter(),
            minimum_output_tokens=20,
            reproject=reproject,
        )

    assert calls == 1
    assert raised.value.receipt.attempt_count == 1
    assert raised.value.receipt.projection_id == "still-too-large"
    assert raised.value.initial_report.input_tokens >= raised.value.report.input_tokens


def test_no_reprojector_preserves_fail_closed_behavior() -> None:
    source = {
        "messages": [{"role": "user", "content": "x" * 90}],
        "max_tokens": 20,
    }

    with pytest.raises(ModelRequestBudgetExceeded):
        fit_model_request_budget_with_reprojection(
            source,
            context_length=100,
            token_counter=LengthCounter(),
            minimum_output_tokens=20,
        )
