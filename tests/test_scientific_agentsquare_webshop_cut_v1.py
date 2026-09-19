from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.webshop import (
    AGENTSQUARE_WEBSHOP_REVISION,
    AGENTSQUARE_WEBSHOP_SPLIT,
    AGENTSQUARE_WEBSHOP_TASK_COUNT,
    AgentSquareWebShopTaskRecord,
    build_agentsquare_webshop_task_set,
)


def _records() -> tuple[AgentSquareWebShopTaskRecord, ...]:
    return tuple(
        AgentSquareWebShopTaskRecord(
            index=index,
            content_digest=canonical_digest(
                {"session": f"fixed_{index}", "source": "agentsquare"}
            ),
        )
        for index in range(AGENTSQUARE_WEBSHOP_TASK_COUNT)
    )


def test_agentsquare_webshop_cut_freezes_all_500_released_sessions() -> None:
    benchmark = build_agentsquare_webshop_task_set(
        _records(),
        source_digest=canonical_digest({"source": "agentsquare-webshop"}),
    )

    assert benchmark.revision_id == AGENTSQUARE_WEBSHOP_REVISION
    selected = benchmark.selected_tasks(AGENTSQUARE_WEBSHOP_SPLIT)
    assert len(selected) == 500
    assert selected[0].task_id == "webshop:fixed_0"
    assert selected[-1].task_id == "webshop:fixed_499"
    assert len({row.task_id for row in selected}) == 500


def test_agentsquare_webshop_cut_rejects_lats_sized_subset() -> None:
    with pytest.raises(ValueError, match="0 through 499"):
        build_agentsquare_webshop_task_set(
            _records()[:50],
            source_digest=canonical_digest({"source": "agentsquare-webshop"}),
        )


def test_agentsquare_webshop_record_rejects_out_of_range_session() -> None:
    with pytest.raises(ValueError, match="\[0, 500\)"):
        AgentSquareWebShopTaskRecord(
            index=500,
            content_digest="a" * 64,
        )
