from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
CANDIDATE_UNCLASSIFIED_01 = MethodSourceLane(
    lane_id='candidate_unclassified_01',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/composable-models/llm_multiagent_debate',
    commit='9b32e0971105a3ada91706d130582bde9b9a855c',
    artifacts=(),
)

SOURCES = MethodSourceRegistry(
    lanes=(CANDIDATE_UNCLASSIFIED_01,),
)

__all__ = [
    "SOURCES",
    "CANDIDATE_UNCLASSIFIED_01",
]
