from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_TOT_REPO = MethodSourceLane(
    lane_id='official_tot_repo',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/princeton-nlp/tree-of-thought-llm',
    commit='8050e67d0e3a0fddc424d7fa5801538722a4c4cc',
    artifacts=('src/tot/methods/bfs.py', 'src/tot/tasks/game24.py'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_TOT_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_TOT_REPO",
]
