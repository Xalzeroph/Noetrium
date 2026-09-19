from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_LATER_RELEASED_LATS_REPO = MethodSourceLane(
    lane_id='later_released_lats_repo',
    kind=MethodSourceLaneKind('later_released_executable'),
    repository='https://github.com/andyz245/LanguageAgentTreeSearch',
    commit='853d81614607dd27433faf17c7b0a7d660f95d22',
    artifacts=('webshop/lats.py', 'webshop/lats.sh'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_LATER_RELEASED_LATS_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_LATER_RELEASED_LATS_REPO",
]
