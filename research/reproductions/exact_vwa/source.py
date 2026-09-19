from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_LATER_RELEASED_EXACT_VWA = MethodSourceLane(
    lane_id='later_released_exact_vwa',
    kind=MethodSourceLaneKind('later_released_executable'),
    repository='https://github.com/microsoft/ExACT',
    commit='d08ebebca1b82aa2b48ce2850e9edc279894295a',
    artifacts=('shells/classifieds/rmcts_mad_som.sh', 'src/prompts/vwa/jsons/p_som_cot_id_actree_3s_final.json', 'src/agent/search_agent.py', 'src/agent/mcts_agent.py'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_LATER_RELEASED_EXACT_VWA,),
)

__all__ = [
    "SOURCES",
    "SOURCE_LATER_RELEASED_EXACT_VWA",
]
