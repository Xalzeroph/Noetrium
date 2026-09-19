from __future__ import annotations

from hashlib import sha256

import pytest

from research.benchmarks.screenspot import ScreenSpotRecord, build_screenspot_task_set
from research.reproductions.seeclick import (
    SEECLICK_FIDELITY,
    SEECLICK_METHOD_PROGRAM,
    build_seeclick_screenspot_study,
    parse_seeclick_point,
    point_inside_bbox,
)


def _benchmark():
    row = ScreenSpotRecord(
        task_id="screenspot:web:text:001",
        screenshot_content_sha256=sha256(b"screenshot-001").hexdigest(),
        instruction="Click the checkout button",
        target_bbox=(0.70, 0.80, 0.90, 0.95),
        element_type="text",
        platform="Web",
    )
    return build_screenspot_task_set(
        (row,),
        dataset_content_sha256=sha256(b"screenspot-paper-cut").hexdigest(),
    )


def test_seeclick_coordinate_semantics_match_paper() -> None:
    point = parse_seeclick_point("(0.80, 0.90)")
    assert point.x == pytest.approx(0.80)
    assert point.y == pytest.approx(0.90)
    assert point_inside_bbox(point, (0.70, 0.80, 0.90, 0.95))
    assert SEECLICK_FIDELITY.coordinate_min == 0.0
    assert SEECLICK_FIDELITY.coordinate_max == 1.0
    assert SEECLICK_FIDELITY.coordinate_precision_decimals == 2


def test_seeclick_method_and_screenspot_study_are_protocol_bound() -> None:
    assert "grounding_accuracy" in SEECLICK_METHOD_PROGRAM.metric_names
    benchmark = _benchmark()
    study = build_seeclick_screenspot_study(
        benchmark,
        split_id="paper-test",
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.trial_protocol_identity.protocol_id == (
        "seeclick.acl2024.screenspot.v1"
    )
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == ("grounding_accuracy", "model_call_count")
