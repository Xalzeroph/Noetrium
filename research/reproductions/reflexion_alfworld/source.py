from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_REFLEXION_REPO = MethodSourceLane(
    lane_id='official_reflexion_repo',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/noahshinn/reflexion',
    commit='65001352fd8d1ce31e7aac79ebc470c9f1a09ee6',
    artifacts=('alfworld_runs/alfworld_trial.py', 'alfworld_runs/main.py', 'alfworld_runs/generate_reflections.py', 'alfworld_runs/run_reflexion.sh'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_REFLEXION_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_REFLEXION_REPO",
]
