from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_PRE_ARXIV_REPRODUCIBILITY_CUT = MethodSourceLane(
    lane_id='pre_arxiv_reproducibility_cut',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/MMWilliams/gats',
    commit='c8cb71cc23bc622e1711ec4bec274071a87940bc',
    artifacts=('README.md', 'reproduce.py', 'experiments/run_gats_eval.py', 'experiments/run_stress_test.py', 'tests/test_reproducibility.py', 'paper/main.tex'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_PRE_ARXIV_REPRODUCIBILITY_CUT,),
)

__all__ = [
    "SOURCES",
    "SOURCE_PRE_ARXIV_REPRODUCIBILITY_CUT",
]
