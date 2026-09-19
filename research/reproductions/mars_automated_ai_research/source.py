from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_GENERATED_CODE_AND_TRAJECTORIES = MethodSourceLane(
    lane_id='official_generated_code_and_trajectories',
    kind=MethodSourceLaneKind('official_artifact'),
    repository='https://github.com/jfc43/MARS',
    commit='04fcc3c78ff40ce0100caa9c4d64a1673a49c712',
    artifacts=('README.md', 'exp-logs/mars_gemini-3-pro-preview_run_1/grading_report.json', 'exp-logs/mars_gemini-3-pro-preview_run_2/grading_report.json', 'exp-logs/mars_gemini-3-pro-preview_run_3/grading_report.json'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_GENERATED_CODE_AND_TRAJECTORIES,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_GENERATED_CODE_AND_TRAJECTORIES",
]
