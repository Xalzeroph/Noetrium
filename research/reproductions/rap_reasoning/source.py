from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_RAP_REPO = MethodSourceLane(
    lane_id='official_rap_repo',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/Ber666/RAP',
    commit='774817c228b3d5ddfc18de2318f3476128ecf6eb',
    artifacts=('rap/mcts.py', 'rap/blocksworld_mcts.py', 'data/blocksworld/step_4.json'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_RAP_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_RAP_REPO",
]
