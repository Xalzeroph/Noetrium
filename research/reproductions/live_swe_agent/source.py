from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
CANDIDATE_UNCLASSIFIED_01 = MethodSourceLane(
    lane_id='candidate_unclassified_01',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/OpenAutoCoder/live-swe-agent',
    commit='f780bc5886b18eaa3b12e91c67740c3824d70b43',
    artifacts=(),
)

SOURCES = MethodSourceRegistry(
    lanes=(CANDIDATE_UNCLASSIFIED_01,),
)

__all__ = [
    "SOURCES",
    "CANDIDATE_UNCLASSIFIED_01",
]
