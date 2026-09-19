from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_REACT_REPO = MethodSourceLane(
    lane_id='official_react_repo',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/ysymyth/ReAct',
    commit='19c6bae532250cf57bd7465d7f5a87edf2fda8f6',
    artifacts=('alfworld.ipynb', 'base_config.yaml', 'prompts/alfworld_3prompts.json'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_REACT_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_REACT_REPO",
]
