from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
CANDIDATE_UNCLASSIFIED_01 = MethodSourceLane(
    lane_id='candidate_unclassified_01',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/microsoft/autogen',
    commit='904b293aa47c0e87e27e127254ce4f17a391048c',
    artifacts=(),
)

SOURCES = MethodSourceRegistry(
    lanes=(CANDIDATE_UNCLASSIFIED_01,),
)

__all__ = [
    "SOURCES",
    "CANDIDATE_UNCLASSIFIED_01",
]
