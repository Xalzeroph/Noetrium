from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.travelplanner import (
    AGENTSQUARE_TRAVELPLANNER_EVALUATION_COUNT,
    AGENTSQUARE_TRAVELPLANNER_EVALUATION_SPLIT,
    AGENTSQUARE_TRAVELPLANNER_FULL_VALIDATION_SPLIT,
    AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT,
    AGENTSQUARE_TRAVELPLANNER_SEARCH_SPLIT,
    AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT,
    TravelPlannerTaskRecord,
    build_agentsquare_travelplanner_task_set,
)


def _records() -> tuple[TravelPlannerTaskRecord, ...]:
    return tuple(
        TravelPlannerTaskRecord(
            index=index,
            query=f"validation query {index}",
            level=("easy", "medium", "hard")[index % 3],
            content_digest=canonical_digest(
                {"travelplanner": "validation", "index": index}
            ),
        )
        for index in range(AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT)
    )


def test_agentsquare_travelplanner_freezes_full_source_and_released_eval_slice() -> None:
    benchmark = build_agentsquare_travelplanner_task_set(
        _records(),
        source_digest=canonical_digest(
            {"travelplanner": "validation-source", "revision": 1}
        ),
    )

    full = benchmark.selected_tasks(
        AGENTSQUARE_TRAVELPLANNER_FULL_VALIDATION_SPLIT
    )
    search = benchmark.selected_tasks(AGENTSQUARE_TRAVELPLANNER_SEARCH_SPLIT)
    evaluation = benchmark.selected_tasks(
        AGENTSQUARE_TRAVELPLANNER_EVALUATION_SPLIT
    )

    assert len(full) == AGENTSQUARE_TRAVELPLANNER_VALIDATION_COUNT == 180
    assert len(search) == AGENTSQUARE_TRAVELPLANNER_SEARCH_COUNT == 30
    assert len(evaluation) == AGENTSQUARE_TRAVELPLANNER_EVALUATION_COUNT == 30

    assert tuple(row.task_id for row in search) == tuple(
        f"travelplanner:validation:{index:03d}"
        for index in range(1, 31)
    )
    assert tuple(row.task_id for row in evaluation) == tuple(
        f"travelplanner:validation:{index:03d}"
        for index in range(151, 181)
    )
    assert not set(row.task_id for row in search) & set(
        row.task_id for row in evaluation
    )
