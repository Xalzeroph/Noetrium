from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_PAPER_ERA_LITS_RELEASE = MethodSourceLane(
    lane_id='paper_era_lits_release',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/xinzhel/lits-llm',
    commit='4f522bb7bf5d5bfd68c42649efe44c566dfa039c',
    artifacts=('lits/agents/tree/mcts.py', 'lits/components/policy/concat.py', 'lits/components/transition/concat.py', 'lits/components/reward/generative.py', 'demos/lits_benchmark/math_qa.py'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_PAPER_ERA_LITS_RELEASE,),
)

__all__ = [
    "SOURCES",
    "SOURCE_PAPER_ERA_LITS_RELEASE",
]
