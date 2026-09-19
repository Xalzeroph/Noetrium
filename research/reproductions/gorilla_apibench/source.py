from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
CANDIDATE_UNCLASSIFIED_01 = MethodSourceLane(
    lane_id='candidate_unclassified_01',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/ShishirPatil/gorilla',
    commit='c849d11833ce0d401df4ab5a4d854167ad861684',
    artifacts=(),
)

SOURCES = MethodSourceRegistry(
    lanes=(CANDIDATE_UNCLASSIFIED_01,),
)

__all__ = [
    "SOURCES",
    "CANDIDATE_UNCLASSIFIED_01",
]
