from __future__ import annotations

import math

import pytest

from noetrium_platform.composition.model_runtime_bootstrap import (
    _percentile,
    _select_kth_float,
)


def test_deterministic_selection_matches_sorted_reference_across_positions() -> None:
    values = [
        float(((index * 37) % 101) - 50)
        for index in range(257)
    ]
    ordered = sorted(values)
    for index in (0, 1, 17, 64, 128, 200, 255, 256):
        assert _select_kth_float(values, index) == ordered[index]


def test_percentile_preserves_nearest_rank_semantics() -> None:
    values = [9.0, 1.0, 5.0, 7.0, 3.0]
    assert _percentile(values, 0.0) == 1.0
    assert _percentile(values, 0.5) == 5.0
    assert _percentile(values, 0.95) == 9.0
    assert _percentile(values, 1.0) == 9.0


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_percentile_fails_closed_on_non_finite_measurement(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _percentile([1.0, value, 2.0], 0.5)
