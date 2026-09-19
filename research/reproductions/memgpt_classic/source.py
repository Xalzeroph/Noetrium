from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
CANDIDATE_UNCLASSIFIED_01 = MethodSourceLane(
    lane_id='candidate_unclassified_01',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/letta-ai/letta',
    commit='15540c24ac328c995fb11f89d2e228cde508ab37',
    artifacts=(),
)

CANDIDATE_UNCLASSIFIED_02 = MethodSourceLane(
    lane_id='candidate_unclassified_02',
    kind=MethodSourceLaneKind.CANDIDATE,
    repository='https://github.com/letta-ai/letta',
    commit='12ca6e98affc9d774b7ddc0e087217122ba2a74b',
    artifacts=(),
)

SOURCES = MethodSourceRegistry(
    lanes=(CANDIDATE_UNCLASSIFIED_01, CANDIDATE_UNCLASSIFIED_02,),
)

__all__ = [
    "SOURCES",
    "CANDIDATE_UNCLASSIFIED_01",
    "CANDIDATE_UNCLASSIFIED_02",
]
